"""Transaction API routes."""

from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import (
    get_contract_resolver,
    get_layout_parser,
    get_transaction_tracer,
)
from app.models.api import (
    MappingParamResponse,
    PackedFieldResponse,
    SlotChangeResponse,
    StorageChangeResponse,
    StructDefinitionResponse,
    StructMemberResponse,
    TransactionDiffResponse,
)
from app.models.domain import StorageChange, StorageLayout
from app.models.errors import (
    NotAContractError,
    RPCError,
    TraceNotAvailableError,
    TransactionNotFoundError,
)
from app.services.decoder import TypeDecoder
from app.services.layout import LayoutParser
from app.services.resolver import ContractResolver
from app.services.tracer import TransactionTracer


import re


def _strip_type_prefix(label: str) -> str:
    """Strip 't_' prefix from Solidity type identifiers for display."""
    if label and label.startswith("t_"):
        return label[2:]
    return label


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
    from app.models.domain import StorageVariable

    if not layout or not variable:
        return []

    key_types = []
    var_type = layout.get_type(variable.type_id)

    while var_type and var_type.encoding == "mapping":
        if var_type.key_type:
            key_types.append(_strip_type_prefix(var_type.key_type))
        if var_type.value_type:
            var_type = layout.get_type(var_type.value_type)
        else:
            break

    return key_types


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
        params.append(MappingParamResponse(type=param_type, value=key))

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

    return _strip_type_prefix(cleaned)


def _get_struct_definition(
    variable: "StorageVariable",
    layout: StorageLayout,
) -> Optional[StructDefinitionResponse]:
    """Get the struct definition for a mapping that points to a struct."""
    from app.models.domain import StorageVariable

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
                        type_label=_strip_type_prefix(member_type.label if member_type else member.type_id),
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
    from app.models.domain import StorageType

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
                type_label=_strip_type_prefix(member_type.label if member_type else member.type_id),
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
    from app.models.domain import StorageVariable

    if not struct_type.members:
        return []

    # Find members in this slot offset
    return [m for m in struct_type.members if m.slot == slot_offset]


def _group_changes_by_slot(
    changes: list[StorageChange],
    layout: Optional[StorageLayout] = None,
) -> list[SlotChangeResponse]:
    """Group storage changes by slot, preserving execution order."""
    if not changes:
        return []

    decoder = TypeDecoder()

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

        # Build interim changes list
        interim_changes = [
            StorageChangeResponse(
                old_raw=c.old_value,
                new_raw=c.new_value,
                old_decoded=c.old_decoded.decoded if c.old_decoded else None,
                new_decoded=c.new_decoded.decoded if c.new_decoded else None,
                old_display=c.old_decoded.display if c.old_decoded else None,
                new_display=c.new_decoded.display if c.new_decoded else None,
                pc=c.pc,
                step=c.change_index,
            )
            for c in slot_change_list
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
                    initial_bytes = bytes.fromhex(first.old_value[2:]) if first.old_value.startswith("0x") else bytes.fromhex(first.old_value)
                    final_bytes = bytes.fromhex(last.new_value[2:]) if last.new_value.startswith("0x") else bytes.fromhex(last.new_value)

                    initial_decoded = decoder.decode_packed_slot(initial_bytes, all_vars, layout.types)
                    final_decoded = decoder.decode_packed_slot(final_bytes, all_vars, layout.types)

                    for var in all_vars:
                        var_type = layout.get_type(var.type_id)
                        packed_fields.append(
                            PackedFieldResponse(
                                name=var.name,
                                type_label=_strip_type_prefix(var_type.label if var_type else var.type_id),
                                offset=var.offset,
                                size=var.size,
                                initial_decoded=initial_decoded[var.name].decoded if var.name in initial_decoded else None,
                                initial_display=initial_decoded[var.name].display if var.name in initial_decoded else None,
                                final_decoded=final_decoded[var.name].decoded if var.name in final_decoded else None,
                                final_display=final_decoded[var.name].display if var.name in final_decoded else None,
                            )
                        )
            except (ValueError, AttributeError):
                pass

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
                        initial_bytes = bytes.fromhex(first.old_value[2:]) if first.old_value.startswith("0x") else bytes.fromhex(first.old_value)
                        final_bytes = bytes.fromhex(last.new_value[2:]) if last.new_value.startswith("0x") else bytes.fromhex(last.new_value)

                        initial_decoded = decoder.decode_packed_slot(initial_bytes, slot_0_members, layout.types)
                        final_decoded = decoder.decode_packed_slot(final_bytes, slot_0_members, layout.types)

                        for member in slot_0_members:
                            member_type = layout.get_type(member.type_id)
                            packed_fields.append(
                                PackedFieldResponse(
                                    name=member.name,
                                    type_label=_strip_type_prefix(member_type.label if member_type else member.type_id),
                                    offset=member.offset,
                                    size=member.size,
                                    initial_decoded=initial_decoded[member.name].decoded if member.name in initial_decoded else None,
                                    initial_display=initial_decoded[member.name].display if member.name in initial_decoded else None,
                                    final_decoded=final_decoded[member.name].decoded if member.name in final_decoded else None,
                                    final_display=final_decoded[member.name].display if member.name in final_decoded else None,
                                )
                            )

                        # Also set the struct definition for display
                        struct_definition = _get_struct_definition(first.variable, layout)

        # Get mapping key - prefer explicit mapping_key, fallback to extraction from path
        mapping_key = first.mapping_key
        if not mapping_key and first.is_mapping and first.variable_path:
            mapping_key = _extract_keys_from_path(first.variable_path)

        # Build unified params from mapping key and types
        params = _build_mapping_params(mapping_key, first.variable, layout) if mapping_key else None

        result.append(
            SlotChangeResponse(
                slot=slot,
                slot_decimal=str(int(slot, 16)) if slot.startswith("0x") else slot,
                variable_name=first.variable.name if first.variable else None,
                variable_path=first.variable_path,
                type_label=_strip_type_prefix(first.variable.label) if first.variable else None,
                params=params,
                mapping_base_slot=first.mapping_base_slot,
                is_mapping=first.is_mapping,
                encoding=first.encoding,
                value_type=_clean_value_type(first.value_type) if first.value_type else None,
                # Summary values: initial (before first change) and final (after last change)
                initial_raw=first.old_value,
                final_raw=last.new_value,
                initial_decoded=first.old_decoded.decoded if first.old_decoded else None,
                final_decoded=last.new_decoded.decoded if last.new_decoded else None,
                initial_display=first.old_decoded.display if first.old_decoded else None,
                final_display=last.new_decoded.display if last.new_decoded else None,
                # Packed storage fields
                packed_fields=packed_fields,
                struct_field=struct_field,
                struct_definition=struct_definition,
                changes=interim_changes,
            )
        )

    # Sort slots by the first change's execution order
    result.sort(key=lambda x: x.changes[0].step if x.changes else 0)

    return result

router = APIRouter(prefix="/api/tx", tags=["transactions"])


@router.get("/{chain_id}/{address}/{tx_hash}", response_model=TransactionDiffResponse)
async def get_tx_diff(
    chain_id: int,
    address: str,
    tx_hash: str,
    resolver: ContractResolver = Depends(get_contract_resolver),
    layout_parser: LayoutParser = Depends(get_layout_parser),
    tracer: TransactionTracer = Depends(get_transaction_tracer),
):
    """
    Get storage changes for a contract in a transaction.

    Returns all SSTORE operations that modified the contract's storage,
    with before/after values decoded if contract is verified.
    """
    # Validate tx_hash format
    if not tx_hash.startswith("0x") or len(tx_hash) != 66:
        raise HTTPException(
            status_code=400,
            detail={"error": "Invalid transaction hash", "code": "INVALID_TX_HASH"},
        )

    # Resolve contract
    try:
        metadata = await resolver.resolve(chain_id, address)
    except NotAContractError:
        raise HTTPException(
            status_code=404,
            detail={"error": "Not a contract", "code": "NOT_CONTRACT"},
        )
    except RPCError as e:
        raise HTTPException(
            status_code=502,
            detail={"error": str(e), "code": "RPC_ERROR"},
        )

    # Get layout
    layout = metadata.storage_layout
    if layout and isinstance(layout, dict):
        try:
            layout = StorageLayout.from_dict(layout)
        except Exception:
            layout = None

    if not layout and metadata.is_verified and metadata.sources and metadata.name:
        try:
            layout = await layout_parser.parse(
                contract_name=metadata.name,
                sources=metadata.sources,
                compiler_version=metadata.compiler_version or "0.8.19",
                compiler_settings=metadata.compiler_settings,
                metadata_settings=metadata.compiler_settings,
            )
            metadata.storage_layout = layout
            if resolver.contract_repo:
                await resolver.contract_repo.save(metadata)
        except Exception:
            layout = None

    # Trace transaction
    try:
        diff = await tracer.trace_transaction(
            chain_id=chain_id,
            contract_address=address,
            tx_hash=tx_hash,
            layout=layout,
        )
    except TransactionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error": "Transaction not found", "code": "TX_NOT_FOUND"},
        )
    except TraceNotAvailableError:
        # Return degraded response with warning
        return TransactionDiffResponse(
            chain_id=chain_id,
            address=address,
            tx_hash=tx_hash,
            block_number=0,
            slots=[],
            is_complete=False,
            is_verified=layout is not None,
            trace_unavailable=True,
        )
    except RPCError as e:
        raise HTTPException(
            status_code=502,
            detail={"error": str(e), "code": "RPC_ERROR"},
        )

    # Group changes by slot
    grouped_slots = _group_changes_by_slot(diff.changes, layout)

    return TransactionDiffResponse(
        chain_id=diff.chain_id,
        address=diff.contract_address,
        tx_hash=diff.tx_hash,
        block_number=diff.block_number,
        slots=grouped_slots,
        is_complete=diff.is_complete,
        is_verified=layout is not None,
        trace_unavailable=diff.trace_unavailable,
        contract_name=metadata.name,
        layout_available=layout is not None,
    )
