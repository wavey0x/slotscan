"""Validated immutable runtime storage layouts."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping

from app.models.domain import StorageLayout, StorageScope, StorageType, StorageVariable
from app.services.storage_rules import (
    StorageRules,
    UnsupportedStorageRules,
    storage_rules_for_layout,
    synthesize_storage_type,
)


class UnsupportedCompiledLayout(ValueError):
    """Raised when a layout cannot safely support deterministic access."""


@dataclass(frozen=True)
class CompiledMember:
    name: str
    slot: int
    byte_offset: int
    byte_size: int
    type_id: str
    label: str


@dataclass(frozen=True)
class CompiledType:
    id: str
    label: str
    kind: str
    encoding: str
    num_bytes: int | None
    base_type: str | None
    element_type: str | None
    array_length: int | None
    key_type: str | None
    value_type: str | None
    members: tuple[CompiledMember, ...]


@dataclass(frozen=True)
class CompiledDeclaration:
    declaration_id: str
    name: str
    slot: int
    byte_offset: int
    byte_size: int
    type_id: str
    label: str
    provenance: str
    confidence: str
    scope_id: str


@dataclass(frozen=True)
class CompiledScope:
    id: str
    kind: str
    root_slot: int
    formula: str | None
    provenance: str
    confidence: str


@dataclass(frozen=True)
class CompiledLayout:
    """A deep-copied, immutable, identity-bound runtime layout."""

    contract_name: str
    language: str | None
    scopes: tuple[CompiledScope, ...]
    variables: tuple[CompiledDeclaration, ...]
    types: Mapping[str, CompiledType]
    storage_rules: StorageRules
    layout_id: str

    def get_type(self, type_id: str) -> CompiledType | None:
        return self.types.get(type_id)

    def get_declaration(self, declaration_id: str) -> CompiledDeclaration | None:
        return next(
            (
                declaration
                for declaration in self.variables
                if declaration.declaration_id == declaration_id
            ),
            None,
        )

    def canonical_wire(self) -> dict[str, Any]:
        return _canonical_wire(
            self.scopes,
            self.variables,
            self.types,
            self.storage_rules,
        )


def _validate_slot(value: int, label: str) -> None:
    if value < 0 or value >= 2**256:
        raise UnsupportedCompiledLayout(f"{label} is outside the EVM slot range")


def _validate_byte_range(offset: int, size: int, label: str) -> None:
    if offset < 0 or offset > 31:
        raise UnsupportedCompiledLayout(f"{label} has an invalid byte offset")
    if size <= 0:
        raise UnsupportedCompiledLayout(f"{label} has an invalid byte size")
    if size <= 32 and offset + size > 32:
        raise UnsupportedCompiledLayout(f"{label} crosses a physical word")
    if size > 32 and offset != 0:
        raise UnsupportedCompiledLayout(
            f"{label} is multi-word but has a non-zero byte offset"
        )


def _copy_member(member: StorageVariable, owner: str) -> CompiledMember:
    _validate_slot(member.slot, f"{owner}.{member.name} member slot")
    _validate_byte_range(
        member.offset,
        member.size,
        f"{owner}.{member.name}",
    )
    if not member.name or not member.type_id:
        raise UnsupportedCompiledLayout(f"{owner} has an incomplete member")
    return CompiledMember(
        name=member.name,
        slot=member.slot,
        byte_offset=member.offset,
        byte_size=member.size,
        type_id=member.type_id,
        label=member.label,
    )


def _copy_type(type_id: str, source: StorageType) -> CompiledType:
    if source.id and source.id != type_id:
        raise UnsupportedCompiledLayout(
            f"Type registry key {type_id} does not match type id {source.id}"
        )
    if source.num_bytes is not None and source.num_bytes <= 0:
        raise UnsupportedCompiledLayout(f"Type {type_id} has an invalid byte size")
    if source.array_length is not None and source.array_length < 0:
        raise UnsupportedCompiledLayout(f"Type {type_id} has a negative array length")
    if source.encoding == "mapping" and (
        not source.key_type or not source.value_type
    ):
        raise UnsupportedCompiledLayout(
            f"Mapping type {type_id} is missing its key or value type"
        )
    if source.encoding == "dynamic_array" and not source.element_type:
        raise UnsupportedCompiledLayout(
            f"Dynamic array type {type_id} is missing its element type"
        )
    if source.kind == "array" and not source.element_type:
        raise UnsupportedCompiledLayout(
            f"Array type {type_id} is missing its element type"
        )
    members = tuple(
        _copy_member(member, type_id)
        for member in (source.members or ())
    )
    return CompiledType(
        id=type_id,
        label=source.label,
        kind=source.kind,
        encoding=source.encoding,
        num_bytes=source.num_bytes,
        base_type=source.base_type,
        element_type=source.element_type,
        array_length=source.array_length,
        key_type=source.key_type,
        value_type=source.value_type,
        members=members,
    )


def _copy_scope(source: StorageScope) -> CompiledScope:
    if not source.id:
        raise UnsupportedCompiledLayout("Storage scope has no id")
    if source.kind not in {"default", "erc7201", "unstructured", "custom"}:
        raise UnsupportedCompiledLayout(
            f"Storage scope {source.id} has unsupported kind {source.kind}"
        )
    _validate_slot(source.root_slot, f"Storage scope {source.id} root")
    return CompiledScope(
        id=source.id,
        kind=source.kind,
        root_slot=source.root_slot,
        formula=source.formula,
        provenance=source.provenance,
        confidence=source.confidence,
    )


def _type_references(type_info: CompiledType) -> tuple[str, ...]:
    references = [
        type_info.base_type,
        type_info.element_type,
        type_info.key_type,
        type_info.value_type,
    ]
    references.extend(member.type_id for member in type_info.members)
    return tuple(reference for reference in references if reference)


def _type_wire(type_info: CompiledType) -> dict[str, Any]:
    return {
        "id": type_info.id,
        "label": type_info.label,
        "kind": type_info.kind,
        "encoding": type_info.encoding,
        "num_bytes": (
            str(type_info.num_bytes) if type_info.num_bytes is not None else None
        ),
        "base_type": type_info.base_type,
        "element_type": type_info.element_type,
        "array_length": (
            str(type_info.array_length)
            if type_info.array_length is not None
            else None
        ),
        "key_type": type_info.key_type,
        "value_type": type_info.value_type,
        "members": [
            {
                "name": member.name,
                "slot": hex(member.slot),
                "byte_offset": member.byte_offset,
                "byte_size": str(member.byte_size),
                "type_id": member.type_id,
                "label": member.label,
            }
            for member in type_info.members
        ],
    }


def _canonical_wire(
    scopes: tuple[CompiledScope, ...],
    variables: tuple[CompiledDeclaration, ...],
    types: Mapping[str, CompiledType],
    storage_rules: StorageRules,
) -> dict[str, Any]:
    return {
        "scopes": [
            {
                "id": scope.id,
                "kind": scope.kind,
                "root_slot": hex(scope.root_slot),
                "formula": scope.formula,
                "provenance": scope.provenance,
                "confidence": scope.confidence,
            }
            for scope in scopes
        ],
        "variables": [
            {
                "declaration_id": declaration.declaration_id,
                "name": declaration.name,
                "slot": hex(declaration.slot),
                "byte_offset": declaration.byte_offset,
                "byte_size": str(declaration.byte_size),
                "type_id": declaration.type_id,
                "type_label": declaration.label,
                "provenance": declaration.provenance,
                "confidence": declaration.confidence,
                "scope_id": declaration.scope_id,
            }
            for declaration in variables
        ],
        "types": {
            type_id: _type_wire(types[type_id])
            for type_id in sorted(types)
        },
        "storage_rules": {
            "mapping_preimage_order": storage_rules.mapping_preimage_order,
            "array_storage_scheme": storage_rules.array_storage_scheme,
        },
    }


def compile_layout(layout: StorageLayout) -> CompiledLayout:
    """Validate, deep-copy, normalize, and identify one source layout."""
    try:
        rules = storage_rules_for_layout(layout)
    except UnsupportedStorageRules as exc:
        raise UnsupportedCompiledLayout(str(exc)) from exc
    copied_scopes = tuple(
        sorted(
            (_copy_scope(scope) for scope in layout.scopes),
            key=lambda scope: (
                scope.root_slot,
                scope.kind,
                scope.id,
            ),
        )
    )
    scope_ids = {scope.id for scope in copied_scopes}
    if len(scope_ids) != len(copied_scopes):
        raise UnsupportedCompiledLayout("Layout contains duplicate storage scope ids")
    default_scopes = [scope for scope in copied_scopes if scope.kind == "default"]
    if len(default_scopes) != 1 or default_scopes[0].root_slot != 0:
        raise UnsupportedCompiledLayout(
            "Layout must contain exactly one default scope rooted at slot zero"
        )

    ordered_variables = sorted(
        layout.variables,
        key=lambda variable: (
            variable.scope_id,
            variable.slot,
            variable.offset,
            variable.name,
            variable.type_id,
            variable.provenance,
            variable.confidence,
        ),
    )

    declarations: list[CompiledDeclaration] = []
    pending_type_ids: list[str] = []
    for ordinal, variable in enumerate(ordered_variables):
        _validate_slot(variable.slot, f"Variable {variable.name} slot")
        _validate_byte_range(
            variable.offset,
            variable.size,
            f"Variable {variable.name}",
        )
        if not variable.name or not variable.type_id:
            raise UnsupportedCompiledLayout("Layout contains an incomplete variable")
        if variable.scope_id not in scope_ids:
            raise UnsupportedCompiledLayout(
                f"Variable {variable.name} references missing scope {variable.scope_id}"
            )
        declarations.append(
            CompiledDeclaration(
                declaration_id=f"decl:{ordinal}",
                name=variable.name,
                slot=variable.slot,
                byte_offset=variable.offset,
                byte_size=variable.size,
                type_id=variable.type_id,
                label=variable.label,
                provenance=variable.provenance,
                confidence=variable.confidence,
                scope_id=variable.scope_id,
            )
        )
        pending_type_ids.append(variable.type_id)

    copied_types: dict[str, CompiledType] = {}
    while pending_type_ids:
        type_id = pending_type_ids.pop(0)
        if type_id in copied_types:
            continue
        source = layout.types.get(type_id) or synthesize_storage_type(type_id)
        if source is None:
            raise UnsupportedCompiledLayout(f"Missing storage type: {type_id}")
        copied = _copy_type(type_id, source)
        copied_types[type_id] = copied
        pending_type_ids.extend(
            reference
            for reference in _type_references(copied)
            if reference not in copied_types
        )

    immutable_types = MappingProxyType(
        {type_id: copied_types[type_id] for type_id in sorted(copied_types)}
    )
    variables = tuple(declarations)
    wire = _canonical_wire(copied_scopes, variables, immutable_types, rules)
    canonical_bytes = json.dumps(
        wire,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    layout_id = "sha256:" + sha256(canonical_bytes).hexdigest()

    return CompiledLayout(
        contract_name=layout.contract_name,
        language=layout.language,
        scopes=copied_scopes,
        variables=variables,
        types=immutable_types,
        storage_rules=rules,
        layout_id=layout_id,
    )
