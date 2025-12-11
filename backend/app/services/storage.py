"""Storage reader for fetching slot values at a specific block."""

import asyncio
import logging
from typing import Any, Optional

from web3 import Web3

# web3.py v7 introduced Web3RPCError, v6 uses generic exceptions
try:
    from web3.exceptions import Web3RPCError
except ImportError:
    # Fallback for web3.py v6
    Web3RPCError = Exception

from app.config import Settings
from app.models.errors import RPCError
from app.models.domain import (
    DecodedValue,
    SlotValue,
    StorageLayout,
    StorageSnapshot,
    StorageVariable,
)
from app.repositories.cache import CacheRepository
from app.services.decoder import TypeDecoder
from app.services.web3_provider import Web3Provider
from app.utils.slots import compute_mapping_slot

logger = logging.getLogger(__name__)


class StorageReader:
    """Reads storage state at a block."""

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
        self._semaphore = asyncio.Semaphore(20)  # Limit concurrent RPC calls

    async def read_at_block(
        self,
        chain_id: int,
        address: str,
        block_number: int | str,
        layout: Optional[StorageLayout] = None,
        include_mapping_keys: Optional[dict[int, list[Any]]] = None,
    ) -> StorageSnapshot:
        """
        Read complete storage state at a block.

        For verified contracts (layout provided): reads all static slots + mapping entries.
        For unverified contracts: scans slots 0-256 for non-zero values.
        """
        address = Web3.to_checksum_address(address)

        # Check cache first
        # Cache disabled for testing; always compute fresh

        # Read based on whether we have a layout
        if layout:
            slots = await self._read_verified_contract(
                chain_id, address, block_number, layout, include_mapping_keys
            )
        else:
            slots = await self._read_unverified_contract(chain_id, address, block_number)

        is_complete = len(slots) <= self.settings.max_slots_per_contract
        if len(slots) > self.settings.max_slots_per_contract:
            slots = slots[: self.settings.max_slots_per_contract]
            is_complete = False

        snapshot = StorageSnapshot(
            chain_id=chain_id,
            address=address,
            block_number=block_number,
            slots=slots,
            is_complete=is_complete,
            layout=layout,
        )

        # Cache result
        if self.cache_repo:
            await self.cache_repo.save_snapshot(snapshot)

        return snapshot

    async def read_slot(
        self, chain_id: int, address: str, slot: int, block_number: int | str
    ) -> str:
        """Read a single slot value (hex string)."""
        web3 = self.web3_provider.get_web3(chain_id)
        slot_hex = hex(slot)

        try:
            async with self._semaphore:
                value = await web3.eth.get_storage_at(
                    address, slot_hex, block_identifier=block_number
                )
        except Web3RPCError as e:
            error_msg = str(e)
            # Check for block not found error
            if "block not found" in error_msg.lower():
                raise RPCError(
                    "eth_getStorageAt",
                    f"Block {block_number} not available (node may not have historical state)"
                )
            raise RPCError("eth_getStorageAt", error_msg)
        except Exception as e:
            raise RPCError("eth_getStorageAt", str(e))

        return "0x" + bytes(value).hex().zfill(64)

    async def read_slots_batch(
        self, chain_id: int, address: str, slots: list[int], block_number: int | str
    ) -> dict[int, str]:
        """
        Read multiple slots using JSON-RPC batching.

        Uses batched RPC calls to reduce HTTP overhead (100 slots = 1 HTTP request).
        Falls back to individual parallel calls if batching fails.
        """
        if not slots:
            return {}

        unique_slots = list(set(slots))

        # Try batch RPC first (much faster - 100 slots in 1 HTTP request)
        try:
            return await self.web3_provider.batch_get_storage_at(
                chain_id, address, unique_slots, block_number
            )
        except Exception as e:
            logger.warning(f"Batch storage read failed, falling back to individual calls: {e}")
            return await self._read_slots_individual(chain_id, address, unique_slots, block_number)

    async def _read_slots_individual(
        self, chain_id: int, address: str, slots: list[int], block_number: int | str
    ) -> dict[int, str]:
        """Fallback: read slots individually with parallel calls."""
        tasks = [
            self.read_slot(chain_id, address, slot, block_number)
            for slot in slots
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        slot_values = {}
        for slot, result in zip(slots, results):
            if isinstance(result, Exception):
                logger.warning(f"Failed to read slot {slot}: {result}")
                slot_values[slot] = "0x" + "00" * 32
            else:
                slot_values[slot] = result

        return slot_values

    async def _read_verified_contract(
        self,
        chain_id: int,
        address: str,
        block_number: int | str,
        layout: StorageLayout,
        mapping_keys: Optional[dict[int, list[Any]]] = None,
    ) -> list[SlotValue]:
        """Read storage for a verified contract using its layout."""
        slots_to_read = []
        slot_to_var: dict[int, tuple[StorageVariable, Any]] = {}
        mapping_slot_index: dict[int, tuple[StorageVariable, Any]] = {}
        vyper_string_vars: dict[int, int] = {}  # base_slot -> max_length

        # Collect static slots from layout
        for var in layout.variables:
            var_type = layout.get_type(var.type_id)
            if not var_type:
                continue

            # Check for Vyper String[N] type
            is_vyper_str, max_len = self.decoder.is_vyper_string(var_type.label)
            if is_vyper_str:
                # Vyper strings: 1 slot for length + ceil(max_len/32) slots for data
                num_data_slots = (max_len + 31) // 32
                total_slots = 1 + num_data_slots
                vyper_string_vars[var.slot] = max_len
                for i in range(total_slots):
                    slot = var.slot + i
                    slots_to_read.append(slot)
                    slot_to_var[slot] = (var, i)
            elif var_type.encoding in ("inplace", "bytes"):
                num_bytes = var_type.num_bytes or var.size or 32
                num_slots = max(1, (num_bytes + 31) // 32)
                for i in range(num_slots):
                    slot = var.slot + i
                    slots_to_read.append(slot)
                    slot_to_var[slot] = (var, i)

            elif var_type.encoding == "dynamic_array":
                # Read array length at base slot
                slots_to_read.append(var.slot)
                slot_to_var[var.slot] = (var, 0)

        # Add mapping entries for provided keys
        if mapping_keys:
            for base_slot, keys in mapping_keys.items():
                var = layout.get_variable_by_slot(base_slot)
                if not var:
                    continue

                var_type = layout.get_type(var.type_id)
                if not var_type or var_type.encoding != "mapping":
                    continue

                key_type = var_type.key_type or "bytes32"
                for key in keys:
                    computed_slot = compute_mapping_slot(base_slot, key, key_type)
                    slots_to_read.append(computed_slot)
                    slot_to_var[computed_slot] = (var, key)
                    mapping_slot_index[computed_slot] = (var, key)

        # Batch read
        slot_values = await self.read_slots_batch(
            chain_id, address, slots_to_read, block_number
        )

        # Build SlotValue results
        results = []
        base_slot_index = layout.get_base_slot_index()
        processed_vyper_strings = set()  # Track which Vyper strings we've already processed

        for slot, raw_value in sorted(slot_values.items()):
            var_info = slot_to_var.get(slot)
            variable = var_info[0] if var_info else None
            extra = var_info[1] if var_info else None

            if variable:
                decoded = None
                variable_path = None

                var_type = layout.get_type(variable.type_id)

                # Handle Vyper String[N] types specially
                if variable.slot in vyper_string_vars:
                    # Skip if we already processed this string (only process base slot)
                    if variable.slot in processed_vyper_strings:
                        continue
                    # Only process when we're at the base slot (extra == 0)
                    if extra != 0:
                        continue

                    processed_vyper_strings.add(variable.slot)
                    max_len = vyper_string_vars[variable.slot]
                    num_data_slots = (max_len + 31) // 32

                    # Gather length slot and data slots
                    length_slot_value = bytes.fromhex(raw_value[2:])
                    data_slot_values = []
                    for i in range(1, num_data_slots + 1):
                        data_slot = variable.slot + i
                        if data_slot in slot_values:
                            data_slot_values.append(bytes.fromhex(slot_values[data_slot][2:]))
                        else:
                            data_slot_values.append(b"\x00" * 32)

                    # Decode Vyper string
                    try:
                        decoded = self.decoder.decode_vyper_string(
                            length_slot_value, data_slot_values, max_len
                        )
                    except Exception as e:
                        logger.warning(f"Failed to decode Vyper string at slot {slot}: {e}")

                    variable_path = variable.name
                    results.append(
                        SlotValue(
                            slot=hex(slot),
                            raw_value=raw_value,
                            variable=variable,
                            decoded_value=decoded,
                            variable_path=variable_path,
                        )
                    )
                    continue

                decode_type = var_type
                # For mappings, decode using the value type
                if var_type and var_type.encoding == "mapping" and var_type.value_type:
                    decode_type = layout.get_type(var_type.value_type)
                # For static arrays, decode using the element type
                elif var_type and var_type.array_length and var_type.element_type:
                    decode_type = layout.get_type(var_type.element_type)

                if decode_type:
                    try:
                        raw_bytes = bytes.fromhex(raw_value[2:])
                        decoded = self.decoder.decode(
                            raw_bytes, decode_type, variable.offset
                        )
                    except Exception as e:
                        logger.warning(f"Failed to decode slot {slot}: {e}")

                # Build variable path
                if var_type and var_type.encoding == "mapping" and extra is not None:
                    key_display = extra
                    if isinstance(extra, str) and len(extra) == 42:
                        key_display = f"{extra[:6]}...{extra[-4:]}"
                    variable_path = f"{variable.name}[{key_display}]"
                elif var_type and var_type.array_length and isinstance(extra, int):
                    # Static array - extra is the slot offset (which equals array index for single-slot elements)
                    variable_path = f"{variable.name}[{extra}]"
                else:
                    variable_path = variable.name

                results.append(
                    SlotValue(
                        slot=hex(slot),
                        raw_value=raw_value,
                        variable=variable,
                        decoded_value=decoded,
                        variable_path=variable_path,
                    )
                )

            else:
                # No variable; include raw
                # Try to see if this slot is a hashed mapping slot: if the slot was derived from a provided key,
                # it will already be in slot_to_var; otherwise, we can't map it without a key.
                results.append(
                    SlotValue(
                        slot=hex(slot),
                        raw_value=raw_value,
                        variable=None,
                        decoded_value=None,
                        variable_path=None,
                    )
                )

        return results

    async def _read_unverified_contract(
        self,
        chain_id: int,
        address: str,
        block_number: int | str,
        additional_slots: Optional[list[int]] = None,
    ) -> list[SlotValue]:
        """Read storage for an unverified contract (scan 0-256)."""
        slots_to_read = list(range(257))

        if additional_slots:
            slots_to_read.extend(additional_slots)
            slots_to_read = list(set(slots_to_read))

        slot_values = await self.read_slots_batch(
            chain_id, address, slots_to_read, block_number
        )

        # Filter to non-zero values
        results = []
        zero_value = "0x" + "00" * 32

        for slot, raw_value in sorted(slot_values.items()):
            if raw_value != zero_value:
                results.append(
                    SlotValue(
                        slot=hex(slot),
                        raw_value=raw_value,
                        variable=None,
                        decoded_value=None,  # hex-first for unverified; heuristics optional at call site
                        variable_path=None,
                    )
                )

        return results

    async def get_single_slot(
        self,
        chain_id: int,
        address: str,
        slot: int,
        block_number: int | str,
        layout: Optional[StorageLayout] = None,
        use_heuristic_unverified: bool = False,
    ) -> SlotValue:
        """Read and decode a single slot."""
        raw_value = await self.read_slot(chain_id, address, slot, block_number)

        variable = None
        decoded = None
        variable_path = None

        if layout:
            variable = layout.get_variable_for_slot(slot)
            if variable:
                var_type = layout.get_type(variable.type_id)
                if var_type:
                    decode_type = var_type
                    array_index = None

                    # For static arrays, use element type and calculate index
                    if var_type.array_length and var_type.element_type:
                        decode_type = layout.get_type(var_type.element_type)
                        array_index = layout.get_static_array_index(variable, slot)

                    if decode_type:
                        try:
                            raw_bytes = bytes.fromhex(raw_value[2:])
                            decoded = self.decoder.decode(raw_bytes, decode_type, variable.offset)
                        except Exception:
                            pass

                    # Build variable path with array index if applicable
                    if array_index is not None:
                        variable_path = f"{variable.name}[{array_index}]"
                    else:
                        variable_path = variable.name
                else:
                    variable_path = variable.name
        elif use_heuristic_unverified:
            try:
                raw_bytes = bytes.fromhex(raw_value[2:])
                decoded = self.decoder.decode_heuristic(raw_bytes)
            except Exception:
                pass

        return SlotValue(
            slot=hex(slot),
            raw_value=raw_value,
            variable=variable,
            decoded_value=decoded,
            variable_path=variable_path,
        )
