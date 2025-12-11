"""Slot resolution - matching storage slots to layout variables."""

import logging
from typing import Optional

from eth_abi import encode as abi_encode
from web3 import Web3

from app.models.domain import StorageLayout, StorageType, StorageVariable

logger = logging.getLogger(__name__)


class SlotResolver:
    """Resolves storage slots to layout variables."""

    def get_final_mapping_value_type(
        self,
        var_type: StorageType,
        layout: StorageLayout,
    ) -> tuple[str | None, StorageType | None]:
        """
        Fully unwrap nested mappings to get the final value type.

        For mapping(A => mapping(B => mapping(C => uint256))):
        Returns ("t_uint256", StorageType for uint256)
        """
        current_type = var_type
        final_value_type_id = None

        while current_type and current_type.encoding == "mapping":
            if not current_type.value_type:
                break
            final_value_type_id = current_type.value_type
            inner_type = layout.get_type(current_type.value_type)
            if inner_type and inner_type.encoding == "mapping":
                current_type = inner_type
            else:
                return final_value_type_id, inner_type

        return final_value_type_id, layout.get_type(final_value_type_id) if final_value_type_id else None

    def resolve_struct_field(
        self,
        base_variable: StorageVariable,
        struct_offset: int,
        layout: StorageLayout,
    ) -> tuple[str | None, StorageType | None]:
        """Resolve struct field name from offset."""
        var_type = layout.get_type(base_variable.type_id)
        if not var_type:
            return None, None

        struct_type = None

        if var_type.encoding == "mapping" and var_type.value_type:
            struct_type = layout.get_type(var_type.value_type)
        elif var_type.encoding == "dynamic_array" and var_type.element_type:
            struct_type = layout.get_type(var_type.element_type)
        elif var_type.kind == "struct":
            struct_type = var_type

        if struct_type and struct_type.members:
            for member in struct_type.members:
                if member.slot == struct_offset:
                    member_type = layout.get_type(member.type_id)
                    if member_type and member_type.kind == "struct" and member_type.members:
                        return member.name, member_type
                    return member.name, member_type

        return None, None

    def try_match_slot_from_preimage(
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
        """
        if depth > 5:
            logger.debug(f"Max recursion depth reached for slot {slot_hex[:18]}...")
            return None

        if visited is None:
            visited = set()

        if slot_hex in visited:
            logger.debug(f"Cycle detected for slot {slot_hex[:18]}...")
            return None
        visited = visited | {slot_hex}

        if not preimage or not layout:
            return None

        preimage_clean = preimage[2:] if preimage.startswith("0x") else preimage

        # Handle 32-byte preimage: keccak256(single_slot) for dynamic arrays
        if len(preimage_clean) == 64:
            inner_slot_hex = "0x" + preimage_clean
            inner_slot_normalized = self._normalize_slot(inner_slot_hex)
            logger.debug(f"  32-byte preimage (array data start): inner_slot={inner_slot_normalized[:18]}...")

            if inner_slot_normalized in preimage_lookup:
                inner_preimage = preimage_lookup[inner_slot_normalized]
                logger.debug(f"  Found inner preimage for array length slot: {inner_preimage[:40]}...")
                mapping_match = self.try_match_slot_from_preimage(
                    inner_slot_normalized, inner_preimage, layout, preimage_lookup,
                    depth=depth + 1, visited=visited
                )
                if mapping_match:
                    variable = mapping_match.get("variable")
                    var_type = layout.get_type(variable.type_id) if variable else None

                    if var_type and var_type.encoding == "mapping" and var_type.value_type:
                        value_type = layout.get_type(var_type.value_type)
                        is_value_array = (
                            value_type and (
                                value_type.encoding == "dynamic_array" or
                                (value_type.element_type and "[]" in (value_type.label or ""))
                            )
                        )
                        if is_value_array:
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
                                "data_start_slot": int(slot_hex, 16),
                            }
            return None

        # Must be at least 64 bytes for a mapping
        if len(preimage_clean) < 128:
            return None

        # Try both orderings: Solidity (key || slot) and Vyper (slot || key)
        # Solidity: first 32 bytes = key, second 32 bytes = slot
        # Vyper: first 32 bytes = slot, second 32 bytes = key

        first_32 = "0x" + preimage_clean[:64]
        second_32 = "0x" + preimage_clean[64:128]
        first_int = int(first_32, 16)
        second_int = int(second_32, 16)

        # Try Solidity format first (key, slot)
        key_hex = first_32
        base_slot_int = second_int
        variable = layout.get_mapping_by_base_slot(base_slot_int)

        # If not found, try Vyper format (slot, key)
        if not variable:
            base_slot_int = first_int
            key_hex = second_32
            variable = layout.get_mapping_by_base_slot(base_slot_int)
            if variable:
                logger.debug(f"  Vyper-style preimage: slot={base_slot_int}, key={key_hex[:18]}...")

        logger.debug(f"  Parsing preimage: key_hex={key_hex[:18]}..., base_slot_int={base_slot_int}")

        decoded_key = self.decode_mapping_key(key_hex)

        # Heuristic for namespaced storage (ERC-7201)
        if not variable and base_slot_int < 256:
            namespace_base = None
            for var in layout.variables:
                if var.slot > 2**200:
                    if namespace_base is None or var.slot < namespace_base:
                        namespace_base = var.slot

            if namespace_base is not None:
                target_slot = namespace_base + base_slot_int
                variable = layout.get_mapping_by_base_slot(target_slot)
                if variable:
                    logger.debug(
                        f"  Namespace heuristic: preimage base_slot={base_slot_int} matched "
                        f"{variable.name} at absolute slot 0x{target_slot:x}"
                    )

        logger.debug(f"  get_mapping_by_base_slot({base_slot_int}) = {variable.name if variable else None}")
        if variable:
            var_type = layout.get_type(variable.type_id)
            logger.debug(f"  Preimage match: base_slot={base_slot_int}, var={variable.name}, var_type_encoding={var_type.encoding if var_type else None}")
            if var_type and var_type.encoding == "mapping":
                final_value_type_id, decode_type = self.get_final_mapping_value_type(var_type, layout)

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

        # Check if base_slot is an intermediate hash (nested mapping)
        base_slot_normalized = self._normalize_slot(base_slot_hex)
        logger.debug(f"  Checking if base_slot is intermediate hash: {base_slot_normalized[:18]}... in_lookup={base_slot_normalized in preimage_lookup}")
        if base_slot_normalized in preimage_lookup:
            outer_preimage = preimage_lookup[base_slot_normalized]
            logger.debug(f"  Recursing with outer preimage: {outer_preimage[:40]}...")
            outer_match = self.try_match_slot_from_preimage(
                base_slot_normalized, outer_preimage, layout, preimage_lookup,
                depth=depth + 1, visited=visited
            )
            logger.debug(f"  Recursion result: outer_match={outer_match is not None}, outer_var={outer_match.get('variable').name if outer_match and outer_match.get('variable') else None}")
            if outer_match:
                outer_key = outer_match.get("key", "?")
                outer_variable = outer_match.get("variable")
                outer_var_type = layout.get_type(outer_variable.type_id) if outer_variable else None

                final_value_type_id = None
                decode_type = None
                if outer_var_type:
                    final_value_type_id, decode_type = self.get_final_mapping_value_type(outer_var_type, layout)

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

        # Check for struct offset: slot might be base_hash + offset
        slot_int = int(slot_hex, 16)
        for offset in range(1, 10):
            potential_base = slot_int - offset
            potential_base_hex = self._normalize_slot(hex(potential_base))
            if potential_base_hex in preimage_lookup:
                base_preimage = preimage_lookup[potential_base_hex]
                logger.debug(f"  Struct offset check: slot_hex-{offset} = {potential_base_hex[:18]}... trying to match")
                base_match = self.try_match_slot_from_preimage(
                    potential_base_hex, base_preimage, layout, preimage_lookup,
                    depth=depth + 1, visited=visited
                )
                logger.debug(f"  Struct offset match result: {base_match is not None}, var={base_match.get('variable').name if base_match and base_match.get('variable') else None}")
                if base_match:
                    base_variable = base_match.get("variable")
                    base_key = base_match.get("key", "?")
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

        logger.debug(f"  Preimage chain break at depth {depth}: slot={slot_hex[:20]}... "
                    f"base_slot={base_slot_normalized[:20]}... not in layout or preimage_lookup")
        return None

    def build_dynamic_array_index(
        self,
        layout: StorageLayout,
    ) -> dict[int, tuple[StorageVariable, int, StorageType | None]]:
        """Build index of dynamic array data start slots."""
        index: dict[int, tuple[StorageVariable, int, StorageType | None]] = {}
        for var in layout.variables:
            var_type = layout.get_type(var.type_id)
            if not var_type:
                continue
            is_dynamic_array = (
                var_type.encoding == "dynamic_array"
                or (var_type.element_type and "[]" in (var_type.label or ""))
            )
            if not is_dynamic_array:
                continue

            encoded_slot = abi_encode(["uint256"], [var.slot])
            data_start = int.from_bytes(Web3.keccak(encoded_slot), "big")

            element_type = layout.get_type(var_type.element_type) if var_type.element_type else None
            if element_type:
                element_bytes = element_type.num_bytes or 32
                element_slots = (element_bytes + 31) // 32
            else:
                element_slots = 1

            index[data_start] = (var, element_slots, element_type)
            logger.debug(f"Dynamic array {var.name}: data_start={hex(data_start)[:18]}..., element_slots={element_slots}")

        return index

    def build_dynamic_bytes_index(
        self,
        layout: StorageLayout,
    ) -> dict[int, StorageVariable]:
        """Build index of dynamic bytes/string data start slots."""
        index: dict[int, StorageVariable] = {}
        for var in layout.variables:
            var_type = layout.get_type(var.type_id)
            if not var_type or var_type.encoding != "bytes":
                continue

            encoded_slot = abi_encode(["uint256"], [var.slot])
            data_start = int.from_bytes(Web3.keccak(encoded_slot), "big")

            index[data_start] = var
            logger.debug(f"Dynamic bytes {var.name}: data_start={hex(data_start)[:18]}...")

        return index

    def build_static_array_index(
        self,
        layout: StorageLayout,
    ) -> dict[int, tuple[StorageVariable, StorageType | None, int, int]]:
        """Build index of static array slot ranges."""
        index: dict[int, tuple[StorageVariable, StorageType | None, int, int]] = {}
        for var in layout.variables:
            var_type = layout.get_type(var.type_id)
            if not var_type:
                continue
            if var_type.encoding != "inplace" or not var_type.array_length:
                continue

            element_type = layout.get_type(var_type.element_type) if var_type.element_type else None
            if element_type:
                element_bytes = element_type.num_bytes or 32
                element_slots = (element_bytes + 31) // 32
            else:
                element_slots = 1

            start_slot = var.slot
            end_slot = var.slot + (var_type.array_length * element_slots)
            index[start_slot] = (var, element_type, element_slots, end_slot)
            logger.debug(f"Static array {var.name}: slots {start_slot}-{end_slot-1}, element_slots={element_slots}")

        return index

    def try_match_static_array_slot(
        self,
        slot_int: int,
        layout: StorageLayout,
        static_array_index: dict[int, tuple[StorageVariable, StorageType | None, int, int]],
    ) -> Optional[dict]:
        """Try to match a slot to a static array element."""
        for start_slot, (var, element_type, element_slots, end_slot) in static_array_index.items():
            if start_slot <= slot_int < end_slot:
                array_index = (slot_int - start_slot) // element_slots
                return {
                    "variable": var,
                    "path": f"{var.name}[{array_index}]",
                    "array_index": array_index,
                    "element_type": element_type,
                    "encoding": "inplace",
                }
        return None

    def try_match_dynamic_bytes_slot(
        self,
        slot_int: int,
        layout: StorageLayout,
        dynamic_bytes_index: dict[int, StorageVariable],
    ) -> Optional[dict]:
        """Try to match a slot to dynamic bytes/string data."""
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

    def try_match_dynamic_array_slot(
        self,
        slot_int: int,
        layout: StorageLayout,
        dynamic_array_index: dict[int, tuple[StorageVariable, int, StorageType | None]],
    ) -> Optional[dict]:
        """Try to match a slot to a dynamic array element."""
        for data_start, (var, element_slots, element_type) in dynamic_array_index.items():
            if slot_int < data_start:
                continue

            offset_from_start = slot_int - data_start

            if element_slots > 1:
                array_index = offset_from_start // element_slots
                struct_slot_offset = offset_from_start % element_slots

                if array_index > 10_000_000:
                    continue

                slot_members = []
                if element_type and element_type.members:
                    for member in element_type.members:
                        if member.slot == struct_slot_offset:
                            slot_members.append(member)

                if len(slot_members) > 1:
                    path = f"{var.name}[{array_index}]" if struct_slot_offset == 0 else f"{var.name}[{array_index}][+{struct_slot_offset}]"
                    return {
                        "variable": var,
                        "base_slot": var.slot,
                        "array_index": array_index,
                        "struct_slot_offset": struct_slot_offset,
                        "field_name": None,
                        "slot_members": slot_members,
                        "path": path,
                        "encoding": "dynamic_array",
                        "element_type": element_type,
                        "decode_type": element_type,
                    }
                elif len(slot_members) == 1:
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
                array_index = offset_from_start
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

    def try_match_mapping_to_array_slot(
        self,
        slot_int: int,
        layout: StorageLayout,
        mapping_to_array_index: dict[int, dict],
    ) -> Optional[dict]:
        """Try to match a slot to an element of a mapping-to-array."""
        for data_start, match_info in mapping_to_array_index.items():
            if slot_int < data_start:
                continue

            offset_from_start = slot_int - data_start
            element_slots = match_info.get("element_slots", 1)
            element_type = match_info.get("element_type")
            variable = match_info.get("variable")
            mapping_key = match_info.get("key", "?")

            if element_slots > 1:
                array_index = offset_from_start // element_slots
                struct_slot_offset = offset_from_start % element_slots

                if array_index > 10_000_000:
                    continue

                slot_members = []
                if element_type and element_type.members:
                    for member in element_type.members:
                        if member.slot == struct_slot_offset:
                            slot_members.append(member)

                var_name = variable.name if variable else "?"
                if len(slot_members) > 1:
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

    def decode_mapping_key(self, key_hex: str) -> str:
        """Decode a mapping key from its 32-byte hex representation."""
        if not key_hex or not key_hex.startswith("0x"):
            return key_hex

        key_bytes = key_hex[2:]

        if len(key_bytes) == 64 and key_bytes[:24] == "0" * 24:
            return "0x" + key_bytes[24:]

        key_int = int(key_hex, 16)
        if key_int < 2**64:
            return str(key_int)

        return key_hex

    def _normalize_slot(self, slot: str) -> str:
        """Normalize slot to 66-char hex (0x + 64 chars)."""
        if isinstance(slot, int):
            return f"0x{slot:064x}"
        slot_clean = slot[2:] if slot.startswith("0x") else slot
        return f"0x{slot_clean.lower().zfill(64)}"
