"""Backend-authoritative bounded storage access queries."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any

from web3 import Web3

from app.services.compiled_layout import (
    CompiledDeclaration,
    CompiledLayout,
    CompiledType,
)
from app.services.decoder import TypeDecoder
from app.services.storage import (
    StorageReader,
    is_materializable_storage_type,
    is_one_word_scalar,
    is_queryable_storage_type,
    is_solidity_dynamic_bytes,
)
from app.services.storage_rules import (
    compute_solidity_mapping_slot,
    compute_vyper_mapping_slot,
    encode_mapping_key,
)
from app.services.web3_provider import BlockRef


UINT256_MODULUS = 2**256


class StorageQueryError(ValueError):
    """A stable client error for an invalid or unsupported typed access."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _wire_decoded(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return [_wire_decoded(item) for item in value]
    if isinstance(value, dict):
        return {key: _wire_decoded(item) for key, item in value.items()}
    return value


def _parse_uint(value: object, label: str) -> int:
    if not isinstance(value, str) or not value.strip():
        raise StorageQueryError("INVALID_INPUT", f"{label} must be a string")
    try:
        parsed = int(value, 0)
    except ValueError as exc:
        raise StorageQueryError(
            "INVALID_INPUT",
            f"{label} must be a decimal or hexadecimal integer",
        ) from exc
    if parsed < 0 or parsed >= UINT256_MODULUS:
        raise StorageQueryError(
            "INVALID_INPUT",
            f"{label} is outside the uint256 range",
        )
    return parsed


def _mapping_location(
    layout: CompiledLayout,
    base_slot: int,
    declared_key_type: str,
    value: object,
) -> int:
    if not isinstance(value, str):
        raise StorageQueryError("INVALID_MAPPING_KEY", "Mapping key must be a string")
    try:
        encoded_key = encode_mapping_key(declared_key_type, value)
    except (TypeError, ValueError) as exc:
        raise StorageQueryError("INVALID_MAPPING_KEY", str(exc)) from exc
    if layout.storage_rules.mapping_preimage_order == "key_then_slot":
        return compute_solidity_mapping_slot(base_slot, encoded_key)
    return compute_vyper_mapping_slot(base_slot, encoded_key)


def _hashed_root(slot: int) -> int:
    return int.from_bytes(Web3.keccak(slot.to_bytes(32, "big")), "big")


def _region(
    role: str,
    slot: int,
    slot_count: int | None = 1,
) -> dict[str, str | None]:
    return {
        "role": role,
        "slot": hex(slot % UINT256_MODULUS),
        "slot_count": str(slot_count) if slot_count is not None else None,
    }


def _provenance(
    regions: list[dict[str, str | None]],
) -> dict[str, list[dict[str, str | None]]] | None:
    return {"regions": regions} if regions else None


def _terminal_word_count(type_info: CompiledType) -> int:
    return max(1, ceil((type_info.num_bytes or 32) / 32))


@dataclass(frozen=True)
class _Leaf:
    relative_path: str
    type_info: CompiledType
    slot: int
    byte_offset: int


@dataclass(frozen=True)
class _ResolvedAccess:
    path: str
    type_info: CompiledType
    slot: int
    byte_offset: int
    regions: tuple[dict[str, str | None], ...]
    array_length: str | None


@dataclass(frozen=True)
class _DynamicValue:
    data_slots: tuple[int, ...]
    storage: dict[str, list[dict[str, str | None]]] | None


class StorageQueryEngine:
    """Resolve a linear access path and materialize one bounded terminal value."""

    def __init__(
        self,
        *,
        layout: CompiledLayout,
        reader: StorageReader,
        decoder: TypeDecoder,
        max_words: int,
        chain_id: int,
        address: str,
        block_ref: BlockRef,
    ):
        self.layout = layout
        self.reader = reader
        self.decoder = decoder
        self.max_words = max_words
        self.chain_id = chain_id
        self.address = address
        self.block_ref = block_ref
        self._words: dict[int, str] = {}

    async def _read(self, slots: list[int]) -> None:
        unique_new = [
            slot % UINT256_MODULUS
            for slot in dict.fromkeys(slots)
            if slot % UINT256_MODULUS not in self._words
        ]
        if len(self._words) + len(unique_new) > self.max_words:
            raise StorageQueryError(
                "QUERY_TOO_LARGE",
                f"Query exceeds the {self.max_words}-word read limit",
            )
        if not unique_new:
            return
        self._words.update(
            await self.reader.read_slots(
                self.chain_id,
                self.address,
                unique_new,
                self.block_ref.number,
            )
        )

    def _validate_steps(
        self,
        declaration: CompiledDeclaration,
        steps: list[dict[str, str]],
    ) -> None:
        current = self.layout.get_type(declaration.type_id)
        if current is None:
            raise StorageQueryError(
                "UNSUPPORTED_ACCESS",
                "The declaration type is unavailable",
            )
        if not is_queryable_storage_type(self.layout, current):
            raise StorageQueryError(
                "UNSUPPORTED_ACCESS",
                "The declaration does not have a supported bounded access path",
            )

        step_index = 0
        visited: set[str] = set()
        while current.encoding == "mapping" or current.kind == "array":
            if current.id in visited:
                raise StorageQueryError(
                    "UNSUPPORTED_ACCESS",
                    "The access path contains a recursive container",
                )
            visited.add(current.id)
            if step_index >= len(steps):
                raise StorageQueryError(
                    "UNSUPPORTED_ACCESS",
                    "The access path is missing a mapping key or array index",
                )

            step = steps[step_index]
            if current.encoding == "mapping":
                if (
                    step.get("kind") != "mapping_key"
                    or not current.key_type
                    or not current.value_type
                ):
                    raise StorageQueryError(
                        "UNSUPPORTED_ACCESS",
                        "The access step does not match the mapping type",
                    )
                _mapping_location(
                    self.layout,
                    0,
                    current.key_type,
                    step.get("value"),
                )
                next_type_id = current.value_type
            else:
                if step.get("kind") != "array_index" or not current.element_type:
                    raise StorageQueryError(
                        "UNSUPPORTED_ACCESS",
                        "The access step does not match the array type",
                    )
                _parse_uint(step.get("value"), "array index")
                if (
                    current.encoding == "dynamic_array"
                    and self.layout.storage_rules.array_storage_scheme
                    == "vyper_legacy_hashed"
                ):
                    raise StorageQueryError(
                        "UNSUPPORTED_ACCESS",
                        "Legacy Vyper hashed dynamic arrays are unsupported",
                    )
                next_type_id = current.element_type

            next_type = self.layout.get_type(next_type_id)
            if next_type is None:
                raise StorageQueryError(
                    "UNSUPPORTED_ACCESS",
                    "The access path references an unavailable type",
                )
            current = next_type
            step_index += 1

        if step_index != len(steps):
            raise StorageQueryError(
                "UNSUPPORTED_ACCESS",
                "The access path contains extra steps",
            )
        if not is_materializable_storage_type(self.layout, current):
            raise StorageQueryError(
                "UNSUPPORTED_ACCESS",
                "The terminal value cannot be materialized safely",
            )

    def _array_data_start(
        self,
        array_type: CompiledType,
        base_slot: int,
    ) -> int:
        scheme = self.layout.storage_rules.array_storage_scheme
        if array_type.encoding == "dynamic_array":
            if scheme == "solidity":
                return _hashed_root(base_slot)
            if scheme == "vyper_sequential":
                return (base_slot + 1) % UINT256_MODULUS
            raise StorageQueryError(
                "UNSUPPORTED_ACCESS",
                "Legacy Vyper hashed dynamic arrays are unsupported",
            )
        if array_type.encoding != "inplace" or array_type.array_length is None:
            raise StorageQueryError(
                "UNSUPPORTED_ACCESS",
                "The declaration is not a supported fixed array",
            )
        return (
            _hashed_root(base_slot)
            if scheme == "vyper_legacy_hashed"
            else base_slot
        )

    def _array_element_location(
        self,
        element_type: CompiledType,
        data_start: int,
        index: int,
    ) -> tuple[int, int]:
        element_size = element_type.num_bytes or 32
        if (
            self.layout.storage_rules.array_storage_scheme == "solidity"
            and is_one_word_scalar(element_type)
            and element_size < 32
        ):
            elements_per_word = 32 // element_size
            return (
                (data_start + index // elements_per_word) % UINT256_MODULUS,
                (index % elements_per_word) * element_size,
            )
        stride = max(1, ceil(element_size / 32))
        return (
            (data_start + index * stride) % UINT256_MODULUS,
            0,
        )

    async def _resolve(
        self,
        declaration: CompiledDeclaration,
        steps: list[dict[str, str]],
    ) -> _ResolvedAccess:
        current = self.layout.get_type(declaration.type_id)
        assert current is not None
        slot = declaration.slot
        byte_offset = declaration.byte_offset
        path = declaration.name
        regions: list[dict[str, str | None]] = []
        array_length: str | None = None

        for step in steps:
            if current.encoding == "mapping":
                regions.append(_region("anchor", slot))
                assert current.key_type and current.value_type
                value = step["value"]
                slot = _mapping_location(
                    self.layout,
                    slot,
                    current.key_type,
                    value,
                )
                path = f"{path}[{value}]"
                current = self.layout.types[current.value_type]
                byte_offset = 0
                continue

            assert current.kind == "array" and current.element_type
            index = _parse_uint(step["value"], "array index")
            element_type = self.layout.types[current.element_type]
            if current.encoding == "dynamic_array":
                regions.append(_region("length", slot))
                await self._read([slot])
                current_length = int(self._words[slot], 16)
                if index >= current_length:
                    raise StorageQueryError(
                        "ARRAY_BOUNDS",
                        "Array index is outside the current dynamic length",
                    )
                if current.array_length is not None and index >= current.array_length:
                    raise StorageQueryError(
                        "ARRAY_BOUNDS",
                        "Array index is outside the declared bound",
                    )
                array_length = str(current_length)
            elif current.array_length is None or index >= current.array_length:
                raise StorageQueryError(
                    "ARRAY_BOUNDS",
                    "Array index is outside the declared bound",
                )

            data_start = self._array_data_start(current, slot)
            slot, byte_offset = self._array_element_location(
                element_type,
                data_start,
                index,
            )
            path = f"{path}[{index}]"
            current = element_type

        if not is_solidity_dynamic_bytes(self.layout, current):
            regions.append(
                _region("entry", slot, _terminal_word_count(current))
            )
        return _ResolvedAccess(
            path=path,
            type_info=current,
            slot=slot,
            byte_offset=byte_offset,
            regions=tuple(regions),
            array_length=array_length,
        )

    def _flatten(
        self,
        type_info: CompiledType,
        slot: int,
        byte_offset: int,
        *,
        relative_path: str = "",
        stack: tuple[str, ...] = (),
    ) -> list[_Leaf]:
        if is_one_word_scalar(type_info) or is_solidity_dynamic_bytes(
            self.layout,
            type_info,
        ):
            return [
                _Leaf(
                    relative_path=relative_path,
                    type_info=type_info,
                    slot=slot,
                    byte_offset=byte_offset,
                )
            ]
        if type_info.id in stack:
            raise StorageQueryError(
                "UNSUPPORTED_ACCESS",
                "The terminal value contains a recursive struct",
            )

        leaves: list[_Leaf] = []
        next_stack = stack + (type_info.id,)
        for member in type_info.members:
            member_type = self.layout.get_type(member.type_id)
            if member_type is None:
                raise StorageQueryError(
                    "UNSUPPORTED_ACCESS",
                    "The terminal value references an unavailable member type",
                )
            member_path = (
                f"{relative_path}.{member.name}"
                if relative_path
                else member.name
            )
            leaves.extend(
                self._flatten(
                    member_type,
                    (slot + member.slot) % UINT256_MODULUS,
                    member.byte_offset,
                    relative_path=member_path,
                    stack=next_stack,
                )
            )
        return leaves

    async def query(
        self,
        declaration: CompiledDeclaration,
        steps: list[dict[str, str]],
    ) -> dict[str, Any]:
        self._validate_steps(declaration, steps)
        resolved = await self._resolve(declaration, steps)
        leaves = self._flatten(
            resolved.type_info,
            resolved.slot,
            resolved.byte_offset,
        )
        await self._read([leaf.slot for leaf in leaves])

        root_is_leaf = len(leaves) == 1 and leaves[0].relative_path == ""
        dynamic_values: dict[int, _DynamicValue] = {}
        dynamic_data_slots: list[int] = []
        for index, leaf in enumerate(leaves):
            if not is_solidity_dynamic_bytes(self.layout, leaf.type_info):
                continue
            raw_word = bytes.fromhex(self._words[leaf.slot][2:])
            prefix = list(resolved.regions) if root_is_leaf else []
            try:
                length, is_inline = self.decoder.inspect_dynamic_bytes_slot(
                    raw_word
                )
            except ValueError as exc:
                raise StorageQueryError(
                    "MALFORMED_STORAGE",
                    f"{leaf.relative_path or resolved.path} has an invalid dynamic header",
                ) from exc
            if is_inline:
                dynamic_values[index] = _DynamicValue(
                    data_slots=(),
                    storage=_provenance(
                        prefix + [_region("inline", leaf.slot)]
                    ),
                )
                continue

            required_words = (length + 31) // 32
            pending_unique = len(set(dynamic_data_slots))
            if (
                required_words
                > self.max_words - len(self._words) - pending_unique
            ):
                raise StorageQueryError(
                    "QUERY_TOO_LARGE",
                    f"Query exceeds the {self.max_words}-word read limit",
                )
            data_start = _hashed_root(leaf.slot)
            data_slots = tuple(
                (data_start + offset) % UINT256_MODULUS
                for offset in range(required_words)
            )
            dynamic_data_slots.extend(data_slots)
            dynamic_values[index] = _DynamicValue(
                data_slots=data_slots,
                storage=_provenance(
                    prefix
                    + [
                        _region("length", leaf.slot),
                        _region("data", data_start, required_words),
                    ]
                ),
            )

        await self._read(dynamic_data_slots)

        items: list[dict[str, Any]] = []
        for index, leaf in enumerate(leaves):
            raw_word = self._words[leaf.slot]
            storage = None
            decoded_wire = None
            if index in dynamic_values:
                dynamic = dynamic_values[index]
                storage = dynamic.storage
                try:
                    decoded = self.decoder.decode_dynamic_bytes_value(
                        bytes.fromhex(raw_word[2:]),
                        [
                            bytes.fromhex(self._words[slot][2:])
                            for slot in dynamic.data_slots
                        ],
                        leaf.type_info.label,
                    )
                except Exception as exc:
                    raise StorageQueryError(
                        "MALFORMED_STORAGE",
                        f"{leaf.relative_path or resolved.path} could not be decoded",
                    ) from exc
                decoded_wire = _wire_decoded(decoded.decoded)
            else:
                if root_is_leaf:
                    storage = _provenance(list(resolved.regions))
                try:
                    decoded = self.decoder.decode(
                        bytes.fromhex(raw_word[2:]),
                        leaf.type_info,
                        leaf.byte_offset,
                    )
                except Exception:
                    pass
                else:
                    decoded_wire = _wire_decoded(decoded.decoded)

            full_path = (
                resolved.path
                if not leaf.relative_path
                else f"{resolved.path}.{leaf.relative_path}"
            )
            items.append(
                {
                    "path": full_path,
                    "relative_path": leaf.relative_path,
                    "type_id": leaf.type_info.id,
                    "type_label": leaf.type_info.label,
                    "location": {
                        "slot": hex(leaf.slot),
                        "byte_offset": leaf.byte_offset,
                        "byte_size": leaf.type_info.num_bytes or 32,
                    },
                    "value_encoded": raw_word,
                    "value_decoded": decoded_wire,
                    "storage": storage,
                }
            )

        root_storage = (
            items[0]["storage"]
            if root_is_leaf
            else _provenance(list(resolved.regions))
        )
        return {
            "block_ref": {
                "number": hex(self.block_ref.number),
                "hash": self.block_ref.hash,
            },
            "layout_id": self.layout.layout_id,
            "declaration_id": declaration.declaration_id,
            "path": resolved.path,
            "type_id": resolved.type_info.id,
            "type_label": resolved.type_info.label,
            "location": {
                "slot": hex(resolved.slot),
                "byte_offset": resolved.byte_offset,
                "byte_size": resolved.type_info.num_bytes or 32,
            },
            "array_length": resolved.array_length,
            "storage": root_storage,
            "items": items,
        }
