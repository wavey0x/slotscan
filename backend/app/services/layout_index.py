"""Immutable, exact lookup primitives derived from compiler storage layouts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import ceil

from app.models.domain import StorageLayout, StorageType, StorageVariable
from app.utils.vyper import LEGACY_HASHED_STORAGE


class StorageNamespace(str, Enum):
    PERSISTENT = "persistent"
    TRANSIENT = "transient"


class ResolutionProvenance(str, Enum):
    COMPILER_LAYOUT = "compiler_layout"
    RUNTIME_PREIMAGE = "runtime_preimage"
    TRANSIENT_LAYOUT = "transient_layout"
    ERC7201_ANNOTATION = "erc7201_annotation"
    SOURCE_INFERENCE = "source_inference"
    HEURISTIC = "heuristic"
    RAW = "raw"


class ResolutionConfidence(str, Enum):
    EXACT = "exact"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class StorageLocation:
    """An exact word location plus a byte range within that word."""

    slot: int
    byte_offset: int = 0
    byte_size: int = 32
    namespace: StorageNamespace = StorageNamespace.PERSISTENT


@dataclass(frozen=True)
class ArrayPacking:
    """How array elements are placed in storage words."""

    element_size: int
    elements_per_slot: int
    slots_per_element: int

    @property
    def is_packed(self) -> bool:
        return self.elements_per_slot > 1

    def slot_count(self, length: int) -> int:
        if length < 0:
            raise ValueError("Array length cannot be negative")
        if self.is_packed:
            return ceil(length / self.elements_per_slot)
        return length * self.slots_per_element

    def location(self, data_start: int, index: int) -> StorageLocation:
        if index < 0:
            raise ValueError("Array index cannot be negative")
        if self.is_packed:
            return StorageLocation(
                slot=data_start + index // self.elements_per_slot,
                byte_offset=(index % self.elements_per_slot) * self.element_size,
                byte_size=self.element_size,
            )
        return StorageLocation(
            slot=data_start + index * self.slots_per_element,
            byte_offset=0,
            byte_size=min(self.element_size, 32),
        )

    def locations_in_slot(
        self,
        data_start: int,
        slot: int,
        *,
        length: int | None = None,
    ) -> tuple[tuple[int, StorageLocation], ...]:
        """Return every array element represented by ``slot``.

        For multi-slot elements this returns the owning element and the word's
        offset is represented by the difference from its first location.
        """
        relative_slot = slot - data_start
        if relative_slot < 0:
            return ()

        if self.is_packed:
            first_index = relative_slot * self.elements_per_slot
            result = []
            for index in range(first_index, first_index + self.elements_per_slot):
                if length is not None and index >= length:
                    break
                result.append((index, self.location(data_start, index)))
            return tuple(result)

        index = relative_slot // self.slots_per_element
        if length is not None and index >= length:
            return ()
        return ((index, self.location(data_start, index)),)


def array_packing(element_type: StorageType | None) -> ArrayPacking:
    """Derive Solidity/Vyper array packing without slot-count heuristics."""
    if element_type is None:
        return ArrayPacking(element_size=32, elements_per_slot=1, slots_per_element=1)

    element_size = element_type.num_bytes or 32
    packs_as_value = element_type.kind in {"value", "contract", "enum"}
    if packs_as_value and 0 < element_size < 32:
        return ArrayPacking(
            element_size=element_size,
            elements_per_slot=32 // element_size,
            slots_per_element=1,
        )

    return ArrayPacking(
        element_size=element_size,
        elements_per_slot=1,
        slots_per_element=max(1, ceil(element_size / 32)),
    )


@dataclass(frozen=True)
class IndexedVariable:
    variable: StorageVariable
    type_info: StorageType
    start_slot: int
    end_slot: int
    array_packing: ArrayPacking | None = None


class LayoutIndex:
    """Immutable slot-range index for direct compiler-declared locations."""

    def __init__(self, layout: StorageLayout):
        entries: list[IndexedVariable] = []
        for variable in layout.variables:
            type_info = layout.get_type(variable.type_id)
            if type_info is None:
                continue

            packing = None
            if layout.storage_scheme == LEGACY_HASHED_STORAGE:
                # Pre-0.2.13 Vyper assigns one top-level salt slot to every
                # declaration and hashes each composite descent.
                slot_count = 1
            elif (
                type_info.encoding == "inplace"
                and type_info.array_length is not None
                and type_info.element_type
                and type_info.element_type.lower() not in {"string", "bytes"}
            ):
                packing = array_packing(layout.get_type(type_info.element_type))
                slot_count = packing.slot_count(type_info.array_length)
            elif type_info.encoding in {"mapping", "dynamic_array"}:
                slot_count = 1
            else:
                slot_count = max(1, ceil((variable.size or type_info.num_bytes or 32) / 32))

            entries.append(
                IndexedVariable(
                    variable=variable,
                    type_info=type_info,
                    start_slot=variable.slot,
                    end_slot=variable.slot + slot_count,
                    array_packing=packing,
                )
            )

        self._entries = tuple(entries)

    def variables_at(self, slot: int) -> tuple[IndexedVariable, ...]:
        return tuple(entry for entry in self._entries if entry.start_slot <= slot < entry.end_slot)

    def first_at(self, slot: int) -> IndexedVariable | None:
        return next(iter(self.variables_at(slot)), None)
