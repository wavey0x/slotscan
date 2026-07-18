"""Immutable comparison report types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ComparisonVerdict(str, Enum):
    NO_CONFLICTS = "no_conflicts"
    CONFLICTS = "conflicts"
    INDETERMINATE = "indeterminate"
    UNAVAILABLE = "unavailable"


class ComparisonImpact(str, Enum):
    CONFLICT = "conflict"
    AMBIGUOUS = "ambiguous"
    NONE = "none"


@dataclass(frozen=True)
class ComparisonScope:
    id: str
    kind: str
    root_slot: int
    formula: str | None

    def to_wire(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "root_slot": hex(self.root_slot),
            "formula": self.formula,
        }


@dataclass(frozen=True)
class ComparisonLocation:
    slot: int
    byte_offset: int
    byte_size: int
    end_slot: int
    is_root: bool = False

    def to_wire(self) -> dict[str, Any]:
        return {
            "slot": hex(self.slot),
            "byte_offset": self.byte_offset,
            "byte_size": str(self.byte_size),
            "end_slot": hex(self.end_slot),
            "is_root": self.is_root,
        }


@dataclass(frozen=True)
class ComparisonType:
    label: str
    kind: str
    encoding: str
    byte_size: int
    array_length: int | None = None
    element_stride: int | None = None

    def to_wire(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "kind": self.kind,
            "encoding": self.encoding,
            "byte_size": str(self.byte_size),
            "array_length": (
                str(self.array_length) if self.array_length is not None else None
            ),
            "element_stride": (
                str(self.element_stride)
                if self.element_stride is not None
                else None
            ),
        }


@dataclass(frozen=True)
class ComparisonRegion:
    scope: ComparisonScope
    location: ComparisonLocation
    path: str
    type: ComparisonType

    def identity(self) -> str:
        return ":".join(
            (
                self.scope.id,
                str(self.location.slot),
                str(self.location.byte_offset),
                str(self.location.byte_size),
                self.path,
            )
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "scope": self.scope.to_wire(),
            "location": self.location.to_wire(),
            "path": self.path,
            "type": self.type.to_wire(),
        }


@dataclass(frozen=True)
class ComparisonEntry:
    id: str
    impact: ComparisonImpact
    kind: str
    from_region: ComparisonRegion | None
    to_region: ComparisonRegion | None
    details: tuple[str, ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "impact": self.impact.value,
            "kind": self.kind,
            "from_region": (
                self.from_region.to_wire() if self.from_region else None
            ),
            "to_region": self.to_region.to_wire() if self.to_region else None,
            "details": list(self.details),
        }


@dataclass(frozen=True)
class ComparisonSummary:
    conflicts: int
    ambiguous: int
    changes: int
    unchanged: int

    def to_wire(self) -> dict[str, int]:
        return {
            "conflicts": self.conflicts,
            "ambiguous": self.ambiguous,
            "changes": self.changes,
            "unchanged": self.unchanged,
        }


@dataclass(frozen=True)
class ComparisonResult:
    verdict: ComparisonVerdict
    summary: ComparisonSummary | None
    entries: tuple[ComparisonEntry, ...]
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedLayoutSubject:
    input_address: str
    storage_address: str
    code_address: str
    kind: str
    block_number: int
    block_hash: str
    name: str | None
    layout_status: str
    layout: Any | None
    layout_provenance: str | None = None
    layout_source_address: str | None = None

    def to_wire(self) -> dict[str, Any]:
        return {
            "input_address": self.input_address,
            "storage_address": self.storage_address,
            "code_address": self.code_address,
            "kind": self.kind,
            "block_ref": {
                "number": hex(self.block_number),
                "hash": self.block_hash,
            },
            "name": self.name,
            "layout_provenance": self.layout_provenance,
            "layout_source_address": self.layout_source_address,
            "layout_status": self.layout_status,
        }


@dataclass(frozen=True)
class LayoutComparisonReport:
    chain_id: int
    verdict: ComparisonVerdict
    from_subject: ResolvedLayoutSubject | None
    to_subject: ResolvedLayoutSubject | None
    summary: ComparisonSummary | None
    entries: tuple[ComparisonEntry, ...]
    limitations: tuple[str, ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "verdict": self.verdict.value,
            "from_subject": (
                self.from_subject.to_wire() if self.from_subject else None
            ),
            "to_subject": self.to_subject.to_wire() if self.to_subject else None,
            "summary": self.summary.to_wire() if self.summary else None,
            "entries": [entry.to_wire() for entry in self.entries],
            "limitations": list(self.limitations),
        }
