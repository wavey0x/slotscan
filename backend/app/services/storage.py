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


def is_queryable_storage_type(
    layout: CompiledLayout,
    type_info: CompiledType,
) -> bool:
    """Return whether the typed-query endpoint supports this aggregate."""
    if type_info.encoding == "mapping":
        current = type_info
        visited: set[str] = set()
        while current.encoding == "mapping":
            if (
                current.id in visited
                or not current.key_type
                or not current.value_type
            ):
                return False
            visited.add(current.id)
            next_type = layout.get_type(current.value_type)
            if next_type is None:
                return False
            current = next_type
        return is_one_word_scalar(current)

    if type_info.kind == "array":
        if (
            type_info.encoding == "dynamic_array"
            and layout.storage_rules.array_storage_scheme == "vyper_legacy_hashed"
        ):
            return False
        element = (
            layout.get_type(type_info.element_type)
            if type_info.element_type
            else None
        )
        return is_one_word_scalar(element)

    return False


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
        if projection.status != "pending":
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
        raise RPCError("eth_getStorageAt", f"Slot {slot}: invalid storage word")
    try:
        raw = bytes.fromhex(value[2:])
    except ValueError as exc:
        raise RPCError(
            "eth_getStorageAt",
            f"Slot {slot}: invalid hexadecimal storage word",
        ) from exc
    if len(raw) != 32:
        raise RPCError(
            "eth_getStorageAt",
            f"Slot {slot}: expected 32 bytes, received {len(raw)}",
        )
    return "0x" + raw.hex()


class StorageReader:
    """Read strict, complete storage-word sets without fallback."""

    def __init__(self, web3_provider: Web3Provider):
        self.web3_provider = web3_provider

    async def read_slots_batch(
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
            values = await self.web3_provider.batch_get_storage_at(
                chain_id,
                address,
                unique_slots,
                block_number,
                batch_size=100,
            )
        except Exception as exc:
            raise RPCError("eth_getStorageAt", str(exc)) from exc

        if set(values) != set(unique_slots) or len(values) != len(unique_slots):
            raise RPCError(
                "eth_getStorageAt",
                "Batch response did not contain the complete requested word set",
            )
        return {slot: _validate_word(slot, values[slot]) for slot in unique_slots}
