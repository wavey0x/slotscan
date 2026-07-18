"""Normalize compiled layouts into bounded recursive physical shapes."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
import re

from app.services.compiled_layout import (
    CompiledDeclaration,
    CompiledLayout,
    CompiledScope,
    CompiledType,
)
from app.services.layout_compatibility.models import (
    ComparisonLocation,
    ComparisonRegion,
    ComparisonScope,
    ComparisonType,
)


class LayoutNormalizationUnavailable(ValueError):
    """Exact normalization could not produce a complete bounded result."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ShapeMember:
    name: str
    slot: int
    byte_offset: int
    byte_size: int
    label: str
    shape: "PhysicalShape"


@dataclass(frozen=True)
class PhysicalShape:
    kind: str
    encoding: str
    byte_size: int
    label: str
    key: "PhysicalShape | None" = None
    value: "PhysicalShape | None" = None
    element: "PhysicalShape | None" = None
    array_length: int | None = None
    element_stride: int | None = None
    elements_per_slot: int | None = None
    members: tuple[ShapeMember, ...] = ()
    recursive: bool = False
    recursive_depth: int | None = None

    def physical_key(self) -> tuple:
        if self.recursive:
            return ("recursive", self.recursive_depth)
        if self.kind == "mapping":
            return (
                self.kind,
                self.encoding,
                self.byte_size,
                self.key.mapping_key_key() if self.key else None,
                self.value.physical_key() if self.value else None,
            )
        if (
            self.encoding == "inplace"
            and self.key is None
            and self.value is None
            and self.element is None
            and not self.members
        ):
            # Contract/interface references, addresses, enums, user-defined
            # value types, and their underlying scalar types can be nominally
            # different while occupying the same physical bytes.
            return ("scalar", self.encoding, self.byte_size)
        return (
            self.kind,
            self.encoding,
            self.byte_size,
            self.key.physical_key() if self.key else None,
            self.value.physical_key() if self.value else None,
            self.element.physical_key() if self.element else None,
            self.array_length,
            self.element_stride,
            self.elements_per_slot,
            tuple(
                (
                    member.slot,
                    member.byte_offset,
                    member.byte_size,
                    member.shape.physical_key(),
                )
                for member in self.members
            ),
        )

    def nominal_key(self) -> tuple:
        """Return the bounded recursive shape including names and type labels."""
        if self.recursive:
            return (
                "recursive",
                self.recursive_depth,
                self.kind,
                self.encoding,
                self.byte_size,
                self.label,
            )
        return (
            self.kind,
            self.encoding,
            self.byte_size,
            self.label,
            self.key.nominal_key() if self.key else None,
            self.value.nominal_key() if self.value else None,
            self.element.nominal_key() if self.element else None,
            self.array_length,
            self.element_stride,
            self.elements_per_slot,
            tuple(
                (
                    member.name,
                    member.slot,
                    member.byte_offset,
                    member.byte_size,
                    member.shape.nominal_key(),
                )
                for member in self.members
            ),
        )

    def mapping_key_key(self) -> tuple:
        """Return the preimage-encoding shape of a Solidity mapping key."""
        if self.encoding == "bytes":
            return ("raw",)
        if self.encoding == "inplace" and re.fullmatch(
            r"bytes(?:[1-9]|[12][0-9]|3[0-2])",
            self.label.strip(),
        ):
            return ("right_padded_word", self.byte_size)
        if self.encoding == "inplace":
            return ("left_padded_word",)
        return self.physical_key()


@dataclass(frozen=True)
class NormalizedRegion:
    report: ComparisonRegion
    shape: PhysicalShape

    @property
    def start(self) -> tuple[int, int]:
        return self.report.location.slot, self.report.location.byte_offset

    @property
    def end_slot(self) -> int:
        return self.report.location.end_slot


@dataclass(frozen=True)
class NormalizedScope:
    report: ComparisonScope
    regions: tuple[NormalizedRegion, ...]


@dataclass(frozen=True)
class NormalizedLayout:
    scopes: tuple[NormalizedScope, ...]


class LayoutNormalizer:
    """Convert exact Solidity declarations to comparison-only physical shapes."""

    def __init__(
        self,
        *,
        max_depth: int = 64,
        max_visited_types: int = 4096,
    ):
        self.max_depth = max_depth
        self.max_visited_types = max_visited_types
        self._visits = 0

    @staticmethod
    def exact_limitation(layout: CompiledLayout) -> str | None:
        if (layout.language or "").lower() != "solidity":
            return "unsupported_language"
        if layout.storage_rules.mapping_preimage_order != "key_then_slot":
            return "unsupported_storage_rules"
        if layout.storage_rules.array_storage_scheme != "solidity":
            return "unsupported_storage_rules"
        if any(
            scope.kind not in {"default", "erc7201"}
            or scope.provenance != "compiler_layout"
            or scope.confidence != "exact"
            for scope in layout.scopes
        ):
            return "non_exact_layout"
        if any(
            declaration.provenance != "compiler_layout"
            or declaration.confidence != "exact"
            for declaration in layout.variables
        ):
            return "non_exact_layout"
        return None

    def normalize(self, layout: CompiledLayout) -> NormalizedLayout:
        limitation = self.exact_limitation(layout)
        if limitation:
            raise LayoutNormalizationUnavailable(limitation)
        self._visits = 0
        scopes = []
        for scope in layout.scopes:
            regions = tuple(
                sorted(
                    (
                        self._region(layout, scope, declaration)
                        for declaration in layout.variables
                        if declaration.scope_id == scope.id
                    ),
                    key=lambda region: (
                        region.report.location.slot,
                        region.report.location.byte_offset,
                        region.report.path,
                    ),
                )
            )
            if scope.kind == "erc7201" and any(
                region.report.location.slot < scope.root_slot
                for region in regions
            ):
                raise LayoutNormalizationUnavailable("invalid_layout")
            for previous, current in zip(regions, regions[1:]):
                if self._regions_overlap(previous, current):
                    raise LayoutNormalizationUnavailable("invalid_layout")
            scopes.append(
                NormalizedScope(
                    report=self._scope_report(scope),
                    regions=regions,
                )
            )
        return NormalizedLayout(scopes=tuple(scopes))

    @staticmethod
    def _regions_overlap(
        first: NormalizedRegion,
        second: NormalizedRegion,
    ) -> bool:
        left = first.report.location
        right = second.report.location
        if left.end_slot < right.slot or right.end_slot < left.slot:
            return False
        if left.slot == left.end_slot == right.slot == right.end_slot:
            left_end = left.byte_offset + left.byte_size
            right_end = right.byte_offset + right.byte_size
            return left.byte_offset < right_end and right.byte_offset < left_end
        return True

    @staticmethod
    def _scope_report(scope: CompiledScope) -> ComparisonScope:
        return ComparisonScope(
            id=scope.id,
            kind=scope.kind,
            root_slot=scope.root_slot,
            formula=scope.formula,
        )

    def _region(
        self,
        layout: CompiledLayout,
        scope: CompiledScope,
        declaration: CompiledDeclaration,
    ) -> NormalizedRegion:
        type_info = layout.get_type(declaration.type_id)
        if type_info is None:
            raise LayoutNormalizationUnavailable("invalid_layout")
        shape = self._shape(layout, type_info, depth=0, stack=())
        is_root = shape.encoding in {"mapping", "dynamic_array"}
        occupied_size = 32 if is_root or shape.encoding == "bytes" else declaration.byte_size
        end_slot = declaration.slot + max(
            1,
            ceil((declaration.byte_offset + occupied_size) / 32),
        ) - 1
        return NormalizedRegion(
            report=ComparisonRegion(
                scope=self._scope_report(scope),
                location=ComparisonLocation(
                    slot=declaration.slot,
                    byte_offset=declaration.byte_offset,
                    byte_size=occupied_size,
                    end_slot=end_slot,
                    is_root=is_root,
                ),
                path=declaration.name,
                type=self._type_report(shape),
            ),
            shape=shape,
        )

    @staticmethod
    def _type_report(shape: PhysicalShape) -> ComparisonType:
        return ComparisonType(
            label=shape.label,
            kind=shape.kind,
            encoding=shape.encoding,
            byte_size=shape.byte_size,
            array_length=shape.array_length,
            element_stride=shape.element_stride,
        )

    def _shape(
        self,
        layout: CompiledLayout,
        type_info: CompiledType,
        *,
        depth: int,
        stack: tuple[str, ...],
    ) -> PhysicalShape:
        if depth > self.max_depth:
            raise LayoutNormalizationUnavailable("analysis_limit")
        self._visits += 1
        if self._visits > self.max_visited_types:
            raise LayoutNormalizationUnavailable("analysis_limit")
        byte_size = type_info.num_bytes or 32
        if type_info.id in stack:
            return PhysicalShape(
                kind=type_info.kind,
                encoding=type_info.encoding,
                byte_size=byte_size,
                label=type_info.label,
                recursive=True,
                recursive_depth=stack.index(type_info.id),
            )
        next_stack = stack + (type_info.id,)

        def child(type_id: str | None) -> PhysicalShape | None:
            if not type_id:
                return None
            child_type = layout.get_type(type_id)
            if child_type is None:
                raise LayoutNormalizationUnavailable("invalid_layout")
            return self._shape(
                layout,
                child_type,
                depth=depth + 1,
                stack=next_stack,
            )

        if type_info.encoding == "mapping":
            return PhysicalShape(
                kind="mapping",
                encoding=type_info.encoding,
                byte_size=32,
                label=type_info.label,
                key=child(type_info.key_type),
                value=child(type_info.value_type),
            )
        if type_info.encoding == "dynamic_array":
            element = child(type_info.element_type)
            stride, per_slot = self._array_packing(element)
            return PhysicalShape(
                kind="dynamic_array",
                encoding=type_info.encoding,
                byte_size=32,
                label=type_info.label,
                element=element,
                element_stride=stride,
                elements_per_slot=per_slot,
            )
        if type_info.kind == "array" and type_info.array_length is not None:
            element = child(type_info.element_type)
            stride, per_slot = self._array_packing(element)
            return PhysicalShape(
                kind="fixed_array",
                encoding=type_info.encoding,
                byte_size=byte_size,
                label=type_info.label,
                element=element,
                array_length=type_info.array_length,
                element_stride=stride,
                elements_per_slot=per_slot,
            )
        if type_info.members:
            members = tuple(
                ShapeMember(
                    name=member.name,
                    slot=member.slot,
                    byte_offset=member.byte_offset,
                    byte_size=member.byte_size,
                    label=member.label,
                    shape=child(member.type_id),
                )
                for member in type_info.members
            )
            return PhysicalShape(
                kind="struct",
                encoding=type_info.encoding,
                byte_size=byte_size,
                label=type_info.label,
                members=members,
            )
        return PhysicalShape(
            kind="bytes" if type_info.encoding == "bytes" else type_info.kind,
            encoding=type_info.encoding,
            byte_size=byte_size,
            label=type_info.label,
        )

    @staticmethod
    def _array_packing(
        element: PhysicalShape | None,
    ) -> tuple[int, int]:
        if element is None:
            raise LayoutNormalizationUnavailable("invalid_layout")
        packs = (
            element.kind in {"value", "contract", "enum"}
            and element.encoding == "inplace"
            and 0 < element.byte_size < 32
        )
        if packs:
            return 1, 32 // element.byte_size
        return max(1, ceil(element.byte_size / 32)), 1
