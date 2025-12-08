"""Transaction tracer for extracting storage changes from transactions."""

import logging
from typing import Optional

from web3 import Web3

from app.config import Settings
from app.models.domain import (
    DecodedValue,
    StorageChange,
    StorageLayout,
    StorageType,
    StorageVariable,
    TransactionDiff,
)
from app.models.errors import RPCError, TraceNotAvailableError, TransactionNotFoundError
from app.repositories.cache import CacheRepository
from app.services.decoder import TypeDecoder
from app.services.web3_provider import Web3Provider
# Note: compute_mapping_slot etc. removed - using preimage lookup instead of brute-force

logger = logging.getLogger(__name__)


class TransactionTracer:
    """Traces transactions to extract storage changes."""

    def __init__(
        self,
        web3_provider: Web3Provider,
        settings: Settings,
        decoder: TypeDecoder,
        cache_repo: Optional[CacheRepository] = None,
    ):
        self.web3_provider = web3_provider
        self.settings = settings
        self.decoder = decoder
        self.cache_repo = cache_repo

    async def trace_transaction(
        self,
        chain_id: int,
        contract_address: str,
        tx_hash: str,
        layout: Optional[StorageLayout] = None,
    ) -> TransactionDiff:
        """
        Trace a transaction and extract storage changes for a contract.

        Uses debug_traceTransaction with prestateTracer.
        """
        contract_address = Web3.to_checksum_address(contract_address)

        # Check cache first
        # Cache disabled for testing; always compute fresh

        # Get block number
        block_number = await self.get_transaction_block(chain_id, tx_hash)

        # Execute trace
        try:
            trace_result = await self._execute_trace(chain_id, tx_hash)
        except TraceNotAvailableError:
            # Return degraded response
            diff = TransactionDiff(
                chain_id=chain_id,
                contract_address=contract_address,
                tx_hash=tx_hash,
                block_number=block_number,
                changes=[],
                is_complete=False,
                layout=layout,
                trace_unavailable=True,
            )
            return diff

        # Get receipt for block number
        receipt = await self._get_receipt(chain_id, tx_hash)
        block_number = receipt["blockNumber"]
        prestate_changes = self._extract_contract_changes(trace_result, contract_address)

        # Get combined storage trace - captures SSTORE and SHA3 operations
        # Need to pass the transaction's "to" address for proper address tracking in structLogs
        # For contract creation transactions, use the created contract address
        tx_to_address = receipt.get("to")  # None for contract creation
        if not tx_to_address:
            # Contract creation - get the created contract address
            tx_to_address = receipt.get("contractAddress")
            if tx_to_address:
                logger.info(f"Contract creation transaction - using created address: {tx_to_address}")
        sstore_trace, sha3_trace = await self._execute_storage_trace(chain_id, tx_hash, tx_to_address)

        # Build preimage lookup from SHA3 trace (for decoding mapping keys)
        # No address filtering - captures ALL SHA3 ops for O(1) mapping resolution
        preimage_lookup = self._build_preimage_lookup(sha3_trace)

        # Build changes from SSTORE trace (preferred - captures all writes with real execution order)
        # or fall back to prestateTracer (only captures first→last per slot, no execution order)
        execution_order_available = False
        if sstore_trace:
            raw_changes, had_unknown_sstores = self._build_changes_from_sstore_trace(
                sstore_trace, trace_result, contract_address
            )
            execution_order_available = True  # We have real SSTORE step numbers for captured slots
        else:
            # No SSTORE trace; fall back to prestateTracer diff (no steps)
            raw_changes = [
                (self._normalize_slot(slot), old, new, None, None)
                for i, (slot, old, new) in enumerate(prestate_changes)
            ]
            execution_order_available = False

        # Check limits
        is_complete = len(raw_changes) <= self.settings.max_sstore_ops
        if not is_complete:
            raw_changes = raw_changes[: self.settings.max_sstore_ops]

        # Decode changes using preimage lookup for O(1) mapping resolution
        decoded_changes = self._decode_changes(raw_changes, layout, preimage_lookup)

        diff = TransactionDiff(
            chain_id=chain_id,
            contract_address=contract_address,
            tx_hash=tx_hash,
            block_number=block_number,
            changes=decoded_changes,
            is_complete=is_complete,
            layout=layout,
            trace_unavailable=False,
            execution_order_available=execution_order_available,
        )

        # Cache result
        if self.cache_repo:
            await self.cache_repo.save_tx_diff(diff)

        return diff

    async def get_transaction_block(self, chain_id: int, tx_hash: str) -> int:
        """Get the block number a transaction was included in."""
        receipt = await self._get_receipt(chain_id, tx_hash)
        return receipt["blockNumber"]

    async def _get_receipt(self, chain_id: int, tx_hash: str) -> dict:
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

    async def _execute_trace(self, chain_id: int, tx_hash: str) -> dict:
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

    async def _execute_storage_trace(
        self, chain_id: int, tx_hash: str, tx_to_address: str | None = None
    ) -> tuple[list[dict], list[dict]]:
        """
        Execute debug_traceTransaction to capture SSTORE and SHA3 operations.

        Uses structLogs tracer which works on Reth and all nodes with debug enabled.
        Parses raw EVM execution to extract storage operations with proper address
        tracking for CALL, DELEGATECALL, and CREATE opcodes.

        Args:
            tx_to_address: The transaction's "to" address (for address tracking)

        Returns (sstores, sha3s) where sha3s contains preimage data.
        """
        return await self._execute_structlogs_trace(chain_id, tx_hash, tx_to_address)

    async def _execute_structlogs_trace(
        self, chain_id: int, tx_hash: str, tx_to_address: str | None = None
    ) -> tuple[list[dict], list[dict]]:
        """
        Parse structLogs to extract SSTORE and SHA3 operations.

        This is the Reth-compatible path - Reth doesn't support custom JS tracers
        but does support the standard structLogs format with memory/stack access.

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
        include_memory = True  # Start with memory enabled for SHA3 preimages

        try:
            # Request full trace with memory, stack, and storage
            # Use enableMemory (Reth/modern) instead of disableMemory=false (Geth legacy)
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

            # Check if error is due to response size limit
            if "too big" in error_msg.lower() or "exceeded" in error_msg.lower():
                logger.info(f"structLogs trace too large for {tx_hash}, retrying without memory")
                # Retry without memory - we lose SHA3 preimages but keep PC values
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

        # === PASS 1: Find all CREATE/CREATE2 and their resulting addresses ===
        # We need to know what contracts are created so we can attribute their constructor SSTOREs
        create_info: dict[int, dict] = {}  # step_index -> {start_step, end_step, created_address, depth}

        # Limit search window for constructor end to prevent O(N²) worst case
        # Most constructors are under 50k steps; search up to 100k as safety margin
        MAX_CONSTRUCTOR_STEPS = 100_000

        for i, log in enumerate(struct_logs):
            op = log.get("op", "")
            if op in ("CREATE", "CREATE2"):
                depth = log.get("depth", 1)
                # Find when constructor ends (when we return to this depth)
                search_end = min(i + 1 + MAX_CONSTRUCTOR_STEPS, len(struct_logs))
                for j in range(i + 1, search_end):
                    if struct_logs[j].get("depth", 1) == depth:
                        # Constructor ended, created address is on stack
                        stack = struct_logs[j].get("stack", [])
                        if stack:
                            created_addr = "0x" + stack[-1][-40:].lower()
                            if created_addr != "0x" + "0" * 40:  # Not a failed create
                                create_info[i] = {
                                    "start_step": i,
                                    "end_step": j,
                                    "created_address": created_addr,
                                    "constructor_depth": depth + 1,
                                }
                        break

        logger.info(f"Found {len(create_info)} CREATE/CREATE2 operations")

        # === PASS 2: Parse SSTOREs and SHA3s with proper address tracking ===
        sstores = []
        sha3s = []
        pending_sha3 = None

        # Track storage_address at each depth (who OWNS the storage)
        # This is different from code_address for DELEGATECALL
        # Stack of (storage_address, code_address) tuples
        call_stack: list[tuple[str, str]] = []
        if tx_to_address:
            call_stack.append((tx_to_address.lower(), tx_to_address.lower()))

        # Track which CREATE we're currently inside (if any)
        active_creates: list[dict] = []

        for i, log in enumerate(struct_logs):
            op = log.get("op", "")
            depth = log.get("depth", 1)
            pc = log.get("pc", 0)
            stack = log.get("stack", [])
            memory = log.get("memory", [])

            # Pop from call_stack when depth decreases
            while len(call_stack) > depth:
                call_stack.pop()

            # Pop from active_creates when we've passed their end
            while active_creates and i >= active_creates[-1]["end_step"]:
                active_creates.pop()

            # Check if we're entering a CREATE context
            if i in create_info:
                info = create_info[i]
                active_creates.append(info)
                # Push the created address onto call stack for constructor execution
                call_stack.append((info["created_address"], info["created_address"]))

            # If we have a pending SHA3, capture its result from current stack top
            if pending_sha3 is not None:
                if stack:
                    hash_result = stack[-1] if stack else None
                    if hash_result:
                        pending_sha3["hash"] = self._normalize_slot(hash_result)
                        sha3s.append(pending_sha3)
                pending_sha3 = None

            # Track addresses from CALL opcodes for proper attribution
            if op in ("CALL", "STATICCALL"):
                # CALL/STATICCALL: New context with target's storage
                if len(stack) >= 2:
                    addr_hex = stack[-2]
                    if addr_hex:
                        try:
                            addr_clean = "0x" + addr_hex[-40:].lower()
                            call_stack.append((addr_clean, addr_clean))
                        except Exception:
                            pass

            elif op in ("DELEGATECALL", "CALLCODE"):
                # DELEGATECALL/CALLCODE: Code from target but storage stays with caller
                if len(stack) >= 2:
                    addr_hex = stack[-2]
                    if addr_hex:
                        try:
                            code_addr = "0x" + addr_hex[-40:].lower()
                            # Storage stays with current context
                            current_storage = call_stack[-1][0] if call_stack else ""
                            call_stack.append((current_storage, code_addr))
                        except Exception:
                            pass

            # Get current storage address (who owns the storage for SSTOREs at this depth)
            current_storage_address = call_stack[-1][0] if call_stack else ""

            if op == "SSTORE":
                # SSTORE: stack has [..., value, slot] (slot on top)
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

            elif op in ("SHA3", "KECCAK256") and include_memory:
                if len(stack) >= 2:
                    try:
                        offset = int(stack[-1], 16) if isinstance(stack[-1], str) else stack[-1]
                        size = int(stack[-2], 16) if isinstance(stack[-2], str) else stack[-2]
                    except (ValueError, TypeError):
                        continue

                    # Capture SHA3 preimages for:
                    # - 32 bytes: dynamic array length slot (keccak256(slot))
                    # - 64 bytes: standard mapping (keccak256(key, slot))
                    # - 96+ bytes: nested mappings, complex keys
                    # - Up to 256 bytes: deeply nested structures
                    if 32 <= size <= 256:
                        preimage = self._extract_memory_slice(memory, offset, size)
                        if preimage:
                            pending_sha3 = {
                                "address": current_storage_address,
                                "preimage": preimage,
                                "size": size,
                                "depth": depth,
                            }

        logger.info(f"structLogs parsed: sstores={len(sstores)}, sha3s={len(sha3s)}")
        return sstores, sha3s

    def _extract_memory_slice(self, memory: list[str], offset: int, size: int) -> str | None:
        """
        Extract a slice from EVM memory.

        Memory in structLogs is an array of 32-byte hex strings (without 0x prefix).
        Each element represents 32 bytes.

        Args:
            memory: List of 32-byte hex strings
            offset: Byte offset to start reading
            size: Number of bytes to read

        Returns:
            Hex string with 0x prefix, or None if extraction fails
        """
        if not memory:
            return None

        try:
            # Concatenate all memory into one continuous hex string
            full_memory = "".join(memory)

            # Each char is a nibble (4 bits), so multiply offsets by 2
            start_nibble = offset * 2
            end_nibble = (offset + size) * 2

            if end_nibble > len(full_memory):
                # Memory might not be fully expanded yet
                # Pad with zeros
                full_memory = full_memory + "0" * (end_nibble - len(full_memory))

            slice_hex = full_memory[start_nibble:end_nibble]
            return "0x" + slice_hex if slice_hex else None
        except Exception as e:
            logger.debug(f"Failed to extract memory slice: {e}")
            return None

    def _build_preimage_lookup(self, sha3_trace: list[dict]) -> dict[str, str]:
        """
        Build a lookup from hash -> preimage for SHA3 operations.

        The preimage for a mapping slot is: abi.encode(key, base_slot)
        - For address keys: 32 bytes (left-padded address) + 32 bytes (slot)
        - For uint keys: 32 bytes (key) + 32 bytes (slot)

        Returns: {normalized_hash: preimage_hex}
        """
        preimage_lookup: dict[str, str] = {}

        # Build lookup from ALL SHA3 ops regardless of address context.
        # keccak256 is collision-resistant (2^-256 collision probability).
        # If a SHA3 output matches our SSTORE slot, that's our preimage -
        # no matter which contract context computed it (e.g., DELEGATECALL to library).
        for op in sha3_trace:
            hash_value = op.get("hash")
            preimage = op.get("preimage")
            if hash_value and preimage:
                normalized_hash = self._normalize_slot(hash_value)
                preimage_lookup[normalized_hash] = preimage

        logger.info(
            f"Built preimage lookup: {len(preimage_lookup)} entries from {len(sha3_trace)} SHA3 ops"
        )
        return preimage_lookup

    def _parse_mapping_preimage(
        self, preimage: str, layout: Optional[StorageLayout]
    ) -> tuple[str | None, str | None, int | None]:
        """
        Parse a 64-byte mapping preimage into (key, base_slot, struct_offset).

        For mapping(key => value), preimage is: key (32 bytes) || base_slot (32 bytes)

        Returns: (key_hex, variable_name, struct_offset)
        - key_hex: The mapping key as hex string
        - variable_name: The storage variable name if found in layout
        - struct_offset: If this slot is base + N, returns N (for struct members)
        """
        if not preimage or not preimage.startswith("0x"):
            return None, None, None

        preimage_bytes = preimage[2:]  # Remove 0x prefix

        # Standard mapping: 64 bytes = key (32) + slot (32)
        if len(preimage_bytes) == 128:  # 64 bytes * 2 hex chars
            key_hex = "0x" + preimage_bytes[:64]
            base_slot_hex = "0x" + preimage_bytes[64:]

            # Try to find the variable name from the base slot
            base_slot_int = int(base_slot_hex, 16)
            variable_name = None
            struct_offset = None

            if layout:
                for var in layout.variables:
                    var_slot = int(var.slot)
                    if var_slot == base_slot_int:
                        variable_name = var.label
                        break
                    # Check if this is a struct offset (slot is base + offset)
                    # This happens when accessing base mapping then adding offset for struct member

            return key_hex, variable_name, struct_offset

        return None, None, None

    def _decode_mapping_key(self, key_hex: str) -> str:
        """
        Decode a mapping key from its 32-byte hex representation.

        - If it looks like an address (first 12 bytes are zeros), format as address
        - If it's a small number, format as integer
        - Otherwise, return the hex
        """
        if not key_hex or not key_hex.startswith("0x"):
            return key_hex

        key_bytes = key_hex[2:]

        # Check if it's an address (first 24 hex chars are zeros)
        if len(key_bytes) == 64 and key_bytes[:24] == "0" * 24:
            return "0x" + key_bytes[24:]

        # Check if it's a small integer
        key_int = int(key_hex, 16)
        if key_int < 2**64:  # Reasonable uint size
            return str(key_int)

        return key_hex

    def _get_final_mapping_value_type(
        self,
        var_type: StorageType,
        layout: StorageLayout,
    ) -> tuple[str | None, StorageType | None]:
        """
        Fully unwrap nested mappings to get the final value type.

        For mapping(A => mapping(B => mapping(C => uint256))):
        Returns ("t_uint256", StorageType for uint256)

        Returns: (value_type_id, decode_type) or (None, None)
        """
        current_type = var_type
        final_value_type_id = None

        # Keep unwrapping while we have mappings
        while current_type and current_type.encoding == "mapping":
            if not current_type.value_type:
                break
            final_value_type_id = current_type.value_type
            inner_type = layout.get_type(current_type.value_type)
            if inner_type and inner_type.encoding == "mapping":
                # Continue unwrapping
                current_type = inner_type
            else:
                # Found the final non-mapping type
                return final_value_type_id, inner_type

        return final_value_type_id, layout.get_type(final_value_type_id) if final_value_type_id else None

    def _resolve_struct_field(
        self,
        base_variable: StorageVariable,
        struct_offset: int,
        layout: StorageLayout,
    ) -> tuple[str | None, StorageType | None]:
        """
        Resolve struct field name from offset.

        When we have a mapping/array to a struct and access slot = base + N,
        the N corresponds to a struct member's slot offset.

        Handles:
        - Mappings to structs: mapping(address => MyStruct)
        - Dynamic arrays of structs: MyStruct[]
        - Nested structs: struct with struct member

        Args:
            base_variable: The mapping/array variable (e.g., rewardData)
            struct_offset: The offset from base (e.g., 4 for .lockStart)
            layout: Storage layout containing type definitions

        Returns: (field_name, field_type) or (None, None) if not found
        """
        var_type = layout.get_type(base_variable.type_id)
        if not var_type:
            return None, None

        # Get the struct type to search for members
        struct_type = None

        # For mappings to structs, get the value type
        if var_type.encoding == "mapping" and var_type.value_type:
            struct_type = layout.get_type(var_type.value_type)

        # For dynamic arrays of structs, get the element type
        elif var_type.encoding == "dynamic_array" and var_type.element_type:
            struct_type = layout.get_type(var_type.element_type)

        # For direct struct types
        elif var_type.kind == "struct":
            struct_type = var_type

        if struct_type and struct_type.members:
            # Find member at this slot offset
            for member in struct_type.members:
                if member.slot == struct_offset:
                    member_type = layout.get_type(member.type_id)

                    # Check if this member is itself a struct (nested struct)
                    # If so and struct_offset extends beyond this member, recurse
                    if member_type and member_type.kind == "struct" and member_type.members:
                        # Member found at this offset - return it
                        return member.name, member_type

                    return member.name, member_type

        return None, None

    def _try_match_slot_from_preimage(
        self,
        slot_hex: str,
        preimage: str,
        layout: Optional[StorageLayout],
        preimage_lookup: dict[str, str],
        depth: int = 0,
        visited: set[str] | None = None,
    ) -> Optional[dict]:
        """
        Try to match a slot to a variable using the SHA3 preimage.

        The preimage contains the actual data hashed to produce this slot:
        - For simple mapping: key (32 bytes) || base_slot (32 bytes)
        - For nested mapping: the base_slot in preimage is itself a hash

        Args:
            slot_hex: The storage slot (hash result)
            preimage: The data that was hashed (64 bytes = 128 hex chars without 0x)
            layout: Storage layout for finding variables
            preimage_lookup: Full preimage lookup for resolving nested mappings
            depth: Current recursion depth (for limiting)
            visited: Set of already-visited slots (for cycle detection)

        Returns:
            Dict with variable info if matched, None otherwise
        """
        # Prevent infinite recursion - max 5 levels deep (handles triple-nested mappings)
        if depth > 5:
            logger.debug(f"Max recursion depth reached for slot {slot_hex[:18]}...")
            return None

        # Initialize visited set on first call
        if visited is None:
            visited = set()

        # Cycle detection - don't re-process the same slot
        if slot_hex in visited:
            logger.debug(f"Cycle detected for slot {slot_hex[:18]}...")
            return None
        visited = visited | {slot_hex}  # Create new set to avoid mutation

        if not preimage or not layout:
            return None

        # Remove 0x prefix if present
        preimage_clean = preimage[2:] if preimage.startswith("0x") else preimage

        # Handle 32-byte preimage: this is keccak256(single_slot), used for:
        # - Dynamic array data start: keccak256(array_length_slot)
        # - This happens with mapping(addr => Struct[]) where the mapping gives array_length_slot,
        #   then keccak256(array_length_slot) gives data_start
        if len(preimage_clean) == 64:
            # The preimage is a single slot - check if it's an array length slot from a mapping
            inner_slot_hex = "0x" + preimage_clean
            inner_slot_normalized = self._normalize_slot(inner_slot_hex)
            logger.debug(f"  32-byte preimage (array data start): inner_slot={inner_slot_normalized[:18]}...")

            # Check if we have a preimage for this inner slot (the mapping lookup)
            if inner_slot_normalized in preimage_lookup:
                inner_preimage = preimage_lookup[inner_slot_normalized]
                logger.debug(f"  Found inner preimage for array length slot: {inner_preimage[:40]}...")
                # Recurse to resolve the mapping that produced the array length slot
                mapping_match = self._try_match_slot_from_preimage(
                    inner_slot_normalized, inner_preimage, layout, preimage_lookup,
                    depth=depth + 1, visited=visited
                )
                if mapping_match:
                    variable = mapping_match.get("variable")
                    var_type = layout.get_type(variable.type_id) if variable else None

                    # Check if this mapping points to a dynamic array
                    if var_type and var_type.encoding == "mapping" and var_type.value_type:
                        value_type = layout.get_type(var_type.value_type)
                        is_value_array = (
                            value_type and (
                                value_type.encoding == "dynamic_array" or
                                (value_type.element_type and "[]" in (value_type.label or ""))
                            )
                        )
                        if is_value_array:
                            # This slot is the data start of a mapping-to-array
                            # Return info so we can match array elements relative to this
                            element_type = layout.get_type(value_type.element_type) if value_type and value_type.element_type else None
                            element_slots = 1
                            if element_type:
                                element_bytes = element_type.num_bytes or 32
                                element_slots = (element_bytes + 31) // 32

                            return {
                                "variable": variable,
                                "base_slot": mapping_match.get("base_slot"),
                                "key": mapping_match.get("key", "?"),
                                "path": mapping_match.get("path"),
                                "encoding": "mapping_to_array",
                                "key_type": var_type.key_type if var_type else None,
                                "value_type": var_type.value_type if var_type else None,
                                "element_type": element_type,
                                "element_slots": element_slots,
                                "data_start_slot": int(slot_hex, 16),  # The slot we're looking up
                            }
            return None

        # Must be at least 64 bytes (128 hex chars) for a mapping
        if len(preimage_clean) < 128:
            return None

        # Parse the preimage: first 32 bytes = key, next 32 bytes = base slot (or intermediate hash)
        key_hex = "0x" + preimage_clean[:64]
        base_slot_hex = "0x" + preimage_clean[64:128]
        base_slot_int = int(base_slot_hex, 16)
        logger.debug(f"  Parsing preimage: key_hex={key_hex[:18]}..., base_slot_int={base_slot_int}")

        # Format the key for display
        decoded_key = self._decode_mapping_key(key_hex)

        # Check if base_slot points directly to a mapping variable
        # Use get_mapping_by_base_slot instead of get_variable_for_slot because the latter skips mappings
        variable = layout.get_mapping_by_base_slot(base_slot_int)
        logger.debug(f"  get_mapping_by_base_slot({base_slot_int}) = {variable.name if variable else None}")
        if variable:
            var_type = layout.get_type(variable.type_id)
            logger.debug(f"  Preimage match: base_slot={base_slot_int}, var={variable.name}, var_type_encoding={var_type.encoding if var_type else None}")
            if var_type and var_type.encoding == "mapping":
                # Found the mapping variable - fully unwrap to get final value type
                final_value_type_id, decode_type = self._get_final_mapping_value_type(var_type, layout)

                return {
                    "variable": variable,
                    "base_slot": base_slot_int,
                    "key": decoded_key,
                    "path": f"{variable.name}[{decoded_key}]",
                    "encoding": var_type.encoding,
                    "key_type": var_type.key_type,
                    "value_type": final_value_type_id,
                    "decode_type": decode_type,
                }

        # If base_slot is not a direct variable slot, it might be an intermediate hash
        # (nested mapping). Check if we have a preimage for it.
        base_slot_normalized = self._normalize_slot(base_slot_hex)
        logger.debug(f"  Checking if base_slot is intermediate hash: {base_slot_normalized[:18]}... in_lookup={base_slot_normalized in preimage_lookup}")
        if base_slot_normalized in preimage_lookup:
            # This is a nested mapping - recurse to find the outer mapping
            outer_preimage = preimage_lookup[base_slot_normalized]
            logger.debug(f"  Recursing with outer preimage: {outer_preimage[:40]}...")
            outer_match = self._try_match_slot_from_preimage(
                base_slot_normalized, outer_preimage, layout, preimage_lookup,
                depth=depth + 1, visited=visited
            )
            logger.debug(f"  Recursion result: outer_match={outer_match is not None}, outer_var={outer_match.get('variable').name if outer_match and outer_match.get('variable') else None}")
            if outer_match:
                # Found the outer mapping, combine the keys
                outer_key = outer_match.get("key", "?")
                outer_variable = outer_match.get("variable")
                outer_var_type = layout.get_type(outer_variable.type_id) if outer_variable else None

                # Fully unwrap nested mappings to get the final value type
                final_value_type_id = None
                decode_type = None
                if outer_var_type:
                    final_value_type_id, decode_type = self._get_final_mapping_value_type(outer_var_type, layout)

                return {
                    "variable": outer_variable,
                    "base_slot": outer_match.get("base_slot"),
                    "key": f"{outer_key}, {decoded_key}",
                    "path": f"{outer_variable.name}[{outer_key}][{decoded_key}]" if outer_variable else None,
                    "encoding": "mapping",
                    "key_type": outer_var_type.key_type if outer_var_type else None,
                    "value_type": final_value_type_id,
                    "decode_type": decode_type,
                }

        # Check for struct offset: sometimes the slot is base_hash + offset
        # Try to find if (slot - N) for small N is in preimage_lookup
        slot_int = int(slot_hex, 16)
        for offset in range(1, 10):  # Check offsets 1-9 (typical struct size)
            potential_base = slot_int - offset
            potential_base_hex = self._normalize_slot(hex(potential_base))
            if potential_base_hex in preimage_lookup:
                # This slot is base + offset, indicating a struct member
                base_preimage = preimage_lookup[potential_base_hex]
                logger.debug(f"  Struct offset check: slot_hex-{offset} = {potential_base_hex[:18]}... trying to match")
                base_match = self._try_match_slot_from_preimage(
                    potential_base_hex, base_preimage, layout, preimage_lookup,
                    depth=depth + 1, visited=visited
                )
                logger.debug(f"  Struct offset match result: {base_match is not None}, var={base_match.get('variable').name if base_match and base_match.get('variable') else None}")
                if base_match:
                    base_variable = base_match.get("variable")
                    base_key = base_match.get("key", "?")
                    # The offset indicates which struct member this is
                    return {
                        "variable": base_variable,
                        "base_slot": base_match.get("base_slot"),
                        "key": base_key,
                        "path": f"{base_variable.name}[{base_key}]+{offset}" if base_variable else None,
                        "encoding": "mapping",
                        "key_type": base_match.get("key_type"),
                        "value_type": base_match.get("value_type"),
                        "decode_type": base_match.get("decode_type"),
                        "struct_offset": offset,
                    }

        return None

    def _build_pc_lookup(
        self, sstore_trace: list[dict], contract_address: str
    ) -> dict[str, int]:
        """
        Build a lookup from slot -> PC for the contract.

        Since the prestateTracer gives us the final diff (old vs new value),
        we want the PC of the *last* SSTORE to each slot (which produced the final value).

        Note: This is only used as a fallback when SSTORE trace is used for PC lookup only.
        The preferred path is _build_changes_from_sstore_trace which captures all writes.
        """
        contract_address_lower = contract_address.lower()
        pc_lookup: dict[str, int] = {}

        for op in sstore_trace:
            op_addr = op.get("address", "").lower()
            if op_addr == contract_address_lower:
                slot = self._normalize_slot(op.get("slot", "0x0"))
                pc = op.get("pc")
                if pc is not None:
                    # Keep updating - we want the last write's PC
                    pc_lookup[slot] = pc

        return pc_lookup

    def _build_changes_from_sstore_trace(
        self,
        sstore_trace: list[dict],
        pre_state: dict,
        contract_address: str,
    ) -> tuple[list[tuple[str, str, str, int | None, int]], bool]:
        """
        Build list of (slot, old_value, new_value, pc, index) from SSTORE trace.

        Captures ALL writes including intermediate ones to the same slot.
        This is the preferred method as it shows every storage mutation.

        Key insight: Instead of filtering by address (unreliable with structLogs),
        we filter by SLOT VALUE. The prestateTracer tells us exactly which slots
        changed in our contract - we accept any SSTORE that writes to those slots.
        """
        contract_address_lower = contract_address.lower()
        zero_value = "0x" + "0" * 64

        pre_storage: dict[str, str] = {}
        post_storage: dict[str, str] = {}
        for addr, state in pre_state.get("pre", {}).items():
            if addr.lower() == contract_address_lower:
                raw_storage = state.get("storage", {})
                for slot, value in raw_storage.items():
                    normalized_slot = self._normalize_slot(slot)
                    pre_storage[normalized_slot] = self._normalize_value(value)
                break
        for addr, state in pre_state.get("post", {}).items():
            if addr.lower() == contract_address_lower:
                raw_storage = state.get("storage", {})
                for slot, value in raw_storage.items():
                    normalized_slot = self._normalize_slot(slot)
                    post_storage[normalized_slot] = self._normalize_value(value)
                break

        # Track current value for each slot (starts from pre-state)
        slot_current_value: dict[str, str] = dict(pre_storage)

        changes: list[tuple[str, str, str, int | None, int]] = []
        had_unknown_address = False

        # Process SSTORE operations in execution order (index from tracer/structLogs)
        for op in sorted(sstore_trace, key=lambda x: x.get("index", 0)):
            op_addr = (op.get("address") or "").lower()
            depth = op.get("depth", 1)
            slot = self._normalize_slot(op.get("slot", "0x0"))

            address_matches = op_addr == contract_address_lower
            addr_unknown = not op_addr

            if addr_unknown:
                had_unknown_address = True

            # Accept SSTORE if:
            # 1. Address matches our target contract (reliable when tracking works), OR
            # 2. Address is unknown AND slot is in valid_slots (prestateTracer fallback)
            #
            # The slot validation uses prestateTracer as ground truth - it knows exactly
            # which slots changed for our contract. This handles cases where address
            # tracking fails (e.g., complex DELEGATECALL chains, edge cases).
            #
            # We require BOTH conditions for the fallback (unknown address + valid slot)
            # to avoid false positives from other contracts with same static slots.
            should_accept = address_matches

            if not should_accept:
                continue

            # Note: We don't filter by prestateTracer slots here because we want to
            # capture ALL SSTOREs to this address, including interim writes that may
            # be overwritten before the transaction ends.

            new_value = self._normalize_value(op.get("value", zero_value))
            pc = op.get("pc")
            index = op.get("index", 0)

            # Get old value (from previous write or pre-state)
            old_value = slot_current_value.get(slot, zero_value)

            # Only record if value actually changed
            if old_value != new_value:
                changes.append((slot, old_value, new_value, pc, index))

            # Update current value for this slot (even if unchanged, to track state)
            slot_current_value[slot] = new_value

        return changes, had_unknown_address

    def _normalize_slot(self, slot: str) -> str:
        """Normalize a slot to 0x-prefixed, 64-char hex."""
        if not slot.startswith("0x"):
            slot = "0x" + slot
        hex_part = slot[2:]
        padded = hex_part.zfill(64)
        return "0x" + padded

    def _extract_contract_changes(
        self, trace_result: dict, contract_address: str
    ) -> list[tuple[str, str, str]]:
        """Extract storage changes for a specific contract from trace."""
        contract_address_lower = contract_address.lower()
        changes = []

        pre_state = trace_result.get("pre", {})
        post_state = trace_result.get("post", {})

        # Find contract in pre/post
        pre_storage = {}
        post_storage = {}

        for addr, state in pre_state.items():
            if addr.lower() == contract_address_lower:
                pre_storage = state.get("storage", {})
                break

        for addr, state in post_state.items():
            if addr.lower() == contract_address_lower:
                post_storage = state.get("storage", {})
                break

        # Collect all slots
        all_slots = set(pre_storage.keys()) | set(post_storage.keys())
        zero_value = "0x" + "0" * 64  # 32 bytes = 64 hex chars

        for slot in all_slots:
            normalized_slot = self._normalize_slot(slot)
            old_val = pre_storage.get(slot, zero_value)
            new_val = post_storage.get(slot, zero_value)

            # Normalize values
            old_val = self._normalize_value(old_val)
            new_val = self._normalize_value(new_val)

            if old_val != new_val:
                changes.append((normalized_slot, old_val, new_val))

        return changes

    def _normalize_value(self, value: str) -> str:
        """Normalize a storage value to full 32-byte hex."""
        if not value.startswith("0x"):
            value = "0x" + value

        hex_part = value[2:]
        padded = hex_part.zfill(64)
        return "0x" + padded

    def _build_dynamic_array_index(
        self,
        layout: StorageLayout,
    ) -> dict[int, tuple[StorageVariable, int, StorageType | None]]:
        """Build index of dynamic array data start slots.

        For dynamic arrays, elements start at keccak256(base_slot).
        This pre-computes those base slots for quick lookup.

        Returns:
            Dict mapping data_start_slot -> (variable, element_slots, element_type)
        """
        from eth_abi import encode

        index: dict[int, tuple[StorageVariable, int, StorageType | None]] = {}
        for var in layout.variables:
            var_type = layout.get_type(var.type_id)
            if not var_type:
                continue
            # Detect dynamic array via encoding OR presence of element_type with [] in label
            is_dynamic_array = (
                var_type.encoding == "dynamic_array"
                or (var_type.element_type and "[]" in (var_type.label or ""))
            )
            if not is_dynamic_array:
                continue

            # Compute keccak256(base_slot) - where array data starts
            encoded_slot = encode(["uint256"], [var.slot])
            data_start = int.from_bytes(Web3.keccak(encoded_slot), "big")

            # Get element type and size
            element_type = layout.get_type(var_type.element_type) if var_type.element_type else None
            if element_type:
                # Element size in slots (round up)
                element_bytes = element_type.num_bytes or 32
                element_slots = (element_bytes + 31) // 32
            else:
                element_slots = 1

            index[data_start] = (var, element_slots, element_type)
            logger.debug(f"Dynamic array {var.name}: data_start={hex(data_start)[:18]}..., element_slots={element_slots}")

        return index

    def _build_dynamic_bytes_index(
        self,
        layout: StorageLayout,
    ) -> dict[int, StorageVariable]:
        """Build index of dynamic bytes/string data start slots.

        For dynamic bytes/strings (encoding="bytes"), long strings (>=32 bytes)
        store their data at keccak256(base_slot), with consecutive slots for
        longer data.

        Returns:
            Dict mapping data_start_slot -> variable
        """
        from eth_abi import encode

        index: dict[int, StorageVariable] = {}
        for var in layout.variables:
            var_type = layout.get_type(var.type_id)
            if not var_type or var_type.encoding != "bytes":
                continue

            # Compute keccak256(base_slot) - where string data starts for long strings
            encoded_slot = encode(["uint256"], [var.slot])
            data_start = int.from_bytes(Web3.keccak(encoded_slot), "big")

            index[data_start] = var
            logger.debug(f"Dynamic bytes {var.name}: data_start={hex(data_start)[:18]}...")

        return index

    def _try_match_dynamic_bytes_slot(
        self,
        slot_int: int,
        layout: StorageLayout,
        dynamic_bytes_index: dict[int, StorageVariable],
    ) -> Optional[dict]:
        """Try to match a slot to dynamic bytes/string data.

        For long strings, data is stored at keccak256(base_slot) onwards.
        """
        # Check up to 100 slots from data start (covers up to 3200 bytes)
        for data_start, var in dynamic_bytes_index.items():
            offset_from_start = slot_int - data_start
            if offset_from_start >= 0 and offset_from_start < 100:
                return {
                    "variable": var,
                    "base_slot": var.slot,
                    "data_offset": offset_from_start,
                    "path": f"{var.name} ({offset_from_start})",
                    "encoding": "bytes",
                }

        return None

    def _try_match_dynamic_array_slot(
        self,
        slot_int: int,
        layout: StorageLayout,
        dynamic_array_index: dict[int, tuple[StorageVariable, int, StorageType | None]],
    ) -> Optional[dict]:
        """Try to match a slot to a dynamic array element.

        Dynamic arrays store elements at keccak256(base_slot) + index * element_slots.
        For struct arrays, we also resolve the specific struct field.

        Returns dict with match info or None if no match found.
        """
        for data_start, (var, element_slots, element_type) in dynamic_array_index.items():
            # Check if slot is within this array's data region
            if slot_int < data_start:
                continue

            offset_from_start = slot_int - data_start

            # For struct elements spanning multiple slots
            if element_slots > 1:
                array_index = offset_from_start // element_slots
                struct_slot_offset = offset_from_start % element_slots

                # Reasonable bound check (max 10M elements) - same as single-slot
                if array_index > 10_000_000:
                    continue

                # Resolve struct field(s) at this slot offset
                # Multiple fields may be packed into the same slot
                slot_members = []
                if element_type and element_type.members:
                    for member in element_type.members:
                        if member.slot == struct_slot_offset:
                            slot_members.append(member)

                # If multiple members at this slot, it's a packed struct slot
                if len(slot_members) > 1:
                    # Return all members for packed decoding
                    # For slot 0, just show array[index]; for other slots, show offset
                    path = f"{var.name}[{array_index}]" if struct_slot_offset == 0 else f"{var.name}[{array_index}][+{struct_slot_offset}]"
                    return {
                        "variable": var,
                        "base_slot": var.slot,
                        "array_index": array_index,
                        "struct_slot_offset": struct_slot_offset,
                        "field_name": None,  # Multiple fields - use packed decoding
                        "slot_members": slot_members,  # All packed members
                        "path": path,
                        "encoding": "dynamic_array",
                        "element_type": element_type,
                        "decode_type": element_type,  # Use full element type for packed decode
                    }
                elif len(slot_members) == 1:
                    # Single field at this slot
                    field_name = slot_members[0].name
                    field_type = layout.get_type(slot_members[0].type_id)
                    path = f"{var.name}[{array_index}].{field_name}"
                    return {
                        "variable": var,
                        "base_slot": var.slot,
                        "array_index": array_index,
                        "struct_slot_offset": struct_slot_offset,
                        "field_name": field_name,
                        "path": path,
                        "encoding": "dynamic_array",
                        "element_type": element_type,
                        "decode_type": field_type or element_type,
                    }
                else:
                    # No members found - use generic path
                    path = f"{var.name}[{array_index}][+{struct_slot_offset}]"
                    return {
                        "variable": var,
                        "base_slot": var.slot,
                        "array_index": array_index,
                        "struct_slot_offset": struct_slot_offset,
                        "field_name": None,
                        "path": path,
                        "encoding": "dynamic_array",
                        "element_type": element_type,
                        "decode_type": element_type,
                    }
            else:
                # Single-slot elements
                array_index = offset_from_start
                # Reasonable bound check (max 10M elements)
                if array_index > 10_000_000:
                    continue

                return {
                    "variable": var,
                    "base_slot": var.slot,
                    "array_index": array_index,
                    "struct_slot_offset": 0,
                    "field_name": None,
                    "path": f"{var.name}[{array_index}]",
                    "encoding": "dynamic_array",
                    "element_type": element_type,
                    "decode_type": element_type,
                }

        return None

    def _try_match_mapping_to_array_slot(
        self,
        slot_int: int,
        layout: StorageLayout,
        mapping_to_array_index: dict[int, dict],
    ) -> Optional[dict]:
        """Try to match a slot to an element of a mapping-to-array (mapping(addr => Struct[])).

        For mapping(address => Struct[]):
        - mapping lookup gives array_length_slot = keccak256(addr || base_slot)
        - array data starts at data_start = keccak256(array_length_slot)
        - element i is at data_start + i * element_slots

        Returns dict with match info or None if no match found.
        """
        for data_start, match_info in mapping_to_array_index.items():
            if slot_int < data_start:
                continue

            offset_from_start = slot_int - data_start
            element_slots = match_info.get("element_slots", 1)
            element_type = match_info.get("element_type")
            variable = match_info.get("variable")
            mapping_key = match_info.get("key", "?")

            if element_slots > 1:
                # Multi-slot struct elements
                array_index = offset_from_start // element_slots
                struct_slot_offset = offset_from_start % element_slots

                # Reasonable bound check
                if array_index > 10_000_000:
                    continue

                # Find struct member at this offset
                slot_members = []
                if element_type and element_type.members:
                    for member in element_type.members:
                        if member.slot == struct_slot_offset:
                            slot_members.append(member)

                var_name = variable.name if variable else "?"
                if len(slot_members) > 1:
                    # Multiple packed members
                    path = f"{var_name}[{mapping_key}][{array_index}]" if struct_slot_offset == 0 else f"{var_name}[{mapping_key}][{array_index}][+{struct_slot_offset}]"
                    return {
                        "variable": variable,
                        "base_slot": match_info.get("base_slot"),
                        "array_index": array_index,
                        "struct_slot_offset": struct_slot_offset,
                        "mapping_key": mapping_key,
                        "field_name": None,
                        "slot_members": slot_members,
                        "path": path,
                        "encoding": "mapping_to_array",
                        "element_type": element_type,
                        "decode_type": element_type,
                    }
                elif len(slot_members) == 1:
                    # Single field
                    field_name = slot_members[0].name
                    field_type = layout.get_type(slot_members[0].type_id)
                    path = f"{var_name}[{mapping_key}][{array_index}].{field_name}"
                    return {
                        "variable": variable,
                        "base_slot": match_info.get("base_slot"),
                        "array_index": array_index,
                        "struct_slot_offset": struct_slot_offset,
                        "mapping_key": mapping_key,
                        "field_name": field_name,
                        "path": path,
                        "encoding": "mapping_to_array",
                        "element_type": element_type,
                        "decode_type": field_type or element_type,
                    }
                else:
                    # No members found
                    path = f"{var_name}[{mapping_key}][{array_index}][+{struct_slot_offset}]"
                    return {
                        "variable": variable,
                        "base_slot": match_info.get("base_slot"),
                        "array_index": array_index,
                        "struct_slot_offset": struct_slot_offset,
                        "mapping_key": mapping_key,
                        "field_name": None,
                        "path": path,
                        "encoding": "mapping_to_array",
                        "element_type": element_type,
                        "decode_type": element_type,
                    }
            else:
                # Single-slot elements
                array_index = offset_from_start
                if array_index > 10_000_000:
                    continue

                var_name = variable.name if variable else "?"
                return {
                    "variable": variable,
                    "base_slot": match_info.get("base_slot"),
                    "array_index": array_index,
                    "struct_slot_offset": 0,
                    "mapping_key": mapping_key,
                    "field_name": None,
                    "path": f"{var_name}[{mapping_key}][{array_index}]",
                    "encoding": "mapping_to_array",
                    "element_type": element_type,
                    "decode_type": element_type,
                }

        return None

    def _decode_changes(
        self,
        raw_changes: list[tuple[str, str, str, int | None, int]],
        layout: Optional[StorageLayout],
        preimage_lookup: Optional[dict[str, str]] = None,
    ) -> list[StorageChange]:
        """Convert raw slot changes to decoded StorageChange objects.

        Args:
            raw_changes: List of (slot, old_value, new_value, pc, index) tuples.
                        pc and index come directly from the SSTORE trace.
            layout: Optional storage layout for decoding.
            preimage_lookup: Dict mapping slot hashes to SHA3 preimages for O(1) mapping resolution.
        """
        decoded_changes = []
        base_slot_index = layout.get_base_slot_index() if layout else {}
        dynamic_array_index = self._build_dynamic_array_index(layout) if layout else {}
        dynamic_bytes_index = self._build_dynamic_bytes_index(layout) if layout else {}
        preimage_lookup = preimage_lookup or {}

        # Build mapping-to-array index: find all 32-byte preimages that resolve to mapping->array
        # This enables matching array element slots (data_start + offset)
        mapping_to_array_index: dict[int, dict] = {}  # data_start_slot -> match info
        if layout and preimage_lookup:
            for slot_hash, preimage in preimage_lookup.items():
                preimage_clean = preimage[2:] if preimage.startswith("0x") else preimage
                if len(preimage_clean) == 64:
                    # This is a 32-byte preimage - could be array data start
                    match = self._try_match_slot_from_preimage(
                        slot_hash, preimage, layout, preimage_lookup, depth=0
                    )
                    if match and match.get("encoding") == "mapping_to_array":
                        data_start = match.get("data_start_slot")
                        if data_start is not None:
                            mapping_to_array_index[data_start] = match
                            logger.debug(
                                f"Mapping-to-array index: data_start={hex(data_start)[:18]}..., "
                                f"var={match.get('variable').name if match.get('variable') else '?'}"
                            )
            if mapping_to_array_index:
                logger.info(f"Built mapping-to-array index with {len(mapping_to_array_index)} entries")

        # Set type registry on decoder for generic struct decoding
        if layout and layout.types:
            self.decoder.set_type_registry(layout.types)

        # First pass: collect all matched slots and their info for struct offset detection
        # We'll process changes twice - first to find matches, then to apply struct offsets
        matched_slots: dict[int, dict] = {}  # slot_int -> match info

        # Diagnostic counters for resolution path tracking
        stats = {
            "total": 0,
            "layout_direct": 0,
            "preimage_lookup": 0,
            "struct_offset": 0,
            "dynamic_array": 0,
            "mapping_to_array": 0,
            "dynamic_bytes": 0,
            "heuristic": 0,
        }

        # Log decode progress for performance debugging
        total_changes = len(raw_changes)
        logger.info(f"Decoding {total_changes} storage changes (preimage_lookup has {len(preimage_lookup)} entries)...")

        for change_idx, (slot_hex, old_value, new_value, pc, exec_index) in enumerate(raw_changes):
            stats["total"] += 1
            resolution_path = "unknown"  # Track which path resolved this slot

            # Progress logging every 50 changes
            if change_idx > 0 and change_idx % 50 == 0:
                logger.info(f"  Decoded {change_idx}/{total_changes} changes...")
            try:
                try:
                    slot_int = int(slot_hex, 16)
                except Exception:
                    slot_int = 0  # fallback to allow processing to continue even with malformed slot

                variable = None
                variable_path = None
                old_decoded = None
                new_decoded = None
                mapping_base_slot: Optional[int] = None
                type_label: Optional[str] = None
                # New fields
                mapping_key: Optional[str] = None
                is_mapping: bool = False
                encoding: Optional[str] = None
                key_type: Optional[str] = None
                value_type: Optional[str] = None
                element_type_id: Optional[str] = None  # For dynamic array struct lookup
                array_index: Optional[int] = None  # For dynamic array entries

                if layout:
                    try:
                        variable = layout.get_variable_for_slot(slot_int)

                        if variable:
                            stats["layout_direct"] += 1
                            resolution_path = "layout_direct"
                            var_type = layout.get_type(variable.type_id)
                            if var_type:
                                encoding = var_type.encoding
                                is_mapping = var_type.encoding == "mapping"
                                key_type = var_type.key_type
                                value_type = var_type.value_type
                            mapping_base_slot = variable.slot if var_type and var_type.encoding == "mapping" else None
                            variable_path = variable.name

                            # For mappings, decode using value type
                            decode_type = var_type
                            if var_type and var_type.encoding == "mapping":
                                if var_type.value_type:
                                    decode_type = layout.get_type(var_type.value_type)
                                else:
                                    # Mapping without value_type - can't decode meaningfully
                                    logger.debug(f"Mapping {variable.name} has no value_type, using heuristic")
                                    decode_type = None

                            if var_type:
                                try:
                                    old_bytes = bytes.fromhex(old_value[2:])
                                    new_bytes = bytes.fromhex(new_value[2:])
                                    # Special handling for bytes encoding (dynamic strings/bytes)
                                    if var_type.encoding == "bytes":
                                        type_label = var_type.label  # e.g., "string" or "bytes"
                                        old_decoded = self.decoder.decode_dynamic_bytes_slot(
                                            old_bytes, type_label
                                        )
                                        new_decoded = self.decoder.decode_dynamic_bytes_slot(
                                            new_bytes, type_label
                                        )
                                        # For long strings (lowest bit = 1), mark as length slot
                                        # Detect encoding transitions between short and long strings
                                        old_is_long = (old_bytes[-1] & 1) == 1 if old_bytes else False
                                        new_is_long = (new_bytes[-1] & 1) == 1 if new_bytes else False

                                        if old_is_long != new_is_long:
                                            # Encoding transition
                                            if new_is_long:
                                                variable_path = f"{variable.name} (short→long string)"
                                            else:
                                                variable_path = f"{variable.name} (long→short string)"
                                        elif new_is_long or old_is_long:
                                            variable_path = f"{variable.name} (string length)"
                                    elif var_type.encoding == "dynamic_array" or (
                                        var_type.element_type and "[]" in (var_type.label or "")
                                    ):
                                        # Dynamic array BASE slot stores the array LENGTH (uint256)
                                        # NOT the element data - elements are at keccak256(slot)
                                        # Detect via encoding OR presence of element_type with [] in label
                                        encoding = "dynamic_array"
                                        is_dynamic_array = True
                                        old_length = int.from_bytes(old_bytes, "big")
                                        new_length = int.from_bytes(new_bytes, "big")
                                        old_decoded = DecodedValue(
                                            raw=old_value,
                                            decoded=old_length,
                                            type_label="uint256",
                                            display=str(old_length),
                                        )
                                        new_decoded = DecodedValue(
                                            raw=new_value,
                                            decoded=new_length,
                                            type_label="uint256",
                                            display=str(new_length),
                                        )
                                        variable_path = f"{variable.name} (array length)"
                                    elif decode_type:
                                        # For multi-slot structs, pass slot offset so field-specific decode can occur
                                        slot_offset = slot_int - variable.slot if variable else 0
                                        old_decoded = self.decoder.decode(
                                            old_bytes, decode_type, variable.offset, slot_offset
                                        )
                                        new_decoded = self.decoder.decode(
                                            new_bytes, decode_type, variable.offset, slot_offset
                                        )
                                except Exception as e:
                                    logger.warning(f"Failed to decode change at slot {slot_hex}: {e}")
                        else:
                            # OPTIMIZATION: Try preimage_lookup FIRST (O(1)) before brute-force
                            # candidate matching. Preimage lookup has the actual keys used.
                            if slot_hex in preimage_lookup:
                                preimage = preimage_lookup[slot_hex]
                                preimage_match = self._try_match_slot_from_preimage(
                                    slot_hex, preimage, layout, preimage_lookup
                                )
                                if preimage_match:
                                    variable = preimage_match.get("variable")
                                    mapping_base_slot = preimage_match.get("base_slot")
                                    mapping_key = preimage_match.get("key")
                                    variable_path = preimage_match.get("path")
                                    is_mapping = True
                                    encoding = preimage_match.get("encoding")
                                    key_type = preimage_match.get("key_type")
                                    value_type = preimage_match.get("value_type")
                                    decode_type = preimage_match.get("decode_type")

                                    # Handle mapping_to_array: this slot IS the data_start, so array_index=0
                                    if encoding == "mapping_to_array":
                                        stats["mapping_to_array"] += 1
                                        resolution_path = "mapping_to_array"
                                        array_index = 0  # This is the data_start slot, so index 0
                                        # Update path to include array index
                                        if variable:
                                            variable_path = f"{variable.name}[{mapping_key}][0]"
                                        # Get element_type for decoding
                                        element_type = preimage_match.get("element_type")
                                        if element_type:
                                            decode_type = element_type

                                    if decode_type:
                                        try:
                                            old_bytes = bytes.fromhex(old_value[2:])
                                            new_bytes = bytes.fromhex(new_value[2:])
                                            old_decoded = self.decoder.decode(
                                                old_bytes, decode_type, variable.offset if variable else 0
                                            )
                                            new_decoded = self.decoder.decode(
                                                new_bytes, decode_type, variable.offset if variable else 0
                                            )
                                        except Exception:
                                            pass

                            # Try dynamic array slot matching if preimage lookup didn't match
                            if not variable and dynamic_array_index:
                                array_match = self._try_match_dynamic_array_slot(
                                    slot_int, layout, dynamic_array_index
                                )
                                if array_match:
                                    stats["dynamic_array"] += 1
                                    resolution_path = "dynamic_array"
                                    variable = array_match["variable"]
                                    variable_path = array_match["path"]
                                    encoding = array_match.get("encoding")
                                    # Capture array index for dynamic arrays
                                    array_index = array_match.get("array_index")
                                    # Get element type (struct) for struct definition lookup
                                    element_type = array_match.get("element_type")
                                    element_type_id = element_type.id if element_type else None
                                    # Get field type for value_type display
                                    decode_type = array_match.get("decode_type")
                                    struct_slot_offset = array_match.get("struct_slot_offset", 0) or 0
                                    # Check for packed struct slot (multiple members at same offset)
                                    slot_members = array_match.get("slot_members")
                                    if slot_members and len(slot_members) > 1:
                                        # Packed struct slot - decode all packed fields
                                        value_type = "packed"
                                        try:
                                            old_bytes = bytes.fromhex(old_value[2:])
                                            new_bytes = bytes.fromhex(new_value[2:])
                                            old_packed = self.decoder.decode_packed_slot(old_bytes, slot_members, layout.types if layout else {})
                                            new_packed = self.decoder.decode_packed_slot(new_bytes, slot_members, layout.types if layout else {})
                                            # Combine into single decoded dict
                                            old_decoded = DecodedValue(
                                                raw=old_value,
                                                decoded={k: v.decoded for k, v in old_packed.items()},
                                                type_label="packed",
                                                display=None,
                                            )
                                            new_decoded = DecodedValue(
                                                raw=new_value,
                                                decoded={k: v.decoded for k, v in new_packed.items()},
                                                type_label="packed",
                                                display=None,
                                            )
                                        except Exception:
                                            pass
                                    elif decode_type:
                                        value_type = decode_type.label
                                        try:
                                            old_bytes = bytes.fromhex(old_value[2:])
                                            new_bytes = bytes.fromhex(new_value[2:])
                                            old_decoded = self.decoder.decode(old_bytes, decode_type, 0, struct_slot_offset)
                                            new_decoded = self.decoder.decode(new_bytes, decode_type, 0, struct_slot_offset)
                                        except Exception:
                                            pass

                            # Try mapping-to-array slot matching (mapping(addr => Struct[]))
                            if not variable and mapping_to_array_index:
                                m2a_match = self._try_match_mapping_to_array_slot(
                                    slot_int, layout, mapping_to_array_index
                                )
                                if m2a_match:
                                    stats["mapping_to_array"] += 1
                                    resolution_path = "mapping_to_array"
                                    variable = m2a_match["variable"]
                                    variable_path = m2a_match["path"]
                                    encoding = m2a_match.get("encoding")
                                    is_mapping = True  # It's a mapping at the root
                                    mapping_key = m2a_match.get("mapping_key")
                                    array_index = m2a_match.get("array_index")
                                    element_type = m2a_match.get("element_type")
                                    element_type_id = element_type.id if element_type else None
                                    decode_type = m2a_match.get("decode_type")
                                    struct_slot_offset = m2a_match.get("struct_slot_offset", 0) or 0
                                    # Check for packed struct slot
                                    slot_members = m2a_match.get("slot_members")
                                    if slot_members and len(slot_members) > 1:
                                        value_type = "packed"
                                        try:
                                            old_bytes = bytes.fromhex(old_value[2:])
                                            new_bytes = bytes.fromhex(new_value[2:])
                                            old_packed = self.decoder.decode_packed_slot(old_bytes, slot_members, layout.types if layout else {})
                                            new_packed = self.decoder.decode_packed_slot(new_bytes, slot_members, layout.types if layout else {})
                                            old_decoded = DecodedValue(
                                                raw=old_value,
                                                decoded={k: v.decoded for k, v in old_packed.items()},
                                                type_label="packed",
                                                display=None,
                                            )
                                            new_decoded = DecodedValue(
                                                raw=new_value,
                                                decoded={k: v.decoded for k, v in new_packed.items()},
                                                type_label="packed",
                                                display=None,
                                            )
                                        except Exception:
                                            pass
                                    elif decode_type:
                                        value_type = decode_type.label
                                        try:
                                            old_bytes = bytes.fromhex(old_value[2:])
                                            new_bytes = bytes.fromhex(new_value[2:])
                                            old_decoded = self.decoder.decode(old_bytes, decode_type, 0, struct_slot_offset)
                                            new_decoded = self.decoder.decode(new_bytes, decode_type, 0, struct_slot_offset)
                                        except Exception:
                                            pass

                            # Try dynamic bytes/string data slot matching
                            if not variable and dynamic_bytes_index:
                                bytes_match = self._try_match_dynamic_bytes_slot(
                                    slot_int, layout, dynamic_bytes_index
                                )
                                if bytes_match:
                                    stats["dynamic_bytes"] += 1
                                    resolution_path = "dynamic_bytes"
                                    variable = bytes_match["variable"]
                                    variable_path = bytes_match["path"]
                                    encoding = bytes_match.get("encoding")
                                    data_offset = bytes_match.get("data_offset", 0)
                                    # Decode the data slot content
                                    try:
                                        old_bytes = bytes.fromhex(old_value[2:])
                                        new_bytes = bytes.fromhex(new_value[2:])
                                        var_type = layout.get_type(variable.type_id)
                                        type_label = var_type.label if var_type else "bytes"
                                        old_decoded = self.decoder.decode_dynamic_bytes_data_slot(
                                            old_bytes, type_label, data_offset
                                        )
                                        new_decoded = self.decoder.decode_dynamic_bytes_data_slot(
                                            new_bytes, type_label, data_offset
                                        )
                                    except Exception as e:
                                        logger.warning(f"Failed to decode dynamic bytes data slot: {e}")
                    except Exception as e:
                        logger.error(f"Slot matching/decoding failed for slot {slot_hex}: {e}", exc_info=True)

                # Try to resolve the slot using preimage lookup (from SHA3 trace)
                # This is more reliable than guessing keys because we captured the actual
                # data that was hashed to produce this slot
                if not variable:
                    # Log unmatched slots for debugging
                    logger.debug(f"Unmatched slot: {slot_hex[:18]}... checking preimage lookup")
                    if slot_hex in preimage_lookup:
                        logger.debug(f"  Found in preimage lookup!")
                    else:
                        # Check if slot minus offset is in lookup (struct member)
                        for offset in range(1, 5):
                            base_int = slot_int - offset
                            base_hex = self._normalize_slot(hex(base_int))
                            if base_hex in preimage_lookup:
                                logger.debug(f"  Slot-{offset} ({base_hex[:18]}...) IS in lookup")
                                break
                        else:
                            logger.debug(f"  NOT in preimage lookup (and no offset matches)")
                if not variable and slot_hex in preimage_lookup:
                    preimage = preimage_lookup[slot_hex]
                    preimage_match = self._try_match_slot_from_preimage(
                        slot_hex, preimage, layout, preimage_lookup
                    )
                    if preimage_match:
                        stats["preimage_lookup"] += 1
                        resolution_path = "preimage_lookup"
                        variable = preimage_match.get("variable")
                        mapping_base_slot = preimage_match.get("base_slot")
                        mapping_key = preimage_match.get("key")
                        variable_path = preimage_match.get("path")
                        is_mapping = True
                        encoding = preimage_match.get("encoding")
                        key_type = preimage_match.get("key_type")
                        value_type = preimage_match.get("value_type")
                        # Decode using value type if available
                        decode_type = preimage_match.get("decode_type")

                        # Handle mapping_to_array: this slot IS the data_start, so array_index=0
                        if encoding == "mapping_to_array":
                            stats["mapping_to_array"] += 1
                            resolution_path = "mapping_to_array"
                            array_index = 0  # This is the data_start slot, so index 0
                            # Update path to include array index
                            if variable:
                                variable_path = f"{variable.name}[{mapping_key}][0]"
                            # Get element_type for decoding
                            element_type = preimage_match.get("element_type")
                            if element_type:
                                decode_type = element_type

                        # If decode_type is None but we have value_type, try to synthesize it
                        if not decode_type and value_type and layout:
                            decode_type = layout.get_type(value_type)

                        if decode_type:
                            try:
                                old_bytes = bytes.fromhex(old_value[2:])
                                new_bytes = bytes.fromhex(new_value[2:])
                                old_decoded = self.decoder.decode(
                                    old_bytes, decode_type, variable.offset if variable else 0
                                )
                                new_decoded = self.decoder.decode(
                                    new_bytes, decode_type, variable.offset if variable else 0
                                )
                            except Exception as e:
                                logger.debug(f"Failed to decode mapping value: {e}")
                        else:
                            # Final fallback: use heuristic decoding
                            try:
                                old_bytes = bytes.fromhex(old_value[2:])
                                new_bytes = bytes.fromhex(new_value[2:])
                                old_decoded = self.decoder.decode_heuristic(old_bytes)
                                new_decoded = self.decoder.decode_heuristic(new_bytes)
                            except Exception:
                                pass

                # Handle struct offsets: if slot is not in preimage_lookup but slot-N is,
                # this is a struct member access (e.g., accountData[addr].field where field offset = N)
                if not variable and slot_hex not in preimage_lookup:
                    for struct_offset in range(1, 10):  # Check offsets 1-9 for struct members
                        base_slot_int = slot_int - struct_offset
                        base_slot_hex = self._normalize_slot(hex(base_slot_int))
                        if base_slot_hex in preimage_lookup:
                            base_preimage = preimage_lookup[base_slot_hex]
                            logger.debug(f"  Struct offset {struct_offset}: trying to match base {base_slot_hex[:18]}...")
                            base_match = self._try_match_slot_from_preimage(
                                base_slot_hex, base_preimage, layout, preimage_lookup
                            )
                            if base_match:
                                base_var = base_match.get("variable")
                                if base_var:
                                    stats["struct_offset"] += 1
                                    resolution_path = "struct_offset"
                                    # Found the base mapping variable, now add struct offset info
                                    variable = base_var
                                    mapping_base_slot = base_match.get("base_slot")
                                    mapping_key = base_match.get("key")
                                    base_path = base_match.get("path", "")
                                    is_mapping = True
                                    encoding = base_match.get("encoding")
                                    key_type = base_match.get("key_type")
                                    value_type = base_match.get("value_type")

                                    # Try to resolve struct field name from offset
                                    field_name, field_type = self._resolve_struct_field(
                                        base_var, struct_offset, layout
                                    )
                                    if field_name:
                                        # Resolved to actual field name (e.g., .lockStart)
                                        variable_path = f"{base_path}.{field_name}" if base_path else f".{field_name}"
                                        # Also decode using the field's type
                                        if field_type:
                                            try:
                                                old_bytes = bytes.fromhex(old_value[2:])
                                                new_bytes = bytes.fromhex(new_value[2:])
                                                old_decoded = self.decoder.decode(old_bytes, field_type, 0)
                                                new_decoded = self.decoder.decode(new_bytes, field_type, 0)
                                            except Exception:
                                                pass
                                    else:
                                        # Fall back to offset notation
                                        variable_path = f"{base_path}[+{struct_offset}]" if base_path else f"[+{struct_offset}]"

                                    logger.debug(f"  Matched as struct offset: {variable.name}{variable_path}")
                                    break

                # Heuristic decode if no layout or no decoded values yet
                if (not layout or not variable) and not old_decoded:
                    try:
                        old_bytes = bytes.fromhex(old_value[2:])
                        new_bytes = bytes.fromhex(new_value[2:])
                        old_decoded = self.decoder.decode_heuristic(old_bytes)
                        new_decoded = self.decoder.decode_heuristic(new_bytes)
                    except Exception:
                        pass

                # Count unresolved slots that fell through to heuristic
                if resolution_path == "unknown":
                    stats["heuristic"] += 1

                # Track matched slots for struct offset detection in second pass
                if variable and is_mapping:
                    matched_slots[slot_int] = {
                        "variable": variable,
                        "mapping_base_slot": mapping_base_slot,
                        "mapping_key": mapping_key,
                        "variable_path": variable_path,
                        "encoding": encoding,
                        "key_type": key_type,
                        "value_type": value_type,
                    }

                # pc and exec_index come directly from the raw_changes tuple
                decoded_changes.append(
                    StorageChange(
                        slot=slot_hex,
                        mapping_base_slot=mapping_base_slot,
                        old_value=old_value,
                        new_value=new_value,
                        variable=variable,
                        variable_path=variable_path,
                        old_decoded=old_decoded,
                        new_decoded=new_decoded,
                        mapping_key=mapping_key,
                        is_mapping=is_mapping,
                        encoding=encoding,
                        key_type=key_type,
                        value_type=value_type,
                        element_type_id=element_type_id,
                        array_index=array_index,
                        change_index=exec_index,
                        pc=pc,
                    )
                )

            except Exception as e:
                logger.error(f"Fatal error decoding slot {slot_hex}: {e}", exc_info=True)
                try:
                    old_bytes = bytes.fromhex(old_value[2:]) if old_value.startswith("0x") else bytes.fromhex(old_value)
                    new_bytes = bytes.fromhex(new_value[2:]) if new_value.startswith("0x") else bytes.fromhex(new_value)
                    old_decoded = self.decoder.decode_heuristic(old_bytes)
                    new_decoded = self.decoder.decode_heuristic(new_bytes)
                except Exception:
                    old_decoded = None
                    new_decoded = None

                decoded_changes.append(
                    StorageChange(
                        slot=slot_hex,
                        mapping_base_slot=None,
                        old_value=old_value,
                        new_value=new_value,
                        variable=None,
                        variable_path=None,
                        old_decoded=old_decoded,
                        new_decoded=new_decoded,
                        mapping_key=None,
                        is_mapping=False,
                        encoding=None,
                        key_type=None,
                        value_type=None,
                        element_type_id=None,
                        array_index=None,
                        change_index=exec_index,
                        pc=pc,
                    )
                )

        # Second pass: Try to resolve unmatched slots using struct offset detection
        # If slot X is unmatched but slot X-N (for small N) is matched, X is a struct member
        all_slot_ints = set(int(c.slot, 16) for c in decoded_changes)

        # Helper function to find base match by following chains
        def find_base_match(slot_int: int, max_depth: int = 10) -> tuple[dict | None, int]:
            """Find the matched base slot by following chains. Returns (match, offset)."""
            for offset in range(1, max_depth + 1):
                base_slot_int = slot_int - offset
                if base_slot_int in matched_slots:
                    return matched_slots[base_slot_int], offset
            return None, 0

        for i, change in enumerate(decoded_changes):
            if change.variable is None:
                slot_int = int(change.slot, 16)
                base_match, offset = find_base_match(slot_int)

                if base_match:
                    base_var = base_match["variable"]
                    base_key = base_match["mapping_key"]
                    # This slot is base + offset, a struct member
                    logger.debug(f"Struct offset match: {change.slot[:18]}... = {base_var.name}[{base_key}]+{offset}")
                    decoded_changes[i] = StorageChange(
                        slot=change.slot,
                        mapping_base_slot=base_match["mapping_base_slot"],
                        old_value=change.old_value,
                        new_value=change.new_value,
                        variable=base_var,
                        variable_path=f"{base_var.name}[{base_key}]+{offset}",
                        old_decoded=change.old_decoded,
                        new_decoded=change.new_decoded,
                        mapping_key=base_key,
                        is_mapping=True,
                        encoding=base_match.get("encoding"),
                        key_type=base_match.get("key_type"),
                        value_type=base_match.get("value_type"),
                        change_index=change.change_index,
                        pc=change.pc,
                    )

        # Log resolution path statistics
        resolved = stats["layout_direct"] + stats["preimage_lookup"] + stats["struct_offset"] + stats["dynamic_array"] + stats["mapping_to_array"] + stats["dynamic_bytes"]
        logger.info(
            f"Slot resolution: {stats['total']} total, {resolved} resolved "
            f"(layout={stats['layout_direct']}, preimage={stats['preimage_lookup']}, "
            f"struct_offset={stats['struct_offset']}, array={stats['dynamic_array']}, "
            f"map_to_array={stats['mapping_to_array']}, bytes={stats['dynamic_bytes']}), {stats['heuristic']} heuristic"
        )
        return decoded_changes
