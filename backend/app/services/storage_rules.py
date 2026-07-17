"""Pure storage type and locator rules."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Literal

from eth_abi import encode as abi_encode
from web3 import Web3

from app.models.domain import StorageLayout, StorageType
from app.utils.vyper import (
    LEGACY_HASHED_STORAGE,
    SEQUENTIAL_STORAGE,
    parse_vyper_version,
)


MappingPreimageOrder = Literal["key_then_slot", "slot_then_key"]
ArrayStorageScheme = Literal[
    "solidity",
    "vyper_sequential",
    "vyper_legacy_hashed",
]

_UINT_PATTERN = re.compile(r"^t_uint(\d+)$")
_INT_PATTERN = re.compile(r"^t_int(\d+)$")
_BYTES_PATTERN = re.compile(r"^t_bytes(\d+)$")
_HASHMAP_PATTERN = re.compile(r"^HashMap\[(.+),\s*(.+)\]$")
_DYNARRAY_PATTERN = re.compile(r"^DynArray\[(.+),\s*(\d+)\]$")
_STATIC_ARRAY_PATTERN = re.compile(r"^(.+)\[(\d+)\]$")
_VYPER_UINT_PATTERN = re.compile(r"^uint(\d+)$")
_VYPER_INT_PATTERN = re.compile(r"^int(\d+)$")
_VYPER_BYTES_PATTERN = re.compile(r"^bytes(\d+)$")
_SOLIDITY_VERSION_PATTERN = re.compile(r"^v?\d+\.\d+\.\d+(?:\+.*)?$")
_UINT_KEY_PATTERN = re.compile(r"^(?:t_)?uint(?P<bits>\d{0,3})(?:_storage)?$")
_INT_KEY_PATTERN = re.compile(r"^(?:t_)?int(?P<bits>\d{0,3})(?:_storage)?$")
_BYTES_KEY_PATTERN = re.compile(r"^(?:t_)?bytes(?P<size>\d+)(?:_storage)?$")

_FIXTURE_BACKED_VYPER_VERSIONS = {
    (0, 2, 4),
    (0, 3, 7),
    (0, 3, 10),
}


class UnsupportedStorageRules(ValueError):
    """Raised when exact compiler-backed storage rules are unavailable."""


@dataclass(frozen=True)
class StorageRules:
    """Normalized storage locator semantics."""

    mapping_preimage_order: MappingPreimageOrder
    array_storage_scheme: ArrayStorageScheme


def storage_rules_for_layout(layout: StorageLayout) -> StorageRules:
    """Select exact normalized rules from language/compiler evidence."""
    language = (layout.language or "").strip().lower()
    compiler_version = (layout.compiler_version or "").strip()
    storage_scheme = (layout.storage_scheme or "").strip()

    if not language or not compiler_version or not storage_scheme:
        raise UnsupportedStorageRules(
            "Language, compiler version, and storage scheme are required"
        )

    if language == "solidity":
        if not _SOLIDITY_VERSION_PATTERN.fullmatch(compiler_version):
            raise UnsupportedStorageRules(
                f"Unsupported Solidity compiler version: {compiler_version}"
            )
        if storage_scheme != "solidity":
            raise UnsupportedStorageRules(
                f"Unsupported Solidity storage scheme: {storage_scheme}"
            )
        return StorageRules(
            mapping_preimage_order="key_then_slot",
            array_storage_scheme="solidity",
        )

    if language == "vyper":
        version = parse_vyper_version(compiler_version)
        if version not in _FIXTURE_BACKED_VYPER_VERSIONS:
            raise UnsupportedStorageRules(
                f"No fixture-backed Vyper rules for {compiler_version}"
            )
        if storage_scheme == SEQUENTIAL_STORAGE:
            array_scheme: ArrayStorageScheme = "vyper_sequential"
        elif storage_scheme == LEGACY_HASHED_STORAGE:
            array_scheme = "vyper_legacy_hashed"
        else:
            raise UnsupportedStorageRules(
                f"Unsupported Vyper storage scheme: {storage_scheme}"
            )
        return StorageRules(
            mapping_preimage_order="slot_then_key",
            array_storage_scheme=array_scheme,
        )

    raise UnsupportedStorageRules(f"Unsupported storage language: {layout.language}")


def _strip_type_id_suffix(type_name: str) -> str:
    """Remove solc's source-specific suffix from an internal type id."""
    return re.sub(r"\$\d+(?:_storage)?$", "", type_name.strip().lower())


def _coerce_bytes(value: Any, *, type_name: str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        if value.startswith("0x"):
            try:
                return bytes.fromhex(value[2:])
            except ValueError as exc:
                raise ValueError(f"Invalid hexadecimal {type_name} mapping key") from exc
        return value.encode()
    raise TypeError(f"{type_name} mapping key must be bytes or a string")


def encode_mapping_key(declared_type: str, input_value: Any) -> bytes:
    """Encode one mapping key without an unknown-type fallback."""
    if not declared_type:
        raise ValueError("Mapping key type is required")

    normalized = _strip_type_id_suffix(declared_type)

    if normalized in {"string", "t_string", "t_string_storage"}:
        if isinstance(input_value, str) and not input_value.startswith("0x"):
            return input_value.encode("utf-8")
        return _coerce_bytes(input_value, type_name="string")

    if normalized in {"bytes", "t_bytes", "t_bytes_storage"}:
        return _coerce_bytes(input_value, type_name="bytes")

    if (
        normalized
        in {"address", "address payable", "t_address", "t_address_payable"}
        or normalized.startswith("t_contract")
        or normalized.startswith("contract ")
        or normalized.startswith("interface ")
    ):
        try:
            address = Web3.to_checksum_address(input_value)
        except Exception as exc:
            raise ValueError(
                f"Invalid address mapping key: {input_value!r}"
            ) from exc
        return abi_encode(["address"], [address])

    if normalized in {"bool", "t_bool"}:
        value = input_value
        if isinstance(value, str):
            lowered = value.lower()
            if lowered in {"true", "1"}:
                value = True
            elif lowered in {"false", "0"}:
                value = False
            else:
                raise ValueError(f"Invalid bool mapping key: {input_value!r}")
        if value not in (True, False, 0, 1):
            raise ValueError(f"Invalid bool mapping key: {input_value!r}")
        return abi_encode(["bool"], [bool(value)])

    uint_match = _UINT_KEY_PATTERN.match(normalized)
    if uint_match:
        bits = int(uint_match.group("bits") or "256")
        value = (
            int(input_value, 0) if isinstance(input_value, str) else int(input_value)
        )
        if bits < 8 or bits > 256 or bits % 8 or value < 0 or value >= 2**bits:
            raise ValueError(f"Value {value} is outside uint{bits}")
        return abi_encode([f"uint{bits}"], [value])

    int_match = _INT_KEY_PATTERN.match(normalized)
    if int_match:
        bits = int(int_match.group("bits") or "256")
        value = (
            int(input_value, 0) if isinstance(input_value, str) else int(input_value)
        )
        if (
            bits < 8
            or bits > 256
            or bits % 8
            or value < -(2 ** (bits - 1))
            or value >= 2 ** (bits - 1)
        ):
            raise ValueError(f"Value {value} is outside int{bits}")
        return abi_encode([f"int{bits}"], [value])

    bytes_match = _BYTES_KEY_PATTERN.match(normalized)
    if bytes_match:
        size = int(bytes_match.group("size"))
        if size < 1 or size > 32:
            raise ValueError(f"Invalid fixed bytes width: {size}")
        value = _coerce_bytes(input_value, type_name=f"bytes{size}")
        if len(value) != size:
            raise ValueError(
                f"bytes{size} mapping key must contain exactly {size} bytes"
            )
        return abi_encode([f"bytes{size}"], [value])

    if normalized.startswith("t_enum") or normalized.startswith("enum "):
        value = (
            int(input_value, 0) if isinstance(input_value, str) else int(input_value)
        )
        if value < 0 or value >= 2**256:
            raise ValueError(f"Invalid enum mapping key: {input_value!r}")
        return abi_encode(["uint256"], [value])

    raise ValueError(f"Unsupported mapping key type: {declared_type}")


def compute_solidity_mapping_slot(base_slot: int, encoded_key: bytes) -> int:
    """Compute ``keccak256(key || slot)``."""
    slot_word = abi_encode(["uint256"], [base_slot])
    return int.from_bytes(Web3.keccak(encoded_key + slot_word), "big")


def compute_vyper_mapping_slot(base_slot: int, encoded_key: bytes) -> int:
    """Compute fixture-backed Vyper ``keccak256(slot || key)``."""
    slot_word = abi_encode(["uint256"], [base_slot])
    return int.from_bytes(Web3.keccak(slot_word + encoded_key), "big")


def compute_mapping_slot(
    layout: StorageLayout,
    base_slot: int,
    declared_type: str,
    input_value: Any,
) -> int:
    """Compute a mapping location using the layout's exact normalized rule."""
    rules = storage_rules_for_layout(layout)
    encoded_key = encode_mapping_key(declared_type, input_value)
    if rules.mapping_preimage_order == "key_then_slot":
        return compute_solidity_mapping_slot(base_slot, encoded_key)
    return compute_vyper_mapping_slot(base_slot, encoded_key)


def synthesize_storage_type(type_id: str) -> StorageType | None:
    """Return a synthesized storage type without mutating a registry."""
    uint_match = _UINT_PATTERN.match(type_id)
    if uint_match:
        bits = int(uint_match.group(1))
        return StorageType(
            id=type_id,
            label=f"uint{bits}",
            kind="value",
            encoding="inplace",
            num_bytes=bits // 8,
        )

    int_match = _INT_PATTERN.match(type_id)
    if int_match:
        bits = int(int_match.group(1))
        return StorageType(
            id=type_id,
            label=f"int{bits}",
            kind="value",
            encoding="inplace",
            num_bytes=bits // 8,
        )

    if type_id in {"t_address", "t_address_payable"}:
        return StorageType(
            id=type_id,
            label="address payable" if type_id.endswith("payable") else "address",
            kind="value",
            encoding="inplace",
            num_bytes=20,
        )

    if type_id == "t_bool":
        return StorageType(
            id=type_id,
            label="bool",
            kind="value",
            encoding="inplace",
            num_bytes=1,
        )

    bytes_match = _BYTES_PATTERN.match(type_id)
    if bytes_match:
        width = int(bytes_match.group(1))
        return StorageType(
            id=type_id,
            label=f"bytes{width}",
            kind="value",
            encoding="inplace",
            num_bytes=width,
        )

    if type_id in {"t_string_storage", "t_bytes_storage"}:
        return StorageType(
            id=type_id,
            label="string" if type_id == "t_string_storage" else "bytes",
            kind="value",
            encoding="bytes",
            num_bytes=32,
        )

    if type_id.startswith("t_contract"):
        contract_match = re.match(r"^t_contract\$_(\w+)_\$\d+$", type_id)
        return StorageType(
            id=type_id,
            label=contract_match.group(1) if contract_match else "contract",
            kind="contract",
            encoding="inplace",
            num_bytes=20,
        )

    hashmap_match = _HASHMAP_PATTERN.match(type_id)
    if hashmap_match:
        return StorageType(
            id=type_id,
            label=type_id,
            kind="mapping",
            encoding="mapping",
            key_type=hashmap_match.group(1).strip(),
            value_type=hashmap_match.group(2).strip(),
            num_bytes=32,
        )

    dynarray_match = _DYNARRAY_PATTERN.match(type_id)
    if dynarray_match:
        return StorageType(
            id=type_id,
            label=type_id,
            kind="array",
            encoding="dynamic_array",
            element_type=dynarray_match.group(1).strip(),
            array_length=int(dynarray_match.group(2)),
            num_bytes=32,
        )

    static_array_match = _STATIC_ARRAY_PATTERN.match(type_id)
    if static_array_match:
        element_type = static_array_match.group(1).strip()
        length = int(static_array_match.group(2))
        return StorageType(
            id=type_id,
            label=type_id,
            kind="array",
            encoding="inplace",
            element_type=element_type,
            array_length=length,
            num_bytes=32 * length,
        )

    if type_id in {"address", "bool"}:
        return StorageType(
            id=type_id,
            label=type_id,
            kind="value",
            encoding="inplace",
            num_bytes=20 if type_id == "address" else 1,
        )

    vyper_uint_match = _VYPER_UINT_PATTERN.match(type_id)
    if vyper_uint_match:
        bits = int(vyper_uint_match.group(1))
        return StorageType(
            id=type_id,
            label=f"uint{bits}",
            kind="value",
            encoding="inplace",
            num_bytes=bits // 8,
        )

    vyper_int_match = _VYPER_INT_PATTERN.match(type_id)
    if vyper_int_match:
        bits = int(vyper_int_match.group(1))
        return StorageType(
            id=type_id,
            label=f"int{bits}",
            kind="value",
            encoding="inplace",
            num_bytes=bits // 8,
        )

    vyper_bytes_match = _VYPER_BYTES_PATTERN.match(type_id)
    if vyper_bytes_match:
        width = int(vyper_bytes_match.group(1))
        return StorageType(
            id=type_id,
            label=f"bytes{width}",
            kind="value",
            encoding="inplace",
            num_bytes=width,
        )

    if type_id in {"Bytes", "String"}:
        return StorageType(
            id=type_id,
            label=type_id,
            kind="value",
            encoding="bytes",
            num_bytes=32,
        )

    return None
