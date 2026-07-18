"""Slot resolution - matching storage slots to layout variables."""

from bisect import bisect_right
from collections.abc import Callable
import logging
import re
from typing import Optional

from eth_abi import encode as abi_encode
from web3 import Web3

from app.models.domain import StorageLayout, StorageType, StorageVariable
from app.services.layout_index import ArrayPacking, array_packing

logger = logging.getLogger(__name__)


class SlotPathResolver:
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

        return self._resolve_type_struct_field(struct_type, struct_offset, layout)

    def resolve_match_struct_field(
        self,
        match: dict,
        struct_offset: int,
        layout: StorageLayout,
    ) -> tuple[str | None, StorageType | None]:
        """Resolve a field relative to the value type at a proven path.

        A match can already point through one or more mapping/struct layers.
        Prefer its current decoded value type instead of restarting from the
        top-level variable, which would interpret the offset against the wrong
        struct.
        """
        current_type = match.get("decode_type")
        if current_type and current_type.kind == "struct":
            return self._resolve_type_struct_field(
                current_type,
                struct_offset,
                layout,
            )

        variable = match.get("variable")
        if variable:
            return self.resolve_struct_field(variable, struct_offset, layout)

        return None, None

    @staticmethod
    def _resolve_type_struct_field(
        struct_type: StorageType | None,
        struct_offset: int,
        layout: StorageLayout,
    ) -> tuple[str | None, StorageType | None]:
        if struct_type and struct_type.members:
            for member in struct_type.members:
                if member.slot == struct_offset:
                    return member.name, layout.get_type(member.type_id)

        return None, None

    def try_match_slot_from_preimage(
        self,
        slot_hex: str,
        preimage: str,
        layout: Optional[StorageLayout],
        preimage_lookup: dict[str, str],
        depth: int = 0,
        visited: set[str] | None = None,
        struct_offsets: tuple[int, ...] | None = None,
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

        if struct_offsets is None:
            struct_offsets = self.get_struct_offsets(layout)

        # Some RPC clients/cache rows preserve a ``0x`` prefix on each memory
        # fragment before concatenating SHA3 input. Normalize those separators
        # back into one canonical byte string before interpreting word offsets.
        preimage_clean = re.sub(r"0x", "", preimage, flags=re.IGNORECASE)
        if len(preimage_clean) % 2 or not re.fullmatch(r"[0-9a-fA-F]+", preimage_clean):
            return None

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
                    depth=depth + 1,
                    visited=visited,
                    struct_offsets=struct_offsets,
                )
                if mapping_match:
                    variable = mapping_match.get("variable")
                    var_type = layout.get_type(variable.type_id) if variable else None

                    if var_type and var_type.encoding == "mapping" and var_type.value_type:
                        # The recursive match may already have traversed
                        # several mapping layers. Continue from its proven
                        # final value type instead of restarting at the
                        # top-level mapping's immediate value.
                        value_type = mapping_match.get("decode_type")
                        value_path = mapping_match.get("path")
                        if value_type and value_type.kind == "struct" and value_type.members:
                            array_member = next(
                                (
                                    member
                                    for member in value_type.members
                                    if member.slot == 0
                                    and (member_type := layout.get_type(member.type_id))
                                    and member_type.encoding == "dynamic_array"
                                ),
                                None,
                            )
                            if array_member:
                                value_type = layout.get_type(array_member.type_id)
                                value_path = f"{value_path}.{array_member.name}"
                        is_value_array = (
                            value_type and (
                                value_type.encoding == "dynamic_array" or
                                (value_type.element_type and "[]" in (value_type.label or ""))
                            )
                        )
                        if is_value_array:
                            element_type = layout.get_type(value_type.element_type) if value_type and value_type.element_type else None
                            packing = array_packing(element_type)

                            return {
                                "variable": variable,
                                "base_slot": mapping_match.get("base_slot"),
                                "key": mapping_match.get("key", "?"),
                                "path": value_path,
                                "encoding": "mapping_to_array",
                                "key_type": var_type.key_type if var_type else None,
                                "value_type": var_type.value_type if var_type else None,
                                "array_type": value_type,
                                "element_type": element_type,
                                "element_slots": packing.slots_per_element,
                                "array_packing": packing,
                                "data_start_slot": int(slot_hex, 16),
                                "array_length_slot": inner_slot_normalized,
                            }
            return None

        # Dynamic string/bytes mapping keys are hashed as their unpadded raw
        # contents followed by the base slot. Their preimages are not 64-byte
        # ABI pairs, so resolve them against the declared key schema first.
        dynamic_match = self._try_dynamic_mapping_preimage(
            preimage_clean,
            layout,
            preimage_lookup,
            depth,
            visited,
            struct_offsets,
        )
        if dynamic_match:
            return dynamic_match

        # Must be at least 64 bytes for a fixed-word mapping key + base slot.
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
            else:
                # Neither word is a direct base slot. Nested Solidity mappings
                # use the second word as an intermediate hash; do not leave the
                # failed Vyper candidate selected or the recursive lookup below
                # will inspect the mapping key instead of that hash.
                base_slot_int = second_int
                key_hex = first_32

        logger.debug(f"  Parsing preimage: key_hex={key_hex[:18]}..., base_slot_int={base_slot_int}")

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
                decoded_key = self.decode_mapping_key(key_hex, var_type.key_type)
                final_value_type_id, decode_type = self.get_final_mapping_value_type(var_type, layout)
                remaining_mapping_type = (
                    layout.get_type(var_type.value_type)
                    if var_type.value_type
                    else None
                )
                if remaining_mapping_type and remaining_mapping_type.encoding != "mapping":
                    remaining_mapping_type = None

                return {
                    "variable": variable,
                    "base_slot": base_slot_int,
                    "key": decoded_key,
                    "path": f"{variable.name}[{decoded_key}]",
                    "encoding": var_type.encoding,
                    "key_type": var_type.key_type,
                    "value_type": final_value_type_id,
                    "decode_type": decode_type,
                    "remaining_mapping_type": remaining_mapping_type,
                }

        # Check both proven nested-mapping encodings. Solidity hashes
        # ``key || previous_hash`` while Vyper hashes
        # ``previous_hash || key``.
        for intermediate_slot, nested_key_hex in (
            (second_int, first_32),
            (first_int, second_32),
        ):
            base_slot_normalized = self._normalize_slot(hex(intermediate_slot))
            if base_slot_normalized not in preimage_lookup:
                continue
            outer_preimage = preimage_lookup[base_slot_normalized]
            outer_match = self.try_match_slot_from_preimage(
                base_slot_normalized, outer_preimage, layout, preimage_lookup,
                depth=depth + 1,
                visited=visited,
                struct_offsets=struct_offsets,
            )
            if outer_match:
                outer_key = outer_match.get("key", "?")
                outer_variable = outer_match.get("variable")
                outer_var_type = layout.get_type(outer_variable.type_id) if outer_variable else None
                current_mapping_type = outer_match.get("remaining_mapping_type")
                decoded_key = self.decode_mapping_key(
                    nested_key_hex,
                    current_mapping_type.key_type if current_mapping_type else None,
                )

                final_value_type_id = None
                decode_type = None
                if outer_var_type:
                    final_value_type_id, decode_type = self.get_final_mapping_value_type(outer_var_type, layout)
                next_mapping_type = None
                if current_mapping_type and current_mapping_type.value_type:
                    candidate_type = layout.get_type(current_mapping_type.value_type)
                    if candidate_type and candidate_type.encoding == "mapping":
                        next_mapping_type = candidate_type

                return {
                    "variable": outer_variable,
                    "base_slot": outer_match.get("base_slot"),
                    "key": f"{outer_key}, {decoded_key}",
                    "path": f"{outer_variable.name}[{outer_key}][{decoded_key}]" if outer_variable else None,
                    "encoding": "mapping",
                    "key_type": outer_var_type.key_type if outer_var_type else None,
                    "value_type": final_value_type_id,
                    "decode_type": decode_type,
                    "remaining_mapping_type": next_mapping_type,
                }

        # Check if base_slot - offset is in preimage_lookup (mapping->struct->mapping case)
        # Example: users[addr].eTokenAllowance[spender] where allowance is at struct offset 2
        # base_slot_int = user_slot_hash + 2, so base_slot_int - 2 = user_slot_hash (in preimage_lookup)
        # Try both Solidity (second_int) and Vyper (first_int) base slots since we don't know which format is used
        for candidate_base, candidate_key_hex in [(second_int, first_32), (first_int, second_32)]:
            for offset, base_match in self.find_struct_offset_matches(
                candidate_base,
                layout,
                preimage_lookup,
                depth=depth,
                visited=visited,
                struct_offsets=struct_offsets,
            ):
                base_variable = base_match.get("variable")
                base_key = base_match.get("key", "?")
                field_name, field_type = self.resolve_match_struct_field(
                    base_match,
                    offset,
                    layout,
                )
                if not field_name or not field_type or field_type.encoding != "mapping":
                    continue
                nested_key = self.decode_mapping_key(
                    candidate_key_hex,
                    field_type.key_type,
                )
                base_path = base_match.get("path") or (
                    f"{base_variable.name}[{base_key}]" if base_variable else None
                )
                value_type = (
                    layout.get_type(field_type.value_type)
                    if field_type.value_type
                    else None
                )
                combined_key = f"{base_key}, {nested_key}"
                return {
                    "variable": base_variable,
                    "base_slot": base_match.get("base_slot"),
                    "key": combined_key,
                    "path": (
                        f"{base_path}.{field_name}[{nested_key}]"
                        if base_path
                        else None
                    ),
                    "encoding": "mapping",
                    "key_type": field_type.key_type,
                    "value_type": field_type.value_type,
                    "decode_type": value_type,
                    "remaining_mapping_type": (
                        value_type
                        if value_type and value_type.encoding == "mapping"
                        else None
                    ),
                }

        # Check for struct offset: slot might be base_hash + offset
        slot_int = int(slot_hex, 16)
        for offset, base_match in self.find_struct_offset_matches(
            slot_int,
            layout,
            preimage_lookup,
            depth=depth,
            visited=visited,
            struct_offsets=struct_offsets,
        ):
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
                "outer_key": self.decode_mapping_key(key_hex),
            }

        logger.debug(f"  Preimage chain break at depth {depth}: slot={slot_hex[:20]}... "
                    f"base_slot={base_slot_normalized[:20]}... not in layout or preimage_lookup")
        return None

    def find_struct_offset_matches(
        self,
        target_slot: int,
        layout: StorageLayout,
        preimage_lookup: dict[str, str],
        *,
        depth: int = 0,
        visited: set[str] | None = None,
        struct_offsets: tuple[int, ...] | None = None,
    ):
        """Yield only offsets proven by actual struct-member layout entries.

        Derive candidate base hashes from compiler-declared member offsets. The
        previous implementation recursively tested every observed SHA3 preimage,
        which became exponential on hash-heavy transactions.
        """
        if struct_offsets is None:
            struct_offsets = self.get_struct_offsets(layout)

        for offset in struct_offsets:
            potential_base = target_slot - offset
            if potential_base < 0:
                continue
            potential_base_hex = self._normalize_slot(potential_base)
            base_preimage = preimage_lookup.get(potential_base_hex)
            if base_preimage is None:
                continue
            base_match = self.try_match_slot_from_preimage(
                potential_base_hex,
                base_preimage,
                layout,
                preimage_lookup,
                depth=depth + 1,
                visited=visited,
                struct_offsets=struct_offsets,
            )
            base_variable = base_match.get("variable") if base_match else None
            if not base_variable:
                continue
            field_name, _ = self.resolve_match_struct_field(
                base_match,
                offset,
                layout,
            )
            if field_name:
                yield offset, base_match

    @staticmethod
    def get_struct_offsets(layout: StorageLayout) -> tuple[int, ...]:
        return tuple(
            sorted(
                {
                    member.slot
                    for storage_type in layout.types.values()
                    for member in (storage_type.members or ())
                    if member.slot > 0
                }
            )
        )

    def build_dynamic_array_index(
        self,
        layout: StorageLayout,
    ) -> dict[int, dict]:
        """Build dynamic-array descriptors; callers must supply runtime bounds."""
        index: dict[int, dict] = {}
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
            packing = array_packing(element_type)
            index[data_start] = {
                "variable": var,
                "array_packing": packing,
                "element_type": element_type,
                "array_length": var_type.array_length,
                "array_length_slot": var.slot,
            }
            logger.debug(
                "Dynamic array %s: data_start=%s, packing=%s",
                var.name,
                hex(data_start)[:18],
                packing,
            )

        return index

    def build_legacy_vyper_slot_index(
        self,
        layout: StorageLayout,
        preimage_lookup: dict[str, str],
        target_slots: set[int],
    ) -> dict[int, dict]:
        """Resolve pre-0.2.13 Vyper's recursively hashed composites.

        In this compiler era every top-level declaration owns one salt slot.
        Mappings hash ``parent || key``; arrays, structs, and bounded bytes hash
        the parent location at every descent and then add an index/member
        offset.  Trace SHA3 preimages provide proof for each hash edge.
        """
        exact: dict[int, dict] = {}
        descriptors: dict[int, dict] = {}

        def is_materialized(type_info: StorageType) -> bool:
            return not (
                type_info.encoding in {"mapping", "bytes"}
                or type_info.kind in {"struct", "array"}
            )

        for variable in layout.variables:
            type_info = layout.get_type(variable.type_id)
            if type_info is None:
                continue
            exact[variable.slot] = {
                "variable": variable,
                "path": variable.name,
                "type_info": type_info,
                "mapping_base_slot": None,
                "mapping_keys": [],
                "is_mapping": False,
                "array_index": None,
                "element_type_id": None,
                "field_name": None,
                "materialized": is_materialized(type_info),
            }

        def descriptor_child(base: int, parent: dict, location: int) -> dict | None:
            delta = location - base
            if delta < 0:
                return None
            parent_type = parent["type_info"]
            child_type = None
            path = parent["path"]
            array_index = parent.get("array_index")
            element_type_id = parent.get("element_type_id")
            field_name = None

            if parent_type.kind == "struct" and parent_type.members:
                member = next(
                    (member for member in parent_type.members if member.slot == delta),
                    None,
                )
                if member is None:
                    return None
                child_type = layout.get_type(member.type_id)
                path = f"{path}.{member.name}"
                field_name = member.name
            elif parent_type.kind == "array" and parent_type.element_type:
                if parent_type.array_length is not None and delta >= parent_type.array_length:
                    return None
                child_type = layout.get_type(parent_type.element_type)
                path = f"{path}[{delta}]"
                array_index = delta
                element_type_id = child_type.id if child_type else parent_type.element_type
            elif parent_type.encoding == "bytes":
                max_words = max(1, ((parent_type.num_bytes or 32) + 31) // 32)
                if delta >= max_words:
                    return None
                child_type = (
                    layout.get_type("uint256")
                    if delta == 0
                    else StorageType(
                        id="bytes32",
                        label="bytes32",
                        kind="value",
                        encoding="inplace",
                        num_bytes=32,
                    )
                )
                path = f"{path} (length)" if delta == 0 else f"{path} (data {delta - 1})"
            else:
                return None

            if child_type is None:
                return None
            return {
                **parent,
                "path": path,
                "type_info": child_type,
                "array_index": array_index,
                "element_type_id": element_type_id,
                "field_name": field_name,
                "materialized": is_materialized(child_type),
            }

        def resolve_location(location: int) -> dict | None:
            if location in exact:
                return exact[location]
            candidates = []
            for base, parent in descriptors.items():
                child = descriptor_child(base, parent, location)
                if child is not None:
                    candidates.append((location - base, child))
            return min(candidates, key=lambda candidate: candidate[0])[1] if candidates else None

        preimages = []
        for output_hex, preimage in preimage_lookup.items():
            cleaned = re.sub(r"0x", "", preimage, flags=re.IGNORECASE)
            if len(cleaned) not in {64, 128} or not re.fullmatch(
                r"[0-9a-fA-F]+", cleaned
            ):
                continue
            try:
                output = int(output_hex, 16)
            except ValueError:
                continue
            preimages.append((output, cleaned))

        for _ in range(len(preimages) + 1):
            changed = False
            for output, cleaned in preimages:
                if len(cleaned) == 128 and output not in exact:
                    parent_location = int(cleaned[:64], 16)
                    parent = resolve_location(parent_location)
                    if parent is None or parent["type_info"].encoding != "mapping":
                        continue
                    mapping_type = parent["type_info"]
                    value_type = (
                        layout.get_type(mapping_type.value_type)
                        if mapping_type.value_type
                        else None
                    )
                    if value_type is None:
                        continue
                    key = self.decode_mapping_key(
                        "0x" + cleaned[64:128],
                        mapping_type.key_type,
                    )
                    exact[output] = {
                        **parent,
                        "path": f"{parent['path']}[{key}]",
                        "type_info": value_type,
                        "mapping_base_slot": (
                            parent.get("mapping_base_slot")
                            if parent.get("mapping_base_slot") is not None
                            else parent["variable"].slot
                        ),
                        "mapping_keys": [*parent.get("mapping_keys", []), key],
                        "is_mapping": True,
                        "materialized": is_materialized(value_type),
                    }
                    changed = True
                elif len(cleaned) == 64 and output not in descriptors:
                    parent_location = int(cleaned, 16)
                    parent = resolve_location(parent_location)
                    if parent is None:
                        continue
                    parent_type = parent["type_info"]
                    if not (
                        parent_type.kind in {"struct", "array"}
                        or parent_type.encoding == "bytes"
                    ):
                        continue
                    descriptors[output] = parent
                    changed = True
            if not changed:
                break

        resolved = {}
        for slot in target_slots:
            match = resolve_location(slot)
            # Composite locations are salts for another hash edge, not storage
            # words themselves. Only scalar leaves (or hashed bytes children)
            # are safe to expose as resolved writes.
            if match is None or not match.get("materialized", False):
                continue
            type_info = match["type_info"]
            mapping_keys = match.get("mapping_keys", [])
            resolved[slot] = {
                "variable": match["variable"],
                "path": match["path"],
                "decode_type": type_info,
                "mapping_base_slot": match.get("mapping_base_slot"),
                "mapping_key": ", ".join(mapping_keys) if mapping_keys else None,
                "is_mapping": match.get("is_mapping", False),
                "encoding": (
                    "mapping" if type_info.encoding == "mapping"
                    else "legacy_vyper_hashed"
                ),
                "key_type": (
                    layout.get_type(match["variable"].type_id).key_type
                    if match.get("is_mapping")
                    and layout.get_type(match["variable"].type_id)
                    else None
                ),
                "value_type": type_info.id,
                "array_index": match.get("array_index"),
                "element_type_id": match.get("element_type_id"),
                "field_name": match.get("field_name"),
            }
        return resolved

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
    ) -> dict[int, tuple[StorageVariable, StorageType | None, ArrayPacking, int]]:
        """Build index of static array slot ranges."""
        index: dict[int, tuple[StorageVariable, StorageType | None, ArrayPacking, int]] = {}
        for var in layout.variables:
            var_type = layout.get_type(var.type_id)
            if not var_type:
                continue
            if var_type.encoding != "inplace" or not var_type.array_length:
                continue

            element_type = layout.get_type(var_type.element_type) if var_type.element_type else None
            packing = array_packing(element_type)

            start_slot = var.slot
            end_slot = var.slot + packing.slot_count(var_type.array_length)
            index[start_slot] = (var, element_type, packing, end_slot)
            logger.debug(
                "Static array %s: slots %s-%s, packing=%s",
                var.name,
                start_slot,
                end_slot - 1,
                packing,
            )

        return index

    def try_match_static_array_slot(
        self,
        slot_int: int,
        layout: StorageLayout,
        static_array_index: dict[int, tuple[StorageVariable, StorageType | None, ArrayPacking, int]],
    ) -> Optional[dict]:
        """Try to match a slot to a static array element."""
        for start_slot, (var, element_type, packing, end_slot) in static_array_index.items():
            if start_slot <= slot_int < end_slot:
                array_type = layout.get_type(var.type_id)
                locations = packing.locations_in_slot(
                    start_slot,
                    slot_int,
                    length=array_type.array_length if array_type else None,
                )
                if packing.is_packed:
                    return {
                        "variable": var,
                        "path": f"{var.name} (packed word)",
                        "array_index": None,
                        "element_locations": locations,
                        "element_type": element_type,
                        "encoding": "inplace",
                    }
                array_index = locations[0][0]
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
        dynamic_bytes_index: dict[int, StorageVariable],
    ) -> Optional[dict]:
        """Try to match a slot to dynamic bytes/string data."""
        for data_start, var in dynamic_bytes_index.items():
            offset_from_start = slot_int - data_start
            if offset_from_start == 0:
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
        dynamic_array_index: dict[int, dict],
        array_length: Callable[[int], int | None] | None = None,
    ) -> Optional[dict]:
        """Try to match a slot to a dynamic array element."""
        for data_start, match_info in dynamic_array_index.items():
            if slot_int < data_start:
                continue

            offset_from_start = slot_int - data_start
            var = match_info["variable"]
            packing = match_info["array_packing"]
            element_type = match_info.get("element_type")
            proven_length = match_info.get("array_length")
            if proven_length is None and array_length is not None:
                proven_length = array_length(match_info["array_length_slot"])
            if proven_length is None:
                continue
            if offset_from_start >= packing.slot_count(proven_length):
                continue

            if packing.is_packed:
                return {
                    "variable": var,
                    "base_slot": var.slot,
                    "array_index": None,
                    "struct_slot_offset": 0,
                    "field_name": None,
                    "element_locations": packing.locations_in_slot(
                        data_start,
                        slot_int,
                        length=proven_length,
                    ),
                    "path": f"{var.name} (packed word)",
                    "encoding": "dynamic_array",
                    "element_type": element_type,
                    "decode_type": element_type,
                }

            if packing.slots_per_element > 1:
                array_index = offset_from_start // packing.slots_per_element
                struct_slot_offset = offset_from_start % packing.slots_per_element

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
        mapping_to_array_roots: tuple[int, ...] | None = None,
        array_length: Callable[[int], int | None] | None = None,
    ) -> Optional[dict]:
        """Try to match a slot to an element of a mapping-to-array."""
        roots = (
            mapping_to_array_roots
            if mapping_to_array_roots is not None
            else tuple(sorted(mapping_to_array_index))
        )
        end = bisect_right(roots, slot_int)
        for root_index in range(end - 1, -1, -1):
            data_start = roots[root_index]
            offset_from_start = slot_int - data_start
            match_info = mapping_to_array_index[data_start]
            packing = match_info.get("array_packing") or array_packing(
                match_info.get("element_type")
            )
            proven_length = match_info.get("array_length")
            if proven_length is None and array_length is not None:
                length_slot = match_info.get("array_length_slot")
                if length_slot is not None:
                    proven_length = array_length(int(length_slot, 16))
            if proven_length is None:
                continue
            if offset_from_start >= packing.slot_count(proven_length):
                continue
            element_type = match_info.get("element_type")
            variable = match_info.get("variable")
            mapping_key = match_info.get("key", "?")
            base_path = match_info.get("path") or (
                f"{variable.name}[{mapping_key}]" if variable else "?"
            )

            if packing.is_packed:
                return {
                    "variable": variable,
                    "base_slot": match_info.get("base_slot"),
                    "array_index": None,
                    "struct_slot_offset": 0,
                    "mapping_key": mapping_key,
                    "field_name": None,
                    "element_locations": packing.locations_in_slot(
                        data_start, slot_int, length=proven_length
                    ),
                    "path": f"{base_path} (packed word)",
                    "encoding": "mapping_to_array",
                    "element_type": element_type,
                    "decode_type": element_type,
                }

            if packing.slots_per_element > 1:
                array_index = offset_from_start // packing.slots_per_element
                struct_slot_offset = offset_from_start % packing.slots_per_element

                slot_members = []
                if element_type and element_type.members:
                    for member in element_type.members:
                        if member.slot == struct_slot_offset:
                            slot_members.append(member)

                if len(slot_members) > 1:
                    path = f"{base_path}[{array_index}]" if struct_slot_offset == 0 else f"{base_path}[{array_index}][+{struct_slot_offset}]"
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
                    path = f"{base_path}[{array_index}].{field_name}"
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
                    path = f"{base_path}[{array_index}][+{struct_slot_offset}]"
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
                return {
                    "variable": variable,
                    "base_slot": match_info.get("base_slot"),
                    "array_index": array_index,
                    "struct_slot_offset": 0,
                    "mapping_key": mapping_key,
                    "field_name": None,
                    "path": f"{base_path}[{array_index}]",
                    "encoding": "mapping_to_array",
                    "element_type": element_type,
                    "decode_type": element_type,
                }

        return None

    def _try_dynamic_mapping_preimage(
        self,
        preimage_clean: str,
        layout: StorageLayout,
        preimage_lookup: dict[str, str],
        depth: int,
        visited: set[str],
        struct_offsets: tuple[int, ...],
    ) -> Optional[dict]:
        if len(preimage_clean) < 64:
            return None

        candidates = [
            (preimage_clean[-64:], preimage_clean[:-64], "solidity"),
            (preimage_clean[:64], preimage_clean[64:], "vyper"),
        ]
        for base_hex, key_data, ordering in candidates:
            if not key_data:
                continue
            base_slot = int(base_hex, 16)
            variable = layout.get_mapping_by_base_slot(base_slot)
            outer_match = None
            var_type = layout.get_type(variable.type_id) if variable else None
            if not variable:
                base_slot_hex = self._normalize_slot(hex(base_slot))
                outer_preimage = preimage_lookup.get(base_slot_hex)
                if not outer_preimage:
                    continue
                outer_match = self.try_match_slot_from_preimage(
                    base_slot_hex,
                    outer_preimage,
                    layout,
                    preimage_lookup,
                    depth=depth + 1,
                    visited=visited,
                    struct_offsets=struct_offsets,
                )
                if not outer_match:
                    continue
                variable = outer_match.get("variable")
                var_type = outer_match.get("remaining_mapping_type")

            key_type = (var_type.key_type or "") if var_type else ""
            normalized_key_type = key_type.lower()
            if "string" not in normalized_key_type and not re.search(
                r"(?:^|t_)bytes(?:_storage)?$", normalized_key_type
            ):
                continue
            if var_type is None or variable is None:
                continue

            decoded_key = self.decode_mapping_key("0x" + key_data, key_type)
            final_value_type_id, decode_type = self.get_final_mapping_value_type(var_type, layout)
            outer_key = outer_match.get("key") if outer_match else None
            combined_key = f"{outer_key}, {decoded_key}" if outer_key else decoded_key
            path = (
                f"{outer_match.get('path')}[{decoded_key}]"
                if outer_match
                else f"{variable.name}[{decoded_key}]"
            )
            logger.debug(
                "Resolved %s dynamic mapping preimage for %s",
                ordering,
                variable.name,
            )
            next_mapping_type = None
            if var_type.value_type:
                candidate_type = layout.get_type(var_type.value_type)
                if candidate_type and candidate_type.encoding == "mapping":
                    next_mapping_type = candidate_type
            return {
                "variable": variable,
                "base_slot": base_slot,
                "key": combined_key,
                "path": path,
                "encoding": "mapping",
                "key_type": key_type,
                "value_type": final_value_type_id,
                "decode_type": decode_type,
                "remaining_mapping_type": next_mapping_type,
            }
        return None

    def decode_mapping_key(self, key_hex: str, key_type: str | None = None) -> str:
        """Decode a mapping key using its declared storage type when available."""
        if not key_hex or not key_hex.startswith("0x"):
            return key_hex

        key_bytes = key_hex[2:]

        if key_type:
            normalized = key_type.lower()
            raw = bytes.fromhex(key_bytes)
            if "string" in normalized:
                try:
                    return raw.decode("utf-8")
                except UnicodeDecodeError:
                    return key_hex
            if re.search(r"(?:^|t_)bytes(?:_storage)?$", normalized):
                return key_hex
            fixed_bytes = re.search(r"bytes(\d+)", normalized)
            if fixed_bytes:
                size = int(fixed_bytes.group(1))
                return "0x" + raw[:size].hex()
            if "address" in normalized or "contract" in normalized:
                return "0x" + raw[-20:].hex()
            if "bool" in normalized:
                return "true" if int.from_bytes(raw, "big") else "false"
            if "uint" in normalized or "enum" in normalized:
                return str(int.from_bytes(raw, "big"))
            if "int" in normalized:
                return str(int.from_bytes(raw, "big", signed=True))

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
