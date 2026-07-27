"""Deterministic compiled-layout scalar planning and strict word reads."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.errors import RPCError
from app.services.compiled_layout import (
    CompiledDeclaration,
    CompiledLayout,
    CompiledType,
)
from app.services.web3_provider import Web3Provider


@dataclass(frozen=True)
class CompiledScalarProjection:
    """One compiled-layout value or explicit non-eager status."""

    declaration: CompiledDeclaration
    path: str
    slot: int
    byte_offset: int
    byte_size: int
    type_info: CompiledType
    status: str


@dataclass(frozen=True)
class CompiledScalarReadPlan:
    """Bounded initial storage-view work."""

    projections: tuple[CompiledScalarProjection, ...]
    words: tuple[int, ...]


def is_one_word_scalar(type_info: CompiledType | None) -> bool:
    """Return whether a compiled type can be decoded from one storage word."""
    return (
        type_info is not None
        and type_info.encoding == "inplace"
        and type_info.kind in {"value", "contract", "enum"}
        and type_info.array_length is None
        and not type_info.members
        and type_info.num_bytes is not None
        and 0 < type_info.num_bytes <= 32
    )


def is_solidity_dynamic_bytes(
    layout: CompiledLayout,
    type_info: CompiledType | None,
) -> bool:
    """Return whether a type uses Solidity's short/long bytes encoding."""
    return (
        type_info is not None
        and layout.storage_rules.array_storage_scheme == "solidity"
        and type_info.encoding == "bytes"
        and type_info.kind == "value"
        and type_info.num_bytes == 32
        and not type_info.members
        and type_info.label.lower() in {"bytes", "string"}
    )


def is_materializable_storage_type(
    layout: CompiledLayout,
    type_info: CompiledType | None,
    *,
    stack: tuple[str, ...] = (),
) -> bool:
    """Return whether a bounded query can fully materialize a terminal type."""
    if is_one_word_scalar(type_info) or is_solidity_dynamic_bytes(layout, type_info):
        return True
    if (
        type_info is None
        or type_info.kind != "struct"
        or type_info.encoding != "inplace"
        or not type_info.members
        or type_info.num_bytes is None
        or type_info.id in stack
    ):
        return False

    next_stack = stack + (type_info.id,)
    occupied_ranges: list[tuple[int, int]] = []
    struct_words = (type_info.num_bytes + 31) // 32
    for member in type_info.members:
        member_type = layout.get_type(member.type_id)
        if (
            member_type is None
            or member_type.num_bytes is None
            or member.byte_size != member_type.num_bytes
        ):
            return False
        if member_type.kind == "struct" and member.byte_offset != 0:
            return False
        start = member.slot * 32 + member.byte_offset
        end = start + member.byte_size
        if (
            end > struct_words * 32
            or any(
                start < occupied_end and end > occupied_start
                for occupied_start, occupied_end in occupied_ranges
            )
        ):
            return False
        occupied_ranges.append((start, end))
        if not is_materializable_storage_type(
            layout,
            member_type,
            stack=next_stack,
        ):
            return False
    return True


def is_queryable_storage_type(
    layout: CompiledLayout,
    type_info: CompiledType,
) -> bool:
    """Return whether the typed-query endpoint supports this aggregate."""
    current = type_info
    visited: set[str] = set()
    while current.encoding == "mapping" or current.kind == "array":
        if current.id in visited:
            return False
        visited.add(current.id)

        if current.encoding == "mapping":
            next_type_id = current.value_type
        else:
            if (
                current.encoding == "dynamic_array"
                and layout.storage_rules.array_storage_scheme
                == "vyper_legacy_hashed"
            ):
                return False
            next_type_id = current.element_type

        next_type = layout.get_type(next_type_id) if next_type_id else None
        if next_type is None:
            return False
        current = next_type

    if layout.storage_rules.array_storage_scheme == "vyper_legacy_hashed":
        return (
            is_one_word_scalar(current)
            or (
                current.kind == "struct"
                and current.num_bytes is not None
                and current.num_bytes <= 32
                and is_materializable_storage_type(layout, current)
            )
        )
    return is_materializable_storage_type(layout, current)


def plan_compiled_scalar_reads(
    layout: CompiledLayout,
    *,
    max_words: int = 256,
) -> CompiledScalarReadPlan:
    """Plan direct, packed, and statically known struct-leaf scalars."""
    if max_words < 0:
        raise ValueError("max_words cannot be negative")

    projections: list[CompiledScalarProjection] = []

    def walk(
        declaration: CompiledDeclaration,
        type_id: str,
        path: str,
        slot: int,
        byte_offset: int,
        byte_size: int,
    ) -> None:
        type_info = layout.get_type(type_id)
        if type_info is None:
            return

        if (
            type_info.encoding == "inplace"
            and type_info.kind in {"value", "contract", "enum"}
            and type_info.array_length is None
            and not type_info.members
            and type_info.num_bytes is not None
            and 0 < type_info.num_bytes <= 32
        ):
            projections.append(
                CompiledScalarProjection(
                    declaration=declaration,
                    path=path,
                    slot=slot,
                    byte_offset=byte_offset,
                    byte_size=type_info.num_bytes,
                    type_info=type_info,
                    status="pending",
                )
            )
            return

        if is_solidity_dynamic_bytes(layout, type_info):
            projections.append(
                CompiledScalarProjection(
                    declaration=declaration,
                    path=path,
                    slot=slot,
                    byte_offset=byte_offset,
                    byte_size=byte_size,
                    type_info=type_info,
                    status="pending_dynamic",
                )
            )
            return

        if (
            type_info.kind == "struct"
            and type_info.encoding == "inplace"
            and type_info.members
            and layout.storage_rules.array_storage_scheme != "vyper_legacy_hashed"
        ):
            for member in type_info.members:
                walk(
                    declaration,
                    member.type_id,
                    f"{path}.{member.name}",
                    slot + member.slot,
                    member.byte_offset,
                    member.byte_size,
                )
            return

        status = (
            "on_demand"
            if is_queryable_storage_type(layout, type_info)
            else "unsupported"
        )
        projections.append(
            CompiledScalarProjection(
                declaration=declaration,
                path=path,
                slot=slot,
                byte_offset=byte_offset,
                byte_size=byte_size,
                type_info=type_info,
                status=status,
            )
        )

    for declaration in layout.variables:
        walk(
            declaration,
            declaration.type_id,
            declaration.name,
            declaration.slot,
            declaration.byte_offset,
            declaration.byte_size,
        )

    words: list[int] = []
    admitted: set[int] = set()
    bounded: list[CompiledScalarProjection] = []
    for projection in projections:
        if projection.status not in {"pending", "pending_dynamic"}:
            bounded.append(projection)
            continue
        if projection.slot not in admitted:
            if len(words) >= max_words:
                bounded.append(
                    CompiledScalarProjection(
                        declaration=projection.declaration,
                        path=projection.path,
                        slot=projection.slot,
                        byte_offset=projection.byte_offset,
                        byte_size=projection.byte_size,
                        type_info=projection.type_info,
                        status="deferred_budget",
                    )
                )
                continue
            admitted.add(projection.slot)
            words.append(projection.slot)
        bounded.append(projection)

    return CompiledScalarReadPlan(
        projections=tuple(bounded),
        words=tuple(words),
    )


def _validate_word(slot: int, value: object) -> str:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise RPCError("eth_getStorageValues", f"Slot {slot}: invalid storage word")
    try:
        raw = bytes.fromhex(value[2:])
    except ValueError as exc:
        raise RPCError(
            "eth_getStorageValues",
            f"Slot {slot}: invalid hexadecimal storage word",
        ) from exc
    if len(raw) != 32:
        raise RPCError(
            "eth_getStorageValues",
            f"Slot {slot}: expected 32 bytes, received {len(raw)}",
        )
    return "0x" + raw.hex()


class StorageReader:
    """Read strict, complete storage-word sets without fallback."""

    def __init__(self, web3_provider: Web3Provider):
        self.web3_provider = web3_provider

    async def read_slots(
        self,
        chain_id: int,
        address: str,
        slots: list[int],
        block_number: int | str,
    ) -> dict[int, str]:
        """Read first-seen unique words and reject incomplete results."""
        if not slots:
            return {}

        unique_slots = list(dict.fromkeys(slots))
        try:
            values = await self.web3_provider.get_storage_values(
                chain_id,
                address,
                unique_slots,
                block_number,
            )
        except Exception as exc:
            raise RPCError("eth_getStorageValues", str(exc)) from exc

        if set(values) != set(unique_slots) or len(values) != len(unique_slots):
            raise RPCError(
                "eth_getStorageValues",
                "Response did not contain the complete requested word set",
            )
        return {slot: _validate_word(slot, values[slot]) for slot in unique_slots}
