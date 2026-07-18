"""RPC client for trace operations."""

import logging
import re

from web3 import Web3

from app.config import Settings
from app.models.errors import RPCError, TraceNotAvailableError, TransactionNotFoundError
from app.services.web3_provider import Web3Provider
from app.utils.addresses import normalize_evm_address

logger = logging.getLogger(__name__)


class TraceRPCClient:
    """Handles RPC calls for transaction tracing."""

    def __init__(
        self,
        web3_provider: Web3Provider,
        settings: Settings | None = None,
    ):
        self.web3_provider = web3_provider
        self.max_writes = settings.max_sstore_ops if settings else 10_000
        self.max_steps = settings.max_trace_steps if settings else 5_000_000
        self.max_sha3_ops = settings.max_trace_sha3_ops if settings else 20_000
        self.max_preimage_bytes = (
            settings.max_trace_preimage_bytes if settings else 5 * 1024 * 1024
        )
        self.max_prestate_accounts = (
            settings.max_prestate_accounts if settings else 10_000
        )
        self.max_prestate_storage_entries = (
            settings.max_prestate_storage_entries if settings else 100_000
        )

    async def get_receipt(self, chain_id: int, tx_hash: str) -> dict:
        """Fetch transaction receipt with error handling."""
        try:
            receipt = await self.web3_provider.get_transaction_receipt(chain_id, tx_hash)
        except Exception as e:
            error_msg = str(e).lower()
            if "not found" in error_msg or "transaction receipt" in error_msg:
                raise TransactionNotFoundError(tx_hash)
            raise RPCError("eth_getTransactionReceipt", str(e))

        if receipt is None:
            raise TransactionNotFoundError(tx_hash)
        return receipt

    async def execute_prestate_trace(
        self,
        chain_id: int,
        tx_hash: str,
        *,
        diff_mode: bool = True,
    ) -> dict:
        """Execute debug_traceTransaction with prestateTracer."""
        tracer_config = {
            "tracer": "prestateTracer",
            "tracerConfig": {"diffMode": diff_mode},
        }

        try:
            result = await self.web3_provider.make_request(
                chain_id, "debug_traceTransaction", [tx_hash, tracer_config]
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
            if any(
                marker in error_msg.lower()
                for marker in (
                    "method not found",
                    "not supported",
                    "unknown tracer",
                    "debug api is disabled",
                )
            ):
                raise TraceNotAvailableError(error_msg)
            raise RPCError("debug_traceTransaction", error_msg)

        trace = result.get("result", {})
        self._validate_prestate_size(trace)
        return trace

    async def execute_structlogs_trace(
        self,
        chain_id: int,
        tx_hash: str,
    ) -> tuple[list[dict], list[dict], int]:
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

        Returns (sstores, sha3s) where sha3s contains preimage data.
        """
        compact = await self._execute_compact_storage_trace(chain_id, tx_hash)
        if compact is not None:
            return compact
        logger.warning(
            "Compact storage tracer unavailable for %s; raw structLogs are disabled",
            tx_hash,
        )
        return [], [], 0

    async def _execute_compact_storage_trace(
        self,
        chain_id: int,
        tx_hash: str,
    ) -> tuple[list[dict], list[dict], int] | None:
        """Run a compact node-side forensic tracer before raw struct logs.

        Full opcode traces can exceed provider response limits. This tracer
        returns only SSTORE/TSTORE and SHA3 evidence while retaining storage/
        code attribution and frame outcomes. Pre-write values are recovered by
        the extractor's full-prestate replay.
        """
        tracer = r"""
        {
          writes: [], sha3s: [], steps: 0, lastOp: null, lastDepth: null,
          sha3Bytes: 0,
          frames: {}, frameStack: [], pendingCalls: {}, nextFrameId: 1,
          effectiveCode: function(requested, db) {
            var requestedHex = toHex(requested).toLowerCase();
            var rawCode = toHex(db.getCode(requested)).toLowerCase();
            if (rawCode.length === 48 && rawCode.slice(0, 8) === '0xef0100') {
              return '0x' + rawCode.slice(8);
            }
            return requestedHex;
          },
          ensureRoot: function(log, db) {
            if (this.frameStack.length === 0) {
              var requested = log.contract.getAddress();
              var address = toHex(requested);
              this.frames[0] = {id: 0, parent: null, depth: log.getDepth(), storage: address, code: this.effectiveCode(requested, db), failed: false};
              this.frameStack.push(0);
            }
          },
          syncFrame: function(log, db) {
            var depth = log.getDepth();
            while (this.frameStack.length > 1 && this.currentFrame().depth > depth) {
              this.frameStack.pop();
            }
            while (this.currentFrame().depth < depth) {
              var parent = this.currentFrame();
              var pending = this.pendingCalls[depth];
              var address = toHex(log.contract.getAddress());
              var requested = pending && pending.code ? pending.code : log.contract.getAddress();
              var frameId = this.nextFrameId++;
              this.frames[frameId] = {
                id: frameId,
                parent: parent.id,
                depth: parent.depth + 1,
                storage: address,
                code: this.effectiveCode(requested, db),
                failed: false
              };
              this.frameStack.push(frameId);
              delete this.pendingCalls[depth];
            }
            if (this.currentFrame().depth === depth) {
              delete this.pendingCalls[depth + 1];
            }
          },
          currentFrame: function() {
            return this.frames[this.frameStack[this.frameStack.length - 1]];
          },
          step: function(log, db) {
            if (this.steps >= __MAX_STEPS__) {
              throw new Error('slotscan trace limit exceeded: steps');
            }
            this.lastOp = log.op.toString();
            this.lastDepth = log.getDepth();
            this.ensureRoot(log, db);
            this.syncFrame(log, db);
            var frame = this.currentFrame();
            var op = log.op.toString();

            if (op === 'SSTORE' || op === 'TSTORE') {
              if (this.writes.length >= __MAX_WRITES__) {
                throw new Error('slotscan trace limit exceeded: writes');
              }
              var slotValue = log.stack.peek(0);
              var value = log.stack.peek(1);
              var oldValue = null;
              this.writes.push({
                address: frame.storage,
                code_address: frame.code,
                code_attribution: 'exact',
                pc: log.getPC(),
                slot: '0x' + slotValue.toString(16),
                value: '0x' + value.toString(16),
                old_value: oldValue,
                opcode: op,
                namespace: op === 'SSTORE' ? 'persistent' : 'transient',
                depth: log.getDepth(),
                index: this.steps,
                frame_id: frame.id
              });
            } else if (op === 'SHA3' || op === 'KECCAK256') {
              var offset = parseInt(log.stack.peek(0).toString());
              var size = parseInt(log.stack.peek(1).toString());
              if (size >= 32 && size <= 256) {
                if (this.sha3s.length >= __MAX_SHA3S__ ||
                    this.sha3Bytes + size > __MAX_SHA3_BYTES__) {
                  throw new Error('slotscan trace limit exceeded: sha3');
                }
                this.sha3s.push({
                  address: frame.storage,
                  preimage: toHex(log.memory.slice(offset, offset + size)),
                  size: size,
                  depth: log.getDepth()
                });
                this.sha3Bytes += size;
              }
            }
            if (op === 'CALL' || op === 'STATICCALL' || op === 'DELEGATECALL' || op === 'CALLCODE') {
              this.pendingCalls[log.getDepth() + 1] = {
                type: op,
                code: toAddress(log.stack.peek(1))
              };
            } else if (op === 'CREATE' || op === 'CREATE2') {
              this.pendingCalls[log.getDepth() + 1] = {type: op, code: null};
            }
            if (log.getError()) frame.failed = true;
            this.steps += 1;
          },
          fault: function(log, db) {
            this.ensureRoot(log, db);
            this.currentFrame().failed = true;
          },
          result: function(ctx, db) {
            if (ctx.error && this.frames[0]) this.frames[0].failed = true;
            for (var i = 0; i < this.writes.length; i++) {
              var write = this.writes[i];
              var current = write.frame_id;
              var failed = [];
              while (current !== null && current !== undefined) {
                var frame = this.frames[current];
                if (frame.failed) failed.push(current);
                current = frame.parent;
              }
              var ownFrame = this.frames[write.frame_id];
              write.frame_parent_id = ownFrame.parent;
              write.frame_failed = ownFrame.failed;
              write.frame_reverted = failed.length > 0;
              write.rollback_frame_id = failed.length > 0 ? failed[0] : null;
              write.rollback_parent_id = failed.length > 1 ? failed[1] : null;
            }
            return {writes: this.writes, sha3s: this.sha3s, stepCount: this.steps, lastOp: this.lastOp, lastDepth: this.lastDepth};
          }
        }
        """
        tracer = (
            tracer.replace("__MAX_STEPS__", str(self.max_steps))
            .replace("__MAX_WRITES__", str(self.max_writes))
            .replace("__MAX_SHA3S__", str(self.max_sha3_ops))
            .replace("__MAX_SHA3_BYTES__", str(self.max_preimage_bytes))
        )
        try:
            response = await self.web3_provider.make_request(
                chain_id,
                "debug_traceTransaction",
                [tx_hash, {"tracer": tracer}],
            )
        except Exception as exc:
            logger.info("Compact storage tracer unavailable: %s", exc)
            return None

        if "error" in response:
            if "slotscan trace limit exceeded" in str(response["error"]).lower():
                raise TraceNotAvailableError("Trace exceeds configured limits")
            logger.info(
                "Compact storage tracer rejected: %s",
                response["error"],
            )
            return None
        result = response.get("result")
        if not isinstance(result, dict) or "writes" not in result:
            return None

        writes = result.get("writes") or []
        for write in writes:
            write["slot"] = self._normalize_slot(write.get("slot", "0x0"))
            write["value"] = self._normalize_value(write.get("value", "0x0"))
            if write.get("old_value") is not None:
                write["old_value"] = self._normalize_value(write["old_value"])
            write["address"] = normalize_evm_address(write.get("address"))
            write["code_address"] = normalize_evm_address(write.get("code_address"))

        step_count = int(result.get("stepCount") or 0)
        sha3s = result.get("sha3s") or []
        self._validate_compact_limits(writes, sha3s, step_count)
        for operation in sha3s:
            preimage = self._normalize_preimage(operation.get("preimage"))
            if not preimage:
                operation["preimage"] = None
                operation["hash"] = None
                continue
            operation["preimage"] = preimage
            operation["hash"] = Web3.keccak(
                bytes.fromhex(preimage.removeprefix("0x"))
            ).hex()
        logger.info(
            "Compact storage trace: steps=%s, writes=%s, sha3s=%s, last=%s@%s",
            step_count,
            len(writes),
            len(sha3s),
            result.get("lastOp"),
            result.get("lastDepth"),
        )
        return writes, sha3s, step_count

    def _validate_compact_limits(
        self,
        writes: list[dict],
        sha3s: list[dict],
        step_count: int,
    ) -> None:
        if len(writes) > self.max_writes:
            raise TraceNotAvailableError("Trace exceeds the configured write limit")
        if step_count > self.max_steps:
            raise TraceNotAvailableError("Trace exceeds the configured step limit")
        if len(sha3s) > self.max_sha3_ops:
            raise TraceNotAvailableError("Trace exceeds the configured SHA3 limit")

        preimage_bytes = 0
        for operation in sha3s:
            preimage = operation.get("preimage")
            if isinstance(preimage, str):
                preimage_bytes += (len(preimage.removeprefix("0x")) + 1) // 2
            if preimage_bytes > self.max_preimage_bytes:
                raise TraceNotAvailableError(
                    "Trace exceeds the configured preimage limit"
                )

    def _validate_prestate_size(self, trace: dict) -> None:
        if not isinstance(trace, dict):
            raise TraceNotAvailableError("Prestate trace is malformed")

        sides = (
            (trace.get("pre", {}), trace.get("post", {}))
            if "pre" in trace or "post" in trace
            else (trace,)
        )
        account_count = 0
        storage_count = 0
        for accounts in sides:
            if not isinstance(accounts, dict):
                raise TraceNotAvailableError("Prestate trace is malformed")
            account_count += len(accounts)
            if account_count > self.max_prestate_accounts:
                raise TraceNotAvailableError(
                    "Prestate trace exceeds the configured account limit"
                )
            for state in accounts.values():
                if not isinstance(state, dict):
                    continue
                storage = state.get("storage", {})
                if isinstance(storage, dict):
                    storage_count += len(storage)
                if storage_count > self.max_prestate_storage_entries:
                    raise TraceNotAvailableError(
                        "Prestate trace exceeds the configured storage limit"
                    )

    def _parse_structlogs(
        self,
        struct_logs: list[dict],
        tx_to_address: str | None,
        include_memory: bool,
    ) -> tuple[list[dict], list[dict]]:
        """Parse structLogs to extract SSTORE and SHA3 operations."""
        if len(struct_logs) > self.max_steps:
            raise TraceNotAvailableError("Trace exceeds the configured step limit")

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
                            created_addr = normalize_evm_address(stack[-1])
                            if created_addr and created_addr != "0x" + "0" * 40:
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
        sha3_bytes = 0
        pending_sha3 = None

        call_stack: list[tuple[str, str]] = []
        if tx_to_address:
            normalized_to = normalize_evm_address(tx_to_address)
            if normalized_to:
                call_stack.append((normalized_to, normalized_to))

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
                        preimage = pending_sha3.get("preimage")
                        pending_bytes = (
                            (len(preimage.removeprefix("0x")) + 1) // 2
                            if isinstance(preimage, str)
                            else 0
                        )
                        if (
                            len(sha3s) >= self.max_sha3_ops
                            or sha3_bytes + pending_bytes
                            > self.max_preimage_bytes
                        ):
                            raise TraceNotAvailableError(
                                "Trace exceeds the configured SHA3 limit"
                            )
                        pending_sha3["hash"] = self._normalize_slot(hash_result)
                        sha3s.append(pending_sha3)
                        sha3_bytes += pending_bytes
                pending_sha3 = None

            if op in ("CALL", "STATICCALL"):
                if len(stack) >= 2:
                    addr_hex = stack[-2]
                    if addr_hex:
                        try:
                            addr_clean = normalize_evm_address(addr_hex)
                            if addr_clean:
                                call_stack.append((addr_clean, addr_clean))
                        except Exception:
                            pass

            elif op in ("DELEGATECALL", "CALLCODE"):
                if len(stack) >= 2:
                    addr_hex = stack[-2]
                    if addr_hex:
                        try:
                            code_addr = normalize_evm_address(addr_hex)
                            current_storage = call_stack[-1][0] if call_stack else ""
                            if code_addr:
                                call_stack.append((current_storage, code_addr))
                        except Exception:
                            pass

            current_storage_address = call_stack[-1][0] if call_stack else ""
            current_code_address = call_stack[-1][1] if call_stack else ""

            if op in ("SSTORE", "TSTORE"):
                if len(stack) >= 2:
                    if len(sstores) >= self.max_writes:
                        raise TraceNotAvailableError(
                            "Trace exceeds the configured write limit"
                        )
                    slot = stack[-1]
                    value = stack[-2]
                    normalized_slot = self._normalize_slot(slot)
                    sstores.append({
                        "address": current_storage_address,
                        "code_address": current_code_address,
                        "code_attribution": "inferred",
                        "pc": pc,
                        "slot": normalized_slot,
                        "value": self._normalize_value(value),
                        # Geth/Reth storage snapshots on the SSTORE structLog
                        # can represent post-op state. Initial values are
                        # recovered from prestateTracer and then replayed.
                        "old_value": None,
                        "opcode": op,
                        "namespace": "persistent" if op == "SSTORE" else "transient",
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

        self._annotate_frame_outcomes(struct_logs, sstores)
        return sstores, sha3s

    def _annotate_frame_outcomes(
        self, struct_logs: list[dict], writes: list[dict]
    ) -> None:
        """Attach stable frame ids and rollback outcomes to captured writes."""
        if not struct_logs:
            return

        root_depth = struct_logs[0].get("depth", 1)
        frames: dict[int, dict] = {
            0: {"parent": None, "failed": False, "depth": root_depth}
        }
        frame_stack: list[tuple[int, int]] = [(root_depth, 0)]
        step_frames: dict[int, int] = {}
        next_frame_id = 1

        for index, log in enumerate(struct_logs):
            depth = log.get("depth", root_depth)
            while frame_stack and frame_stack[-1][0] > depth:
                frame_stack.pop()

            if not frame_stack:
                frame_stack.append((root_depth, 0))

            while frame_stack[-1][0] < depth:
                parent_id = frame_stack[-1][1]
                frame_id = next_frame_id
                next_frame_id += 1
                child_depth = frame_stack[-1][0] + 1
                frames[frame_id] = {
                    "parent": parent_id,
                    "failed": False,
                    "depth": child_depth,
                }
                frame_stack.append((child_depth, frame_id))

            frame_id = frame_stack[-1][1]
            step_frames[index] = frame_id
            op = log.get("op", "")
            if op in {"REVERT", "INVALID"} or log.get("error"):
                frames[frame_id]["failed"] = True

        def frame_reverted(frame_id: int) -> bool:
            current: int | None = frame_id
            while current is not None:
                frame = frames[current]
                if frame["failed"]:
                    return True
                current = frame["parent"]
            return False

        def rollback_context(frame_id: int) -> tuple[int | None, int | None]:
            failed_ancestors = []
            current: int | None = frame_id
            while current is not None:
                frame = frames[current]
                if frame["failed"]:
                    failed_ancestors.append(current)
                current = frame["parent"]
            rollback_id = failed_ancestors[0] if failed_ancestors else None
            rollback_parent = (
                failed_ancestors[1] if len(failed_ancestors) > 1 else None
            )
            return rollback_id, rollback_parent

        for write in writes:
            frame_id = step_frames.get(write.get("index", -1), 0)
            rollback_id, rollback_parent = rollback_context(frame_id)
            write["frame_id"] = frame_id
            write["frame_parent_id"] = frames[frame_id]["parent"]
            write["frame_failed"] = frames[frame_id]["failed"]
            write["frame_reverted"] = frame_reverted(frame_id)
            write["rollback_frame_id"] = rollback_id
            write["rollback_parent_id"] = rollback_parent

    def _extract_memory_slice(self, memory: list[str], offset: int, size: int) -> str | None:
        """Extract a slice from EVM memory."""
        if not memory:
            return None

        try:
            full_memory = "".join(
                word.removeprefix("0x").removeprefix("0X")
                for word in memory
            )
            if not re.fullmatch(r"[0-9a-fA-F]*", full_memory):
                return None
            start_nibble = offset * 2
            requested_nibbles = size * 2
            slice_hex = full_memory[
                start_nibble : start_nibble + requested_nibbles
            ].ljust(requested_nibbles, "0")
            return "0x" + slice_hex if requested_nibbles else None
        except Exception as e:
            logger.debug(f"Failed to extract memory slice: {e}")
            return None

    @staticmethod
    def _normalize_preimage(preimage: str | None) -> str | None:
        if not preimage:
            return None
        clean = re.sub(r"0x", "", preimage, flags=re.IGNORECASE)
        if len(clean) % 2 or not re.fullmatch(r"[0-9a-fA-F]+", clean):
            return None
        return "0x" + clean.lower()

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
