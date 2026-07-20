"""Transaction API routes."""

from collections import defaultdict
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.dependencies import (
    get_transaction_history_service,
    get_transaction_response_cache,
)
from app.models.api import (
    ContractHistoryCountsResponse,
    ContractHistoryResponse,
    ContractResolutionResponse,
    GlobalStorageEventReferenceResponse,
    MappingParamResponse,
    PackedFieldResponse,
    SlotChangeResponse,
    StorageChangeResponse,
    StructDefinitionResponse,
    StructMemberResponse,
    TransactionCapabilitiesResponse,
    TransactionStorageHistoryResponse,
    TransactionSummaryResponse,
    ValuePair,
    ValuePairDecoded,
)
from app.models.domain import (
    StorageChange,
    StorageLayout,
    StorageType,
    StorageVariable,
)
from app.models.errors import (
    RPCError,
    TraceNotAvailableError,
    TransactionNotFoundError,
)
from app.services.decoder import TypeDecoder
from app.services.layout_index import LayoutIndex
from app.services.transaction_receipt import ReceiptIdentity
from app.services.transaction_history import TransactionHistoryService
from app.services.transaction_response_cache import (
    TransactionResponseCache,
    TransactionResponseKey,
)
from app.utils.type_labels import (
    clean_type_label,
    normalize_contract_label,
    strip_type_prefix,
)


import re


def _extract_keys_from_path(variable_path: Optional[str]) -> Optional[str]:
    """
    Extract mapping keys from a variable path like 'rewards[0xaddr1][0xaddr2]'.

    Returns comma-separated keys, e.g., '0xaddr1, 0xaddr2'
    """
    if not variable_path:
        return None

    # Find all [key] patterns but exclude [+N] struct offset patterns
    keys = re.findall(r'\[([^\[\]]+)\]', variable_path)
    # Filter out struct offset patterns like '+4'
    keys = [k for k in keys if not k.startswith('+')]

    if not keys:
        return None

    return ", ".join(keys)


def _get_mapping_key_types(
    variable: "StorageVariable",
    layout: Optional[StorageLayout],
) -> list[str]:
    """Get all key types for a (possibly nested) mapping."""

    if not layout or not variable:
        return []

    key_types = []
    var_type = layout.get_type(variable.type_id)

    while var_type and var_type.encoding == "mapping":
        if var_type.key_type:
            key_types.append(strip_type_prefix(var_type.key_type))
        if var_type.value_type:
            var_type = layout.get_type(var_type.value_type)
        else:
            break

    return key_types


def _get_final_value_type(
    variable: "StorageVariable",
    layout: Optional[StorageLayout],
) -> Optional[str]:
    """Get the final (innermost) value type for a mapping.

    For mapping(address => uint256), returns "uint256".
    For mapping(address => mapping(uint => uint256)), returns "uint256".
    For mapping(address => SomeStruct), returns "SomeStruct" (cleaned).
    """

    if not layout or not variable:
        return None

    var_type = layout.get_type(variable.type_id)
    if not var_type:
        return None

    # If not a mapping, return the type's label directly
    if var_type.encoding != "mapping":
        return strip_type_prefix(var_type.label) if var_type.label else None

    # Traverse nested mappings to find the final value type
    while var_type and var_type.encoding == "mapping":
        if var_type.value_type:
            inner_type = layout.get_type(var_type.value_type)
            if inner_type:
                if inner_type.encoding == "mapping":
                    # Continue unwrapping
                    var_type = inner_type
                else:
                    # Found the final value type
                    label = inner_type.label or var_type.value_type
                    # Clean up the label
                    cleaned = strip_type_prefix(label)
                    # Strip struct parent if present
                    if cleaned.startswith("struct ") and "." in cleaned:
                        parts = cleaned.rsplit(".", 1)
                        cleaned = f"struct {parts[1]}"
                    return cleaned
            else:
                # Can't resolve, return the type ID cleaned up
                return strip_type_prefix(var_type.value_type)
        else:
            break

    return None


def _format_mapping_key_value(key: str, key_type: str) -> str:
    """Format a mapping key value based on its type.

    - uint/int types: Convert hex to decimal string
    - address: Keep as checksummed hex
    - bytes: Keep as hex
    """
    key_type_lower = key_type.lower()

    # For uint/int types, convert hex to decimal
    if 'uint' in key_type_lower or 'int' in key_type_lower:
        if key.startswith('0x'):
            try:
                # Convert hex to decimal
                int_val = int(key, 16)
                return str(int_val)
            except ValueError:
                pass
        # Already decimal or couldn't parse
        return key

    # For addresses, ensure proper checksum format
    if 'address' in key_type_lower:
        if key.startswith('0x') and len(key) == 42:
            try:
                from web3 import Web3
                return Web3.to_checksum_address(key)
            except Exception:
                pass
        return key

    # Default: return as-is
    return key


def _build_mapping_params(
    mapping_key: Optional[str],
    variable: "StorageVariable",
    layout: Optional[StorageLayout],
) -> Optional[list[MappingParamResponse]]:
    """Build unified params array from mapping key and key types."""
    if not mapping_key:
        return None

    # Split the comma-separated keys
    keys = [k.strip() for k in mapping_key.split(",")]
    key_types = _get_mapping_key_types(variable, layout) if variable and layout else []

    # Build params array, pairing types with values
    params = []
    for i, key in enumerate(keys):
        param_type = key_types[i] if i < len(key_types) else "unknown"
        # Format the value based on type (e.g., uint256 hex -> decimal)
        formatted_value = _format_mapping_key_value(key, param_type)
        params.append(MappingParamResponse(type=param_type, value=formatted_value))

    return params if params else None


def _clean_value_type(value_type: Optional[str]) -> Optional[str]:
    """Clean up value_type to be more readable."""
    if not value_type:
        return None

    # Remove internal suffixes like "2384_storage"
    cleaned = value_type
    if "_storage" in cleaned:
        cleaned = cleaned.split("_storage")[0]

    # Clean up struct notation: "struct(Reward)2384" -> "Reward"
    if cleaned.startswith("struct(") and ")" in cleaned:
        # Extract just the struct name
        start = cleaned.index("(") + 1
        end = cleaned.index(")")
        cleaned = cleaned[start:end]

    # Contract/interface types are just addresses
    if cleaned.lower().startswith("contract"):
        cleaned = "address"

    return clean_type_label(cleaned)


def _preserve_large_ints(value: Any, threshold: int = 2**53) -> Any:
    """Convert large ints to strings to avoid JS precision loss in the API response."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(value) if abs(value) >= threshold else value
    if isinstance(value, list):
        return [_preserve_large_ints(v, threshold) for v in value]
    if isinstance(value, dict):
        return {k: _preserve_large_ints(v, threshold) for k, v in value.items()}
    return value


def _get_struct_definition(
    variable: "StorageVariable",
    layout: StorageLayout,
) -> Optional[StructDefinitionResponse]:
    """Get the struct definition for a mapping that points to a struct."""

    var_type = layout.get_type(variable.type_id)
    if not var_type:
        return None

    # For mappings, get the value type (which might be a struct)
    value_type_id = var_type.value_type
    while value_type_id:
        value_type = layout.get_type(value_type_id)
        if not value_type:
            break

        # If this is a struct with members, return the definition
        if value_type.members:
            # Extract the struct name from the label (e.g., "struct GovStaker.RewardData" -> "RewardData")
            struct_name = value_type.label
            if "." in struct_name:
                struct_name = struct_name.rsplit(".", 1)[1]
            if struct_name.startswith("struct "):
                struct_name = struct_name[7:]

            members = []
            for member in value_type.members:
                member_type = layout.get_type(member.type_id)
                members.append(
                    StructMemberResponse(
                        name=member.name,
                        type_label=clean_type_label(member_type.label if member_type else member.type_id),
                        slot_offset=member.slot,  # In members, slot is the offset within the struct
                        byte_offset=member.offset,
                        size=member.size,
                    )
                )
            return StructDefinitionResponse(name=struct_name, members=members)

        # Check nested mappings (e.g., mapping(address => mapping(address => Struct)))
        if value_type.encoding == "mapping" and value_type.value_type:
            value_type_id = value_type.value_type
        else:
            break

    return None


def _get_struct_type_from_value_type(
    value_type_id: str,
    layout: StorageLayout,
) -> Optional["StorageType"]:
    """Get the struct type from a value_type ID, traversing nested mappings."""

    while value_type_id:
        value_type = layout.get_type(value_type_id)
        if not value_type:
            return None

        # If this is a struct with members, return it
        if value_type.members:
            return value_type

        # Check nested mappings
        if value_type.encoding == "mapping" and value_type.value_type:
            value_type_id = value_type.value_type
        else:
            return None

    return None


def _get_struct_definition_from_type_id(
    type_id: str,
    layout: StorageLayout,
) -> Optional[StructDefinitionResponse]:
    """Get struct definition directly from a type ID (e.g., element_type for dynamic arrays)."""
    value_type = layout.get_type(type_id)
    if not value_type or not value_type.members:
        return None

    # Extract the struct name from the label (e.g., "struct Voter.Proposal" -> "Proposal")
    struct_name = value_type.label
    if "." in struct_name:
        struct_name = struct_name.rsplit(".", 1)[1]
    if struct_name.startswith("struct "):
        struct_name = struct_name[7:]

    members = []
    for member in value_type.members:
        member_type = layout.get_type(member.type_id)
        members.append(
            StructMemberResponse(
                name=member.name,
                type_label=clean_type_label(member_type.label if member_type else member.type_id),
                slot_offset=member.slot,  # In members, slot is the offset within the struct
                byte_offset=member.offset,
                size=member.size,
            )
        )
    return StructDefinitionResponse(name=struct_name, members=members)


def _get_struct_members_in_slot(
    struct_type: "StorageType",
    slot_offset: int,
) -> list["StorageVariable"]:
    """Get struct members that reside in the given slot offset within the struct."""

    if not struct_type.members:
        return []

    # Find members in this slot offset
    return [m for m in struct_type.members if m.slot == slot_offset]


def _group_changes_by_slot(
    changes: list[StorageChange],
    layout: Optional[StorageLayout] = None,
    storage_address: Optional[str] = None,
    layouts_by_code_address: Optional[dict[str, StorageLayout]] = None,
) -> list[SlotChangeResponse]:
    """Group storage changes by slot, preserving execution order."""
    if not changes:
        return []

    decoder = TypeDecoder()
    normalized_storage_address = (
        storage_address.lower() if storage_address else None
    )
    default_layout = layout
    layouts_by_code_address = {
        address.lower(): code_layout
        for address, code_layout in (layouts_by_code_address or {}).items()
    }

    # Group changes by slot
    slot_changes: dict[str, list[StorageChange]] = defaultdict(list)
    for c in changes:
        slot_changes[c.slot].append(c)

    # Sort changes within each slot by change_index (execution order)
    for slot in slot_changes:
        slot_changes[slot].sort(key=lambda x: x.change_index)

    # Build SlotChangeResponse for each slot
    result: list[SlotChangeResponse] = []
    for slot, slot_change_list in slot_changes.items():
        first = slot_change_list[0]
        last = slot_change_list[-1]
        layout = (
            layouts_by_code_address.get((first.code_address or "").lower())
            or default_layout
        )
        summary_before = first.state_initial_value or first.old_value
        summary_after = last.state_final_value or last.new_value

        # Packed-array decoding can emit several logical paths for one physical
        # SSTORE. The forensic event inventory must still contain that opcode
        # exactly once.
        physical_changes: list[StorageChange] = []
        seen_steps: set[tuple[int, Optional[int], Optional[int]]] = set()
        for change in slot_change_list:
            event_key = (change.change_index, change.pc, change.frame_id)
            if event_key not in seen_steps:
                physical_changes.append(change)
                seen_steps.add(event_key)

        resolved_paths = list(
            dict.fromkeys(
                change.variable_path
                for change in slot_change_list
                if change.variable_path
            )
        )

        net_changed = (
            summary_before != summary_after if first.state_values_known else None
        )
        if net_changed is True:
            classification = "net_changed"
        elif physical_changes and all(
            change.frame_outcome == "reverted" for change in physical_changes
        ):
            classification = "reverted_only"
        elif (
            first.state_values_known
            and summary_before == summary_after
            and any(
                change.frame_outcome == "applied"
                and change.changed_value is True
                for change in physical_changes
            )
        ):
            classification = "restored"
        elif physical_changes and all(
            change.changed_value is False for change in physical_changes
        ):
            classification = "noop_only"
        elif first.state_values_known and summary_before == summary_after:
            classification = "unchanged"
        else:
            classification = "unknown"

        def decoded_for_value(encoded: Optional[str]):
            if encoded is None:
                return None
            for change in slot_change_list:
                if change.old_value == encoded and change.old_decoded:
                    return change.old_decoded.decoded
                if change.new_value == encoded and change.new_decoded:
                    return change.new_decoded.decoded
            return None

        summary_before_decoded = decoded_for_value(summary_before)
        summary_after_decoded = decoded_for_value(summary_after)

        # Cache the variable's type lookup to avoid repeated regex-based synthesis
        first_var_type = None
        resolved_value_type = None
        if layout and first.variable:
            first_var_type = layout.get_type(first.variable.type_id)
            if first.value_type:
                resolved_value_type = layout.get_type(first.value_type)
        response_type_label = (
            resolved_value_type.label
            if resolved_value_type
            else first.variable.label if first.variable else None
        )
        response_type_kind = (
            resolved_value_type.kind
            if resolved_value_type
            else first_var_type.kind if first_var_type else None
        )
        if resolved_value_type:
            response_value_type = clean_type_label(resolved_value_type.label)
        elif first.is_mapping and first.variable and layout:
            response_value_type = _get_final_value_type(first.variable, layout)
        else:
            response_value_type = (
                _clean_value_type(first.value_type) if first.value_type else None
            )

        # Build interim changes list
        interim_changes = [
            StorageChangeResponse(
                before=ValuePair(
                    value_encoded=c.old_value,
                    value_decoded=_preserve_large_ints(c.old_decoded.decoded if c.old_decoded else None),
                ),
                after=ValuePair(
                    value_encoded=c.new_value,
                    value_decoded=_preserve_large_ints(c.new_decoded.decoded if c.new_decoded else None),
                ),
                pc=c.pc,
                step=c.change_index,
                effect=c.effect,
                storage_address=normalized_storage_address,
                code_address=c.code_address,
                changed_value=c.changed_value,
                frame_outcome=c.frame_outcome,
                frame_id=c.frame_id,
                depth=c.depth,
                opcode=c.opcode,
                namespace=c.namespace,
            )
            for c in physical_changes
        ]

        # Check for packed storage (multiple variables in one slot)
        packed_fields: Optional[list[PackedFieldResponse]] = None
        struct_field: Optional[str] = None
        struct_definition: Optional[StructDefinitionResponse] = None

        if layout and first.variable:
            # Check if this is a static slot with multiple packed variables
            try:
                slot_int = int(slot, 16) if slot.startswith("0x") else int(slot)
                all_vars = layout.get_all_variables_in_slot(slot_int)

                if len(all_vars) > 1:
                    # Multiple variables packed in this slot - decode all of them
                    packed_fields = []

                    # Decode initial and final values for each packed variable
                    initial_bytes = bytes.fromhex(summary_before[2:]) if summary_before.startswith("0x") else bytes.fromhex(summary_before)
                    final_bytes = bytes.fromhex(summary_after[2:]) if summary_after.startswith("0x") else bytes.fromhex(summary_after)

                    initial_decoded = decoder.decode_packed_slot(initial_bytes, all_vars, layout.types)
                    final_decoded = decoder.decode_packed_slot(final_bytes, all_vars, layout.types)

                    for var in all_vars:
                        var_type = layout.get_type(var.type_id)
                        packed_fields.append(
                            PackedFieldResponse(
                                name=var.name,
                                type_label=clean_type_label(var_type.label if var_type else var.type_id),
                                offset=var.offset,
                                size=var.size,
                                before=ValuePairDecoded(
                                    value_decoded=_preserve_large_ints(initial_decoded[var.name].decoded if var.name in initial_decoded else None),
                                ),
                                after=ValuePairDecoded(
                                    value_decoded=_preserve_large_ints(final_decoded[var.name].decoded if var.name in final_decoded else None),
                                ),
                            )
                        )
            except (ValueError, AttributeError):
                pass

            # Check if this variable IS a struct (not a mapping to a struct)
            # This handles cases like `CurrentRateInfo currentRateInfo` where the variable itself is a struct
            if struct_definition is None:
                if first_var_type and first_var_type.members:
                    # This is a struct type - build struct_definition from its members
                    struct_name = first_var_type.label
                    if "." in struct_name:
                        struct_name = struct_name.rsplit(".", 1)[1]
                    if struct_name.startswith("struct "):
                        struct_name = struct_name[7:]

                    members = []
                    for member in first_var_type.members:
                        member_type = layout.get_type(member.type_id)
                        members.append(
                            StructMemberResponse(
                                name=member.name,
                                type_label=clean_type_label(member_type.label if member_type else member.type_id),
                                slot_offset=member.slot,
                                byte_offset=member.offset,
                                size=member.size,
                            )
                        )
                    struct_definition = StructDefinitionResponse(name=struct_name, members=members)

            # Extract struct field name from variable_path if present (e.g., "rewardData[0x...].lockStart")
            if first.variable_path and "." in first.variable_path:
                parts = first.variable_path.rsplit(".", 1)
                if len(parts) == 2:
                    struct_field = parts[1]
                    # Get the full struct definition
                    # For dynamic arrays, use element_type_id; for mappings, use _get_struct_definition
                    if first.element_type_id:
                        struct_definition = _get_struct_definition_from_type_id(first.element_type_id, layout)
                    else:
                        struct_definition = _get_struct_definition(first.variable, layout)

            # Handle mapping-to-struct base slots (e.g., accountData[addr] where AccountData is a struct)
            # This is when:
            # 1. It's a mapping (first.is_mapping is True)
            # 2. The value_type points to a struct
            # 3. The variable_path has no "." (it's the base slot, not a field access)
            # 4. We haven't already populated packed_fields (static slot check)
            if (
                first.is_mapping
                and first.value_type
                and first.variable_path
                and "." not in first.variable_path
                and packed_fields is None
            ):
                # Try to get the struct type from value_type
                struct_type = _get_struct_type_from_value_type(first.value_type, layout)
                if struct_type and struct_type.members:
                    # Find members in slot 0 of the struct (base slot)
                    slot_0_members = _get_struct_members_in_slot(struct_type, 0)
                    if len(slot_0_members) > 0:
                        # Decode packed struct members
                        packed_fields = []
                        initial_bytes = bytes.fromhex(summary_before[2:]) if summary_before.startswith("0x") else bytes.fromhex(summary_before)
                        final_bytes = bytes.fromhex(summary_after[2:]) if summary_after.startswith("0x") else bytes.fromhex(summary_after)

                        initial_decoded = decoder.decode_packed_slot(initial_bytes, slot_0_members, layout.types)
                        final_decoded = decoder.decode_packed_slot(final_bytes, slot_0_members, layout.types)

                        for member in slot_0_members:
                            member_type = layout.get_type(member.type_id)
                            packed_fields.append(
                                PackedFieldResponse(
                                    name=member.name,
                                    type_label=clean_type_label(member_type.label if member_type else member.type_id),
                                    offset=member.offset,
                                    size=member.size,
                                    before=ValuePairDecoded(
                                        value_decoded=_preserve_large_ints(initial_decoded[member.name].decoded if member.name in initial_decoded else None),
                                    ),
                                    after=ValuePairDecoded(
                                        value_decoded=_preserve_large_ints(final_decoded[member.name].decoded if member.name in final_decoded else None),
                                    ),
                                )
                            )

                        # Also set the struct definition for display
                        struct_definition = _get_struct_definition(first.variable, layout)

            # Handle dynamic array struct base slots (e.g., rewards[0] where RewardType is a struct)
            if (
                first.encoding == "dynamic_array"
                and first.element_type_id
                and first.variable_path
                and "." not in first.variable_path
                and packed_fields is None
            ):
                # Get struct type from element_type_id
                struct_type = layout.get_type(first.element_type_id) if layout else None
                if struct_type and struct_type.members:
                    # Find members in slot 0 of the struct (base slot)
                    slot_0_members = _get_struct_members_in_slot(struct_type, 0)
                    if len(slot_0_members) > 0:
                        # Decode packed struct members
                        packed_fields = []
                        initial_bytes = bytes.fromhex(summary_before[2:]) if summary_before.startswith("0x") else bytes.fromhex(summary_before)
                        final_bytes = bytes.fromhex(summary_after[2:]) if summary_after.startswith("0x") else bytes.fromhex(summary_after)

                        initial_decoded = decoder.decode_packed_slot(initial_bytes, slot_0_members, layout.types)
                        final_decoded = decoder.decode_packed_slot(final_bytes, slot_0_members, layout.types)

                        for member in slot_0_members:
                            member_type = layout.get_type(member.type_id)
                            packed_fields.append(
                                PackedFieldResponse(
                                    name=member.name,
                                    type_label=clean_type_label(member_type.label if member_type else member.type_id),
                                    offset=member.offset,
                                    size=member.size,
                                    before=ValuePairDecoded(
                                        value_decoded=_preserve_large_ints(initial_decoded[member.name].decoded if member.name in initial_decoded else None),
                                    ),
                                    after=ValuePairDecoded(
                                        value_decoded=_preserve_large_ints(final_decoded[member.name].decoded if member.name in final_decoded else None),
                                    ),
                                )
                            )

                        # Also set the struct definition
                        struct_definition = _get_struct_definition_from_type_id(first.element_type_id, layout)

            # Handle static struct variables (e.g., ExchangeRateInfo exchangeRateInfo)
            # This covers inline structs that are not mappings or dynamic arrays
            if (
                layout
                and first.variable
                and packed_fields is None
                and struct_definition is not None  # We detected this is a struct earlier
                and not first.is_mapping
                and first.encoding != "dynamic_array"
            ):
                if first_var_type and first_var_type.members:
                    # Calculate which slot offset within the struct this change represents
                    try:
                        current_slot = int(slot, 16) if slot.startswith("0x") else int(slot)
                        struct_slot_offset = current_slot - first.variable.slot

                        # Find members in this slot offset
                        slot_members = [m for m in first_var_type.members if m.slot == struct_slot_offset]

                        if len(slot_members) > 0:
                            packed_fields = []
                            initial_bytes = bytes.fromhex(summary_before[2:]) if summary_before.startswith("0x") else bytes.fromhex(summary_before)
                            final_bytes = bytes.fromhex(summary_after[2:]) if summary_after.startswith("0x") else bytes.fromhex(summary_after)

                            initial_decoded = decoder.decode_packed_slot(initial_bytes, slot_members, layout.types)
                            final_decoded = decoder.decode_packed_slot(final_bytes, slot_members, layout.types)

                            for member in slot_members:
                                member_type = layout.get_type(member.type_id)
                                packed_fields.append(
                                    PackedFieldResponse(
                                        name=member.name,
                                        type_label=clean_type_label(member_type.label if member_type else member.type_id),
                                        offset=member.offset,
                                        size=member.size,
                                        before=ValuePairDecoded(
                                            value_decoded=_preserve_large_ints(initial_decoded[member.name].decoded if member.name in initial_decoded else None),
                                        ),
                                        after=ValuePairDecoded(
                                            value_decoded=_preserve_large_ints(final_decoded[member.name].decoded if member.name in final_decoded else None),
                                        ),
                                    )
                                )
                    except (ValueError, AttributeError):
                        pass

        # Get mapping key - prefer explicit mapping_key, fallback to extraction from path
        mapping_key = first.mapping_key
        if not mapping_key and first.is_mapping and first.variable_path:
            mapping_key = _extract_keys_from_path(first.variable_path)

        # Build unified params from mapping key and types
        params = (
            _build_mapping_params(mapping_key, first.variable, layout)
            if mapping_key and first.variable
            else None
        )

        # A slot is compiler-declared only when the layout index proves it;
        # numeric magnitude is not storage provenance.
        try:
            slot_int = int(slot, 16) if slot.startswith("0x") else int(slot)
            layout_entry = LayoutIndex(layout).first_at(slot_int) if layout else None
            is_static_slot = layout_entry is not None
        except ValueError:
            is_static_slot = False
            layout_entry = None

        provenance = (
            first.variable.provenance
            if first.variable and first.variable.provenance != "compiler_layout"
            else "compiler_layout"
            if layout_entry and first.variable
            else "runtime_preimage"
            if first.variable
            else "raw"
        )
        confidence = first.variable.confidence if first.variable else "unknown"

        result.append(
            SlotChangeResponse(
                slot=slot,
                slot_decimal=str(int(slot, 16)) if slot.startswith("0x") else slot,
                is_static_slot=is_static_slot,
                provenance=provenance,
                confidence=confidence,
                namespace=first.namespace,
                net_changed=net_changed,
                classification=classification,
                first_write_step=(
                    physical_changes[0].change_index if physical_changes else None
                ),
                last_write_step=(
                    physical_changes[-1].change_index if physical_changes else None
                ),
                event_count=len(physical_changes),
                state_values_known=first.state_values_known,
                variable_name=first.variable.name if first.variable else None,
                variable_path=first.variable_path,
                resolved_paths=resolved_paths,
                type_label=normalize_contract_label(
                    response_type_label,
                    response_type_kind,
                ) if first.variable else None,
                params=params,
                mapping_base_slot=first.mapping_base_slot,
                is_mapping=first.is_mapping,
                is_dynamic_array=first.encoding == "dynamic_array",
                array_index=first.array_index,
                encoding=first.encoding,
                # Use the fully-unwrapped final value type for mappings
                value_type=response_value_type,
                # Summary values: before (initial) and after (final)
                before=ValuePair(
                    value_encoded=summary_before,
                    value_decoded=_preserve_large_ints(summary_before_decoded),
                ),
                after=ValuePair(
                    value_encoded=summary_after,
                    value_decoded=_preserve_large_ints(summary_after_decoded),
                ),
                # Packed storage fields
                packed_fields=packed_fields,
                struct_field=struct_field,
                struct_definition=struct_definition,
                changes=interim_changes,
            )
        )

    # Sort slots by the first change's execution order (step)
    # Step is the sequential execution index - this determines actual execution order
    # PC is just bytecode position which doesn't indicate when code ran
    def get_sort_key(x):
        if not x.changes:
            return (float('inf'), float('inf'))
        first_change = x.changes[0]
        step_val = first_change.step if first_change.step is not None else float('inf')
        return (step_val, first_change.pc or 0)

    result.sort(key=get_sort_key)

    return result

router = APIRouter(prefix="/api/slotscan/tx", tags=["transactions"])


def _history_counts(slots: list[SlotChangeResponse]) -> ContractHistoryCountsResponse:
    events = [event for slot in slots for event in slot.changes]
    classifications = [slot.classification for slot in slots]
    return ContractHistoryCountsResponse(
        slots_written=len(slots),
        sstore_events=len(events),
        net_changed_slots=classifications.count("net_changed"),
        restored_slots=classifications.count("restored"),
        reverted_only_slots=classifications.count("reverted_only"),
        noop_only_slots=classifications.count("noop_only"),
        reverted_writes=sum(
            event.frame_outcome == "reverted" for event in events
        ),
        noop_writes=sum(event.changed_value is False for event in events),
    )


def _empty_transaction_history(
    *,
    chain_id: int,
    tx_hash: str,
    receipt: dict,
    degraded_reason: str = "tracer_unavailable",
) -> TransactionStorageHistoryResponse:
    status_value = receipt.get("status", 1)
    status_int = int(status_value, 16) if isinstance(status_value, str) else int(status_value)
    block_value = receipt.get("blockNumber", 0)
    block_number = int(block_value, 16) if isinstance(block_value, str) else int(block_value)
    return TransactionStorageHistoryResponse(
        chain_id=chain_id,
        tx_hash=tx_hash.lower(),
        block_number=block_number,
        status="success" if status_int == 1 else "reverted",
        from_address=str(receipt.get("from")).lower() if receipt.get("from") else None,
        to_address=str(receipt.get("to")).lower() if receipt.get("to") else None,
        created_contract=(
            str(receipt.get("contractAddress")).lower()
            if receipt.get("contractAddress")
            else None
        ),
        capabilities=TransactionCapabilitiesResponse(
            write_history_complete=False,
            values_complete=False,
            rollback_classification_complete=False,
            execution_order_available=False,
            final_state_values_available=False,
            state_reconciliation_complete=False,
            address_attribution_complete=False,
            code_attribution_complete=False,
        ),
        summary=TransactionSummaryResponse(
            storage_owners=0,
            slots_written=0,
            sstore_events=0,
            net_changed_slots=0,
            restored_slots=0,
            reverted_only_slots=0,
            noop_only_slots=0,
            reverted_writes=0,
            noop_writes=0,
            resolved_slots=0,
        ),
        contracts=[],
        global_order=None,
        is_complete=False,
        trace_unavailable=True,
        degraded_reason=degraded_reason,
    )


async def _build_transaction_storage_history(
    chain_id: int,
    tx_hash: str,
    include_global_order: bool,
    history_service: TransactionHistoryService,
    receipt: dict,
) -> TransactionStorageHistoryResponse:
    try:
        analysis = await history_service.analyze(
            chain_id,
            tx_hash,
            receipt=receipt,
        )
    except TransactionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error": "Transaction not found", "code": "TX_NOT_FOUND"},
        )
    except TraceNotAvailableError as exc:
        degraded_reason = (
            "trace_limit"
            if any(
                marker in exc.reason.lower()
                for marker in ("limit", "exceed", "too large")
            )
            else "tracer_unavailable"
        )
        return _empty_transaction_history(
            chain_id=chain_id,
            tx_hash=tx_hash,
            receipt=receipt,
            degraded_reason=degraded_reason,
        )
    except RPCError:
        raise HTTPException(
            status_code=502,
            detail={"error": "Upstream RPC request failed", "code": "RPC_ERROR"},
        )

    artifact = analysis.artifact
    journal = analysis.journal
    contract_responses: list[ContractHistoryResponse] = []

    for projection in analysis.contracts:
        metadata = projection.metadata
        slots = _group_changes_by_slot(
            projection.diff.changes,
            projection.diff.layout,
            storage_address=projection.storage_address,
            layouts_by_code_address=projection.layouts_by_code_address,
        )
        counts = _history_counts(slots)
        resolved = sum(
            bool(slot.variable_path or slot.variable_name) for slot in slots
        )
        steps = [
            event.step
            for slot in slots
            for event in slot.changes
            if event.step is not None
        ]
        implementations = []
        if metadata and metadata.implementation_address:
            implementations.append(metadata.implementation_address)
        implementations.extend(
            address
            for address in projection.code_addresses
            if address.lower() != projection.storage_address.lower()
        )
        contract_responses.append(
            ContractHistoryResponse(
                storage_address=projection.storage_address,
                name=projection.display_name,
                is_proxy=metadata.is_proxy if metadata else False,
                is_verified=metadata.is_verified if metadata else False,
                layout_provenance=(
                    metadata.layout_provenance if metadata else None
                ),
                layout_source_address=(
                    metadata.layout_source_address if metadata else None
                ),
                implementation_addresses=list(dict.fromkeys(implementations)),
                code_addresses=list(projection.code_addresses),
                first_write_step=min(steps) if steps else None,
                last_write_step=max(steps) if steps else None,
                layout_available=bool(projection.layouts_by_code_address),
                resolution_status=projection.resolution_status,
                resolution=ContractResolutionResponse(
                    resolved=resolved,
                    total=len(slots),
                ),
                counts=counts,
                errors=list(projection.errors),
                slots=slots,
            )
        )

    all_slots = [slot for contract in contract_responses for slot in contract.slots]
    all_events = [event for slot in all_slots for event in slot.changes]
    classifications = [slot.classification for slot in all_slots]
    capabilities = artifact.capabilities
    persistent_event_count = sum(
        event.namespace.value == "persistent" for event in journal.events
    )
    response_complete = (
        capabilities.get("write_history_complete", False)
        and capabilities.get("address_attribution_complete", False)
        and capabilities.get("code_attribution_complete", False)
        and persistent_event_count <= history_service.settings.max_sstore_ops
    )

    global_order = None
    if include_global_order and journal.capabilities.execution_order:
        references: list[GlobalStorageEventReferenceResponse] = []
        ordinal = 0
        for contract in contract_responses:
            for slot in contract.slots:
                for event_index, event in enumerate(slot.changes):
                    references.append(
                        GlobalStorageEventReferenceResponse(
                            ordinal=ordinal,
                            step=event.step,
                            storage_address=contract.storage_address,
                            slot=slot.slot,
                            event_index=event_index,
                        )
                    )
                    ordinal += 1
        references.sort(
            key=lambda item: (
                item.step if item.step is not None else 2**63 - 1,
                item.ordinal,
            )
        )
        global_order = references

    return TransactionStorageHistoryResponse(
        chain_id=artifact.chain_id,
        tx_hash=artifact.tx_hash,
        block_number=artifact.block_number,
        status="success" if artifact.root_succeeded else "reverted",
        from_address=artifact.transaction_from,
        to_address=artifact.transaction_to,
        created_contract=artifact.created_contract,
        capabilities=TransactionCapabilitiesResponse(
            write_history_complete=capabilities.get(
                "write_history_complete", False
            ),
            values_complete=journal.capabilities.write_old_values,
            rollback_classification_complete=journal.capabilities.frame_outcomes,
            execution_order_available=journal.capabilities.execution_order,
            final_state_values_available=journal.capabilities.final_state_values,
            state_reconciliation_complete=(
                journal.capabilities.state_reconciliation
            ),
            address_attribution_complete=capabilities.get(
                "address_attribution_complete", False
            ),
            code_attribution_complete=capabilities.get(
                "code_attribution_complete", False
            ),
        ),
        summary=TransactionSummaryResponse(
            storage_owners=len(contract_responses),
            slots_written=len(all_slots),
            sstore_events=len(all_events),
            net_changed_slots=classifications.count("net_changed"),
            restored_slots=classifications.count("restored"),
            reverted_only_slots=classifications.count("reverted_only"),
            noop_only_slots=classifications.count("noop_only"),
            reverted_writes=sum(
                event.frame_outcome == "reverted" for event in all_events
            ),
            noop_writes=sum(event.changed_value is False for event in all_events),
            resolved_slots=sum(
                contract.resolution.resolved for contract in contract_responses
            ),
        ),
        contracts=contract_responses,
        global_order=global_order,
        is_complete=response_complete,
        trace_unavailable=False,
        degraded_reason=capabilities.get("degraded_reason"),
    )


def _is_response_cacheable(
    response: TransactionStorageHistoryResponse,
) -> bool:
    return (
        response.is_complete
        and not response.trace_unavailable
        and response.degraded_reason is None
        and all(
            contract.resolution_status == "resolved"
            and contract.is_verified
            and contract.layout_available
            and not contract.errors
            for contract in response.contracts
        )
    )


def _serialized_response(
    response: TransactionStorageHistoryResponse,
) -> bytes:
    return response.model_dump_json().encode()


@router.get(
    "/{chain_id}/{tx_hash}",
    response_model=TransactionStorageHistoryResponse,
)
async def get_transaction_storage_history(
    chain_id: int,
    tx_hash: str,
    include_global_order: bool = False,
    history_service: TransactionHistoryService = Depends(
        get_transaction_history_service
    ),
    response_cache: TransactionResponseCache = Depends(
        get_transaction_response_cache
    ),
):
    """Analyze persistent writes across every storage owner in a transaction."""
    if not re.fullmatch(r"0x[a-fA-F0-9]{64}", tx_hash):
        raise HTTPException(
            status_code=400,
            detail={"error": "Invalid transaction hash", "code": "INVALID_TX_HASH"},
        )

    try:
        receipt = await history_service.tracer.rpc_client.get_receipt(
            chain_id,
            tx_hash,
        )
        receipt_identity = ReceiptIdentity.from_receipt(receipt)
    except TransactionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error": "Transaction not found", "code": "TX_NOT_FOUND"},
        )
    except RPCError:
        raise HTTPException(
            status_code=502,
            detail={"error": "Upstream RPC request failed", "code": "RPC_ERROR"},
        )

    key = TransactionResponseKey(
        chain_id=chain_id,
        tx_hash=tx_hash.lower(),
        receipt=receipt_identity,
        include_global_order=include_global_order,
    )
    cached = response_cache.get(key)
    if cached is not None:
        return Response(content=cached, media_type="application/json")

    async with response_cache.hold(key):
        cached = response_cache.peek(key)
        if cached is not None:
            response_cache.coalesced_hits += 1
            return Response(content=cached, media_type="application/json")

        response = await _build_transaction_storage_history(
            chain_id=chain_id,
            tx_hash=tx_hash,
            include_global_order=include_global_order,
            history_service=history_service,
            receipt=receipt,
        )
        if not _is_response_cacheable(response):
            return response

        body = _serialized_response(response)
        response_cache.put(key, body)
        return Response(content=body, media_type="application/json")
