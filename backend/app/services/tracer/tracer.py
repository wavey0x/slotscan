"""Transaction tracer for extracting storage changes from transactions."""

import asyncio
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
from app.models.errors import TraceNotAvailableError
from app.repositories.cache import CacheRepository
from app.repositories.trace_cache import TraceCacheRepository, CachedTraceData
from app.services.decoder import TypeDecoder
from app.services.web3_provider import Web3Provider
from app.services.tracer.rpc_client import TraceRPCClient
from app.services.tracer.preimage_resolver import PreimageResolver
from app.services.tracer.slot_resolver import SlotResolver

logger = logging.getLogger(__name__)


class TransactionTracer:
    """Traces transactions to extract storage changes."""

    def __init__(
        self,
        web3_provider: Web3Provider,
        settings: Settings,
        decoder: TypeDecoder,
        cache_repo: Optional[CacheRepository] = None,
        trace_cache_repo: Optional[TraceCacheRepository] = None,
    ):
        self.web3_provider = web3_provider
        self.settings = settings
        self.decoder = decoder
        self.cache_repo = cache_repo
        self.trace_cache_repo = trace_cache_repo

        # Composed services
        self.rpc_client = TraceRPCClient(web3_provider)
        self.preimage_resolver = PreimageResolver()
        self.slot_resolver = SlotResolver()

    async def trace_transaction(
        self,
        chain_id: int,
        contract_address: str,
        tx_hash: str,
        layout: Optional[StorageLayout] = None,
        sources: Optional[dict[str, str]] = None,
    ) -> TransactionDiff:
        """
        Trace a transaction and extract storage changes for a contract.

        Uses debug_traceTransaction with prestateTracer.
        Caches raw trace data (after RPC, before decoding) for fast repeated access.
        """
        contract_address = Web3.to_checksum_address(contract_address)

        # Check trace cache first
        cached_trace = None
        if self.trace_cache_repo:
            cached_trace = await self.trace_cache_repo.get(chain_id, tx_hash, contract_address)

        if cached_trace:
            logger.info(f"Trace cache HIT for {tx_hash[:10]}... - skipping RPC calls")

            raw_changes = cached_trace.raw_changes
            preimage_lookup = cached_trace.preimage_lookup
            block_number = cached_trace.block_number
            execution_order_available = True

            is_complete = len(raw_changes) <= self.settings.max_sstore_ops
            if not is_complete:
                raw_changes = raw_changes[: self.settings.max_sstore_ops]

            decoded_changes = self._decode_changes(raw_changes, layout, preimage_lookup)

            return TransactionDiff(
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

        logger.info(f"Trace cache MISS for {tx_hash[:10]}... - executing RPC calls")

        try:
            trace_result, receipt = await asyncio.gather(
                self.rpc_client.execute_prestate_trace(chain_id, tx_hash),
                self.rpc_client.get_receipt(chain_id, tx_hash),
            )
        except TraceNotAvailableError:
            receipt = await self.rpc_client.get_receipt(chain_id, tx_hash)
            return TransactionDiff(
                chain_id=chain_id,
                contract_address=contract_address,
                tx_hash=tx_hash,
                block_number=receipt["blockNumber"],
                changes=[],
                is_complete=False,
                layout=layout,
                trace_unavailable=True,
            )

        block_number = receipt["blockNumber"]
        prestate_changes = self._extract_contract_changes(trace_result, contract_address)

        tx_to_address = receipt.get("to")
        if not tx_to_address:
            tx_to_address = receipt.get("contractAddress")
            if tx_to_address:
                logger.info(f"Contract creation transaction - using created address: {tx_to_address}")

        sstore_trace, sha3_trace = await self.rpc_client.execute_structlogs_trace(
            chain_id, tx_hash, tx_to_address
        )

        preimage_lookup = self.preimage_resolver.build_preimage_lookup(sha3_trace)

        if sources and layout:
            constant_lookup = self.preimage_resolver.build_constant_preimage_lookup(sources, layout)
            if constant_lookup:
                for slot_hash, preimage in constant_lookup.items():
                    if slot_hash not in preimage_lookup:
                        preimage_lookup[slot_hash] = preimage

        execution_order_available = False
        trace_step_count = 0
        if sstore_trace:
            raw_changes, had_unknown_sstores = self._build_changes_from_sstore_trace(
                sstore_trace, trace_result, contract_address
            )
            execution_order_available = True
            trace_step_count = len(sstore_trace) + len(sha3_trace)
        else:
            raw_changes = [
                (self._normalize_slot(slot), old, new, None, None)
                for i, (slot, old, new) in enumerate(prestate_changes)
            ]
            execution_order_available = False

        if self.trace_cache_repo:
            try:
                await self.trace_cache_repo.save(CachedTraceData(
                    chain_id=chain_id,
                    tx_hash=tx_hash,
                    contract_address=contract_address,
                    block_number=block_number,
                    raw_changes=raw_changes,
                    preimage_lookup=preimage_lookup,
                    trace_step_count=trace_step_count,
                ))
            except Exception as e:
                logger.warning(f"Failed to save trace to cache: {e}")

        is_complete = len(raw_changes) <= self.settings.max_sstore_ops
        if not is_complete:
            raw_changes = raw_changes[: self.settings.max_sstore_ops]

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

        if self.cache_repo:
            await self.cache_repo.save_tx_diff(diff)

        return diff

    async def get_transaction_block(self, chain_id: int, tx_hash: str) -> int:
        """Get the block number a transaction was included in."""
        receipt = await self.rpc_client.get_receipt(chain_id, tx_hash)
        return receipt["blockNumber"]

    def _build_changes_from_sstore_trace(
        self,
        sstore_trace: list[dict],
        pre_state: dict,
        contract_address: str,
    ) -> tuple[list[tuple[str, str, str, int | None, int]], bool]:
        """Build list of (slot, old_value, new_value, pc, index) from SSTORE trace."""
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

        slot_current_value: dict[str, str] = dict(pre_storage)
        changes: list[tuple[str, str, str, int | None, int]] = []
        had_unknown_address = False

        for op in sorted(sstore_trace, key=lambda x: x.get("index", 0)):
            op_addr = (op.get("address") or "").lower()
            slot = self._normalize_slot(op.get("slot", "0x0"))

            address_matches = op_addr == contract_address_lower
            addr_unknown = not op_addr

            if addr_unknown:
                had_unknown_address = True

            should_accept = address_matches

            if not should_accept:
                continue

            new_value = self._normalize_value(op.get("value", zero_value))
            pc = op.get("pc")
            index = op.get("index", 0)

            old_value = slot_current_value.get(slot, zero_value)

            if old_value != new_value:
                changes.append((slot, old_value, new_value, pc, index))

            slot_current_value[slot] = new_value

        return changes, had_unknown_address

    def _extract_contract_changes(
        self, trace_result: dict, contract_address: str
    ) -> list[tuple[str, str, str]]:
        """Extract storage changes for a specific contract from trace."""
        contract_address_lower = contract_address.lower()
        changes = []

        pre_state = trace_result.get("pre", {})
        post_state = trace_result.get("post", {})

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

        all_slots = set(pre_storage.keys()) | set(post_storage.keys())
        zero_value = "0x" + "0" * 64

        for slot in all_slots:
            normalized_slot = self._normalize_slot(slot)
            old_val = pre_storage.get(slot, zero_value)
            new_val = post_storage.get(slot, zero_value)

            old_val = self._normalize_value(old_val)
            new_val = self._normalize_value(new_val)

            if old_val != new_val:
                changes.append((normalized_slot, old_val, new_val))

        return changes

    def _normalize_slot(self, slot: str) -> str:
        """Normalize a slot to 0x-prefixed, 64-char hex."""
        if isinstance(slot, int):
            return f"0x{slot:064x}"
        if not slot.startswith("0x"):
            slot = "0x" + slot
        hex_part = slot[2:]
        padded = hex_part.zfill(64)
        return "0x" + padded.lower()

    def _normalize_value(self, value: str) -> str:
        """Normalize a storage value to full 32-byte hex."""
        if isinstance(value, int):
            return f"0x{value:064x}"
        if not value.startswith("0x"):
            value = "0x" + value
        hex_part = value[2:]
        padded = hex_part.zfill(64)
        return "0x" + padded.lower()

    def _decode_changes(
        self,
        raw_changes: list[tuple[str, str, str, int | None, int]],
        layout: Optional[StorageLayout],
        preimage_lookup: Optional[dict[str, str]] = None,
    ) -> list[StorageChange]:
        """Convert raw slot changes to decoded StorageChange objects."""
        decoded_changes = []
        base_slot_index = layout.get_base_slot_index() if layout else {}
        dynamic_array_index = self.slot_resolver.build_dynamic_array_index(layout) if layout else {}
        dynamic_bytes_index = self.slot_resolver.build_dynamic_bytes_index(layout) if layout else {}
        static_array_index = self.slot_resolver.build_static_array_index(layout) if layout else {}
        preimage_lookup = preimage_lookup or {}

        # Build mapping-to-array index
        mapping_to_array_index: dict[int, dict] = {}
        if layout and preimage_lookup:
            for slot_hash, preimage in preimage_lookup.items():
                preimage_clean = preimage[2:] if preimage.startswith("0x") else preimage
                if len(preimage_clean) == 64:
                    match = self.slot_resolver.try_match_slot_from_preimage(
                        slot_hash, preimage, layout, preimage_lookup, depth=0
                    )
                    if match and match.get("encoding") == "mapping_to_array":
                        data_start = match.get("data_start_slot")
                        if data_start is not None:
                            mapping_to_array_index[data_start] = match
            if mapping_to_array_index:
                logger.info(f"Built mapping-to-array index with {len(mapping_to_array_index)} entries")

        if layout and layout.types:
            self.decoder.set_type_registry(layout.types)

        matched_slots: dict[int, dict] = {}

        stats = {
            "total": 0,
            "layout_direct": 0,
            "static_array": 0,
            "preimage_lookup": 0,
            "struct_offset": 0,
            "dynamic_array": 0,
            "mapping_to_array": 0,
            "dynamic_bytes": 0,
            "heuristic": 0,
        }

        total_changes = len(raw_changes)
        logger.info(f"Decoding {total_changes} storage changes (preimage_lookup has {len(preimage_lookup)} entries)...")

        for change_idx, (slot_hex, old_value, new_value, pc, exec_index) in enumerate(raw_changes):
            stats["total"] += 1
            resolution_path = "unknown"

            if change_idx > 0 and change_idx % 50 == 0:
                logger.info(f"  Decoded {change_idx}/{total_changes} changes...")

            try:
                try:
                    slot_int = int(slot_hex, 16)
                except Exception:
                    slot_int = 0

                variable = None
                variable_path = None
                old_decoded = None
                new_decoded = None
                mapping_base_slot: Optional[int] = None
                type_label: Optional[str] = None
                mapping_key: Optional[str] = None
                is_mapping: bool = False
                encoding: Optional[str] = None
                key_type: Optional[str] = None
                value_type: Optional[str] = None
                element_type_id: Optional[str] = None
                array_index: Optional[int] = None

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

                            if var_type and var_type.encoding == "inplace" and var_type.array_length:
                                static_arr_index = layout.get_static_array_index(variable, slot_int)
                                if static_arr_index is not None:
                                    stats["static_array"] += 1
                                    resolution_path = "static_array"
                                    variable_path = f"{variable.name}[{static_arr_index}]"
                                    array_index = static_arr_index
                                    if var_type.element_type:
                                        value_type = var_type.element_type

                            decode_type = var_type
                            if var_type and var_type.encoding == "mapping":
                                if var_type.value_type:
                                    decode_type = layout.get_type(var_type.value_type)
                                else:
                                    decode_type = None

                            if var_type:
                                try:
                                    old_bytes = bytes.fromhex(old_value[2:])
                                    new_bytes = bytes.fromhex(new_value[2:])
                                    if var_type.encoding == "bytes":
                                        type_label = var_type.label
                                        old_decoded = self.decoder.decode_dynamic_bytes_slot(old_bytes, type_label)
                                        new_decoded = self.decoder.decode_dynamic_bytes_slot(new_bytes, type_label)
                                        old_is_long = (old_bytes[-1] & 1) == 1 if old_bytes else False
                                        new_is_long = (new_bytes[-1] & 1) == 1 if new_bytes else False
                                        if old_is_long or new_is_long or old_is_long != new_is_long:
                                            variable_path = f"{variable.name} (length)"
                                            value_type = "uint256"
                                            def extract_string_length(raw_bytes: bytes, is_long: bool) -> int:
                                                if not raw_bytes or raw_bytes == bytes(32):
                                                    return 0
                                                if is_long:
                                                    full_value = int.from_bytes(raw_bytes, "big")
                                                    return (full_value - 1) // 2
                                                else:
                                                    return raw_bytes[-1] // 2
                                            old_length = extract_string_length(old_bytes, old_is_long)
                                            new_length = extract_string_length(new_bytes, new_is_long)
                                            old_decoded = DecodedValue(raw=old_value, decoded=old_length, type_label="uint256")
                                            new_decoded = DecodedValue(raw=new_value, decoded=new_length, type_label="uint256")
                                    elif var_type.encoding == "dynamic_array" or (var_type.element_type and "[]" in (var_type.label or "")):
                                        encoding = "dynamic_array"
                                        old_length = int.from_bytes(old_bytes, "big")
                                        new_length = int.from_bytes(new_bytes, "big")
                                        old_decoded = DecodedValue(raw=old_value, decoded=old_length, type_label="uint256")
                                        new_decoded = DecodedValue(raw=new_value, decoded=new_length, type_label="uint256")
                                        variable_path = f"{variable.name} (array length)"
                                    elif decode_type:
                                        slot_offset = slot_int - variable.slot if variable else 0
                                        old_decoded = self.decoder.decode(old_bytes, decode_type, variable.offset, slot_offset)
                                        new_decoded = self.decoder.decode(new_bytes, decode_type, variable.offset, slot_offset)
                                except Exception as e:
                                    logger.warning(f"Failed to decode change at slot {slot_hex}: {e}")
                        else:
                            # Try preimage lookup
                            if slot_hex in preimage_lookup:
                                preimage = preimage_lookup[slot_hex]
                                preimage_match = self.slot_resolver.try_match_slot_from_preimage(
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
                                    decode_type = preimage_match.get("decode_type")

                                    if encoding == "mapping_to_array":
                                        stats["mapping_to_array"] += 1
                                        resolution_path = "mapping_to_array"
                                        array_index = 0
                                        if variable:
                                            variable_path = f"{variable.name}[{mapping_key}][0]"
                                        element_type = preimage_match.get("element_type")
                                        if element_type:
                                            decode_type = element_type

                                    if decode_type:
                                        try:
                                            old_bytes = bytes.fromhex(old_value[2:])
                                            new_bytes = bytes.fromhex(new_value[2:])
                                            old_decoded = self.decoder.decode(old_bytes, decode_type, variable.offset if variable else 0)
                                            new_decoded = self.decoder.decode(new_bytes, decode_type, variable.offset if variable else 0)
                                        except Exception:
                                            pass

                            # Try static array
                            if not variable and static_array_index:
                                static_match = self.slot_resolver.try_match_static_array_slot(slot_int, layout, static_array_index)
                                if static_match:
                                    stats["static_array"] += 1
                                    resolution_path = "static_array"
                                    variable = static_match["variable"]
                                    variable_path = static_match["path"]
                                    encoding = static_match.get("encoding")
                                    array_index = static_match.get("array_index")
                                    element_type = static_match.get("element_type")
                                    if element_type:
                                        value_type = element_type.label if hasattr(element_type, 'label') else str(element_type)
                                        try:
                                            old_bytes = bytes.fromhex(old_value[2:])
                                            new_bytes = bytes.fromhex(new_value[2:])
                                            old_decoded = self.decoder.decode(old_bytes, element_type, 0)
                                            new_decoded = self.decoder.decode(new_bytes, element_type, 0)
                                        except Exception:
                                            pass

                            # Try dynamic array
                            if not variable and dynamic_array_index:
                                array_match = self.slot_resolver.try_match_dynamic_array_slot(slot_int, layout, dynamic_array_index)
                                if array_match:
                                    stats["dynamic_array"] += 1
                                    resolution_path = "dynamic_array"
                                    variable = array_match["variable"]
                                    variable_path = array_match["path"]
                                    encoding = array_match.get("encoding")
                                    array_index = array_match.get("array_index")
                                    element_type = array_match.get("element_type")
                                    element_type_id = element_type.id if element_type else None
                                    decode_type = array_match.get("decode_type")
                                    struct_slot_offset = array_match.get("struct_slot_offset", 0) or 0
                                    slot_members = array_match.get("slot_members")
                                    if slot_members and len(slot_members) > 1:
                                        value_type = "packed"
                                        try:
                                            old_bytes = bytes.fromhex(old_value[2:])
                                            new_bytes = bytes.fromhex(new_value[2:])
                                            old_packed = self.decoder.decode_packed_slot(old_bytes, slot_members, layout.types if layout else {})
                                            new_packed = self.decoder.decode_packed_slot(new_bytes, slot_members, layout.types if layout else {})
                                            old_decoded = DecodedValue(raw=old_value, decoded={k: v.decoded for k, v in old_packed.items()}, type_label="packed")
                                            new_decoded = DecodedValue(raw=new_value, decoded={k: v.decoded for k, v in new_packed.items()}, type_label="packed")
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

                            # Try mapping-to-array
                            if not variable and mapping_to_array_index:
                                m2a_match = self.slot_resolver.try_match_mapping_to_array_slot(slot_int, layout, mapping_to_array_index)
                                if m2a_match:
                                    stats["mapping_to_array"] += 1
                                    resolution_path = "mapping_to_array"
                                    variable = m2a_match["variable"]
                                    variable_path = m2a_match["path"]
                                    encoding = m2a_match.get("encoding")
                                    is_mapping = True
                                    mapping_key = m2a_match.get("mapping_key")
                                    array_index = m2a_match.get("array_index")
                                    element_type = m2a_match.get("element_type")
                                    element_type_id = element_type.id if element_type else None
                                    decode_type = m2a_match.get("decode_type")
                                    struct_slot_offset = m2a_match.get("struct_slot_offset", 0) or 0
                                    slot_members = m2a_match.get("slot_members")
                                    if slot_members and len(slot_members) > 1:
                                        value_type = "packed"
                                        try:
                                            old_bytes = bytes.fromhex(old_value[2:])
                                            new_bytes = bytes.fromhex(new_value[2:])
                                            old_packed = self.decoder.decode_packed_slot(old_bytes, slot_members, layout.types if layout else {})
                                            new_packed = self.decoder.decode_packed_slot(new_bytes, slot_members, layout.types if layout else {})
                                            old_decoded = DecodedValue(raw=old_value, decoded={k: v.decoded for k, v in old_packed.items()}, type_label="packed")
                                            new_decoded = DecodedValue(raw=new_value, decoded={k: v.decoded for k, v in new_packed.items()}, type_label="packed")
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

                            # Try dynamic bytes
                            if not variable and dynamic_bytes_index:
                                bytes_match = self.slot_resolver.try_match_dynamic_bytes_slot(slot_int, layout, dynamic_bytes_index)
                                if bytes_match:
                                    stats["dynamic_bytes"] += 1
                                    resolution_path = "dynamic_bytes"
                                    variable = bytes_match["variable"]
                                    variable_path = bytes_match["path"]
                                    encoding = bytes_match.get("encoding")
                                    data_offset = bytes_match.get("data_offset", 0)
                                    try:
                                        old_bytes = bytes.fromhex(old_value[2:])
                                        new_bytes = bytes.fromhex(new_value[2:])
                                        var_type = layout.get_type(variable.type_id)
                                        type_label = var_type.label if var_type else "bytes"
                                        old_decoded = self.decoder.decode_dynamic_bytes_data_slot(old_bytes, type_label, data_offset)
                                        new_decoded = self.decoder.decode_dynamic_bytes_data_slot(new_bytes, type_label, data_offset)
                                    except Exception as e:
                                        logger.warning(f"Failed to decode dynamic bytes data slot: {e}")
                    except Exception as e:
                        logger.error(f"Slot matching/decoding failed for slot {slot_hex}: {e}", exc_info=True)

                # Handle struct offsets
                if not variable and slot_hex not in preimage_lookup:
                    for struct_offset in range(1, 10):
                        base_slot_int = slot_int - struct_offset
                        base_slot_hex = self._normalize_slot(hex(base_slot_int))
                        if base_slot_hex in preimage_lookup:
                            base_preimage = preimage_lookup[base_slot_hex]
                            base_match = self.slot_resolver.try_match_slot_from_preimage(
                                base_slot_hex, base_preimage, layout, preimage_lookup
                            )
                            if base_match:
                                base_var = base_match.get("variable")
                                if base_var:
                                    stats["struct_offset"] += 1
                                    resolution_path = "struct_offset"
                                    variable = base_var
                                    mapping_base_slot = base_match.get("base_slot")
                                    mapping_key = base_match.get("key")
                                    base_path = base_match.get("path", "")
                                    is_mapping = True
                                    encoding = base_match.get("encoding")
                                    key_type = base_match.get("key_type")
                                    value_type = base_match.get("value_type")

                                    field_name, field_type = self.slot_resolver.resolve_struct_field(base_var, struct_offset, layout)
                                    if field_name:
                                        variable_path = f"{base_path}.{field_name}" if base_path else f".{field_name}"
                                        if field_type:
                                            try:
                                                old_bytes = bytes.fromhex(old_value[2:])
                                                new_bytes = bytes.fromhex(new_value[2:])
                                                old_decoded = self.decoder.decode(old_bytes, field_type, 0)
                                                new_decoded = self.decoder.decode(new_bytes, field_type, 0)
                                            except Exception:
                                                pass
                                    else:
                                        variable_path = f"{base_path}[+{struct_offset}]" if base_path else f"[+{struct_offset}]"
                                    break

                # Heuristic decode if no layout or no decoded values
                if (not layout or not variable) and not old_decoded:
                    try:
                        old_bytes = bytes.fromhex(old_value[2:])
                        new_bytes = bytes.fromhex(new_value[2:])
                        old_decoded = self.decoder.decode_heuristic(old_bytes)
                        new_decoded = self.decoder.decode_heuristic(new_bytes)
                    except Exception:
                        pass

                if resolution_path == "unknown":
                    stats["heuristic"] += 1

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

        # Second pass: struct offset detection
        for i, change in enumerate(decoded_changes):
            if change.variable is None:
                slot_int = int(change.slot, 16)
                for offset in range(1, 11):
                    base_slot_int = slot_int - offset
                    if base_slot_int in matched_slots:
                        base_match = matched_slots[base_slot_int]
                        base_var = base_match["variable"]
                        base_key = base_match["mapping_key"]
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
                        break

        resolved = stats["layout_direct"] + stats["preimage_lookup"] + stats["struct_offset"] + stats["dynamic_array"] + stats["mapping_to_array"] + stats["dynamic_bytes"]
        logger.info(
            f"Slot resolution: {stats['total']} total, {resolved} resolved "
            f"(layout={stats['layout_direct']}, preimage={stats['preimage_lookup']}, "
            f"struct_offset={stats['struct_offset']}, array={stats['dynamic_array']}, "
            f"map_to_array={stats['mapping_to_array']}, bytes={stats['dynamic_bytes']}), "
            f"{stats['heuristic']} heuristic"
        )
        return decoded_changes
