"""RPC client for trace operations."""

import logging
from typing import Optional

from web3 import Web3

from app.models.errors import RPCError, TraceNotAvailableError, TransactionNotFoundError
from app.services.web3_provider import Web3Provider

logger = logging.getLogger(__name__)


class TraceRPCClient:
    """Handles RPC calls for transaction tracing."""

    def __init__(self, web3_provider: Web3Provider):
        self.web3_provider = web3_provider

    async def get_receipt(self, chain_id: int, tx_hash: str) -> dict:
        """Fetch transaction receipt with error handling."""
        web3 = self.web3_provider.get_web3(chain_id)
        try:
            receipt = await web3.eth.get_transaction_receipt(tx_hash)
        except Exception as e:
            error_msg = str(e).lower()
            if "not found" in error_msg or "transaction receipt" in error_msg:
                raise TransactionNotFoundError(tx_hash)
            raise RPCError("eth_getTransactionReceipt", str(e))

        if receipt is None:
            raise TransactionNotFoundError(tx_hash)
        return receipt

    async def execute_prestate_trace(self, chain_id: int, tx_hash: str) -> dict:
        """Execute debug_traceTransaction with prestateTracer."""
        web3 = self.web3_provider.get_web3(chain_id)

        tracer_config = {
            "tracer": "prestateTracer",
            "tracerConfig": {"diffMode": True},
        }

        try:
            result = await web3.provider.make_request(
                "debug_traceTransaction", [tx_hash, tracer_config]
            )
        except Exception as e:
            error_msg = str(e).lower()
            if "method not found" in error_msg or "not supported" in error_msg:
                raise TraceNotAvailableError(
                    "Node does not support debug_traceTransaction"
                )
            raise RPCError("debug_traceTransaction", str(e))

        if "error" in result:
            error = result["error"]
            if isinstance(error, dict):
                error_msg = error.get("message", str(error))
            else:
                error_msg = str(error)
            raise RPCError("debug_traceTransaction", error_msg)

        return result.get("result", {})

    async def execute_structlogs_trace(
        self, chain_id: int, tx_hash: str, tx_to_address: str | None = None
    ) -> tuple[list[dict], list[dict]]:
        """
        Parse structLogs to extract SSTORE and SHA3 operations.

        Uses the standard structLogs format with memory/stack access. Works on all
        nodes with debug_traceTransaction support.

        For SHA3/KECCAK256:
        - When the opcode executes, stack has [offset, size]
        - Memory contains the preimage at memory[offset:offset+size]
        - The hash result appears on the stack in the NEXT step

        Address tracking handles:
        - CALL/STATICCALL: New context with target's storage
        - DELEGATECALL/CALLCODE: Code from target but storage stays with caller
        - CREATE/CREATE2: New contract created, constructor writes to new contract's storage

        Args:
            tx_to_address: The transaction's "to" address (top-level contract at depth=1)

        Returns (sstores, sha3s) where sha3s contains preimage data.
        """
        web3 = self.web3_provider.get_web3(chain_id)
        include_memory = True
        sha3_from_tracer = []

        try:
            result = await web3.provider.make_request(
                "debug_traceTransaction",
                [tx_hash, {
                    "enableMemory": True,
                    "enableReturnData": True,
                }]
            )
        except Exception as e:
            logger.warning(f"structLogs trace failed for {tx_hash}: {e}")
            return [], []

        if "error" in result:
            error = result["error"]
            error_msg = error.get("message", str(error)) if isinstance(error, dict) else str(error)

            if "too big" in error_msg.lower() or "exceeded" in error_msg.lower():
                logger.info(f"structLogs trace too large for {tx_hash}, using custom SHA3 tracer + no-memory structLogs")
                sha3_from_tracer = await self._get_sha3_via_custom_tracer(web3, tx_hash)

                try:
                    result = await web3.provider.make_request(
                        "debug_traceTransaction",
                        [tx_hash, {
                            "disableMemory": True,
                            "disableStorage": True,
                            "enableReturnData": False,
                        }]
                    )
                    include_memory = False
                    if "error" in result:
                        logger.warning(f"structLogs trace (no memory) error for {tx_hash}: {result['error']}")
                        return [], []
                except Exception as e2:
                    logger.warning(f"structLogs trace (no memory) failed for {tx_hash}: {e2}")
                    return [], []
            else:
                logger.warning(f"structLogs trace error for {tx_hash}: {error_msg}")
                return [], []

        struct_logs = result.get("result", {}).get("structLogs", [])
        if not struct_logs:
            logger.warning(f"No structLogs in trace for {tx_hash}")
            return [], []

        logger.info(f"structLogs trace: {len(struct_logs)} steps (memory={'enabled' if include_memory else 'disabled'})")

        # Parse the structLogs
        sstores, sha3s = self._parse_structlogs(struct_logs, tx_to_address, include_memory)

        if sha3_from_tracer:
            sha3s = sha3_from_tracer
            logger.info(f"structLogs parsed: sstores={len(sstores)}, sha3s={len(sha3s)} (from custom tracer)")
        else:
            logger.info(f"structLogs parsed: sstores={len(sstores)}, sha3s={len(sha3s)}")

        return sstores, sha3s

    def _parse_structlogs(
        self,
        struct_logs: list[dict],
        tx_to_address: str | None,
        include_memory: bool,
    ) -> tuple[list[dict], list[dict]]:
        """Parse structLogs to extract SSTORE and SHA3 operations."""
        # PASS 1: Find all CREATE/CREATE2 and their resulting addresses
        create_info: dict[int, dict] = {}
        MAX_CONSTRUCTOR_STEPS = 100_000

        for i, log in enumerate(struct_logs):
            op = log.get("op", "")
            if op in ("CREATE", "CREATE2"):
                depth = log.get("depth", 1)
                search_end = min(i + 1 + MAX_CONSTRUCTOR_STEPS, len(struct_logs))
                for j in range(i + 1, search_end):
                    if struct_logs[j].get("depth", 1) == depth:
                        stack = struct_logs[j].get("stack", [])
                        if stack:
                            created_addr = "0x" + stack[-1][-40:].lower()
                            if created_addr != "0x" + "0" * 40:
                                create_info[i] = {
                                    "start_step": i,
                                    "end_step": j,
                                    "created_address": created_addr,
                                    "constructor_depth": depth + 1,
                                }
                        break

        logger.info(f"Found {len(create_info)} CREATE/CREATE2 operations")

        # PASS 2: Parse SSTOREs and SHA3s with proper address tracking
        sstores = []
        sha3s = []
        pending_sha3 = None

        call_stack: list[tuple[str, str]] = []
        if tx_to_address:
            call_stack.append((tx_to_address.lower(), tx_to_address.lower()))

        active_creates: list[dict] = []

        for i, log in enumerate(struct_logs):
            op = log.get("op", "")
            depth = log.get("depth", 1)
            pc = log.get("pc", 0)
            stack = log.get("stack", [])
            memory = log.get("memory", [])

            while len(call_stack) > depth:
                call_stack.pop()

            while active_creates and i >= active_creates[-1]["end_step"]:
                active_creates.pop()

            if i in create_info:
                info = create_info[i]
                active_creates.append(info)
                call_stack.append((info["created_address"], info["created_address"]))

            if pending_sha3 is not None:
                if stack:
                    hash_result = stack[-1] if stack else None
                    if hash_result:
                        pending_sha3["hash"] = self._normalize_slot(hash_result)
                        sha3s.append(pending_sha3)
                pending_sha3 = None

            if op in ("CALL", "STATICCALL"):
                if len(stack) >= 2:
                    addr_hex = stack[-2]
                    if addr_hex:
                        try:
                            addr_clean = "0x" + addr_hex[-40:].lower()
                            call_stack.append((addr_clean, addr_clean))
                        except Exception:
                            pass

            elif op in ("DELEGATECALL", "CALLCODE"):
                if len(stack) >= 2:
                    addr_hex = stack[-2]
                    if addr_hex:
                        try:
                            code_addr = "0x" + addr_hex[-40:].lower()
                            current_storage = call_stack[-1][0] if call_stack else ""
                            call_stack.append((current_storage, code_addr))
                        except Exception:
                            pass

            current_storage_address = call_stack[-1][0] if call_stack else ""

            if op == "SSTORE":
                if len(stack) >= 2:
                    slot = stack[-1]
                    value = stack[-2]
                    sstores.append({
                        "address": current_storage_address,
                        "pc": pc,
                        "slot": self._normalize_slot(slot),
                        "value": self._normalize_value(value),
                        "depth": depth,
                        "index": i,
                    })

            elif op in ("SHA3", "KECCAK256"):
                if len(stack) >= 2:
                    try:
                        offset = int(stack[-1], 16) if isinstance(stack[-1], str) else stack[-1]
                        size = int(stack[-2], 16) if isinstance(stack[-2], str) else stack[-2]
                    except (ValueError, TypeError):
                        continue

                    if 32 <= size <= 256 and include_memory:
                        preimage = self._extract_memory_slice(memory, offset, size)
                        pending_sha3 = {
                            "address": current_storage_address,
                            "preimage": preimage,
                            "size": size,
                            "depth": depth,
                        }

        return sstores, sha3s

    def _extract_memory_slice(self, memory: list[str], offset: int, size: int) -> str | None:
        """Extract a slice from EVM memory."""
        if not memory:
            return None

        try:
            full_memory = "".join(memory)
            start_nibble = offset * 2
            end_nibble = (offset + size) * 2

            if end_nibble > len(full_memory):
                full_memory = full_memory + "0" * (end_nibble - len(full_memory))

            slice_hex = full_memory[start_nibble:end_nibble]
            return "0x" + slice_hex if slice_hex else None
        except Exception as e:
            logger.debug(f"Failed to extract memory slice: {e}")
            return None

    async def _get_sha3_via_custom_tracer(self, web3, tx_hash: str) -> list[dict]:
        """Get SHA3 preimages using a custom JS tracer."""
        tracer = """
        {
            data: [],
            step: function(log, db) {
                var op = log.op.toString();
                if (op === 'SHA3' || op === 'KECCAK256') {
                    var offset = log.stack.peek(0).valueOf();
                    var size = log.stack.peek(1).valueOf();
                    if (size >= 32 && size <= 256) {
                        this.data.push({
                            preimage: toHex(log.memory.slice(offset, offset + size)),
                            size: size
                        });
                    }
                }
            },
            fault: function(log, db) {},
            result: function(ctx, db) { return this.data; }
        }
        """

        try:
            result = await web3.provider.make_request(
                "debug_traceTransaction",
                [tx_hash, {"tracer": tracer}]
            )

            if "error" in result:
                logger.warning(f"Custom SHA3 tracer failed: {result['error']}")
                return []

            sha3_ops = result.get("result", [])
            logger.info(f"Custom SHA3 tracer: got {len(sha3_ops)} preimages")

            sha3_list = []
            for op in sha3_ops:
                preimage = op.get("preimage", "")
                if preimage:
                    preimage_bytes = bytes.fromhex(preimage[2:] if preimage.startswith("0x") else preimage)
                    hash_value = web3.keccak(preimage_bytes).hex()
                    sha3_list.append({
                        "preimage": preimage,
                        "hash": hash_value,
                        "size": int(op.get("size", 64)),
                    })

            return sha3_list

        except Exception as e:
            logger.warning(f"Custom SHA3 tracer error: {e}")
            return []

    def _normalize_slot(self, slot: str) -> str:
        """Normalize slot to 66-char hex (0x + 64 chars)."""
        if isinstance(slot, int):
            return f"0x{slot:064x}"
        slot_clean = slot[2:] if slot.startswith("0x") else slot
        return f"0x{slot_clean.lower().zfill(64)}"

    def _normalize_value(self, value: str) -> str:
        """Normalize value to 66-char hex."""
        if isinstance(value, int):
            return f"0x{value:064x}"
        value_clean = value[2:] if value.startswith("0x") else value
        return f"0x{value_clean.lower().zfill(64)}"
