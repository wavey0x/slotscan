"""Exact storage-slot algebra for mappings, arrays, and structs."""

import re
from typing import Any

from eth_abi import encode
from web3 import Web3


_UINT_RE = re.compile(r"^(?:t_)?uint(?P<bits>\d{0,3})(?:_storage)?$")
_INT_RE = re.compile(r"^(?:t_)?int(?P<bits>\d{0,3})(?:_storage)?$")
_BYTES_RE = re.compile(r"^(?:t_)?bytes(?P<size>\d+)(?:_storage)?$")


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


def encode_mapping_key(key: Any, key_type: str) -> bytes:
    """Encode one mapping key according to Solidity's storage-layout rules.

    Value types use their 32-byte ABI word. Dynamic ``bytes`` and ``string``
    are the deliberate exception: Solidity hashes their unpadded contents.
    Unknown types are rejected rather than silently being treated as bytes32.
    """
    normalized = _strip_type_id_suffix(key_type)

    if normalized in {"string", "t_string", "t_string_storage"}:
        if isinstance(key, str) and not key.startswith("0x"):
            return key.encode("utf-8")
        return _coerce_bytes(key, type_name="string")

    if normalized in {"bytes", "t_bytes", "t_bytes_storage"}:
        return _coerce_bytes(key, type_name="bytes")

    if normalized in {"address", "address payable", "t_address", "t_address_payable"} \
            or normalized.startswith("t_contract") \
            or normalized.startswith("contract ") \
            or normalized.startswith("interface "):
        try:
            address = Web3.to_checksum_address(key)
        except Exception as exc:
            raise ValueError(f"Invalid address mapping key: {key!r}") from exc
        return encode(["address"], [address])

    if normalized in {"bool", "t_bool"}:
        if isinstance(key, str):
            lowered = key.lower()
            if lowered in {"true", "1"}:
                key = True
            elif lowered in {"false", "0"}:
                key = False
            else:
                raise ValueError(f"Invalid bool mapping key: {key!r}")
        if key not in (True, False, 0, 1):
            raise ValueError(f"Invalid bool mapping key: {key!r}")
        return encode(["bool"], [bool(key)])

    uint_match = _UINT_RE.match(normalized)
    if uint_match:
        bits = int(uint_match.group("bits") or "256")
        value = int(key, 0) if isinstance(key, str) else int(key)
        if bits < 8 or bits > 256 or bits % 8 or value < 0 or value >= 2**bits:
            raise ValueError(f"Value {value} is outside uint{bits}")
        return encode([f"uint{bits}"], [value])

    int_match = _INT_RE.match(normalized)
    if int_match:
        bits = int(int_match.group("bits") or "256")
        value = int(key, 0) if isinstance(key, str) else int(key)
        if bits < 8 or bits > 256 or bits % 8 or value < -(2 ** (bits - 1)) or value >= 2 ** (bits - 1):
            raise ValueError(f"Value {value} is outside int{bits}")
        return encode([f"int{bits}"], [value])

    bytes_match = _BYTES_RE.match(normalized)
    if bytes_match:
        size = int(bytes_match.group("size"))
        if size < 1 or size > 32:
            raise ValueError(f"Invalid fixed bytes width: {size}")
        bytes_value = _coerce_bytes(key, type_name=f"bytes{size}")
        if len(bytes_value) != size:
            raise ValueError(f"bytes{size} mapping key must contain exactly {size} bytes")
        return encode([f"bytes{size}"], [bytes_value])

    # Enums are encoded as their unsigned integer value. Solc's internal enum
    # ids include a declaration-specific suffix, so the exact width is not
    # reliably present here; ABI/storage mapping encoding is still a full word.
    if normalized.startswith("t_enum") or normalized.startswith("enum "):
        value = int(key, 0) if isinstance(key, str) else int(key)
        if value < 0 or value >= 2**256:
            raise ValueError(f"Invalid enum mapping key: {key!r}")
        return encode(["uint256"], [value])

    raise ValueError(f"Unsupported mapping key type: {key_type}")


def compute_mapping_slot(base_slot: int, key: Any, key_type: str) -> int:
    """
    Compute storage slot for a mapping entry.

    Formula: keccak256(abi.encode(key, base_slot))

    Args:
        base_slot: The slot where the mapping is declared
        key: The mapping key value
        key_type: Solidity type of key ("address", "uint256", etc.)

    Returns:
        Integer slot number
    """
    encoded_key = encode_mapping_key(key, key_type)

    # Encode the slot (always uint256)
    encoded_slot = encode(["uint256"], [base_slot])

    # Concatenate key + slot and hash
    combined = encoded_key + encoded_slot
    slot_hash = Web3.keccak(combined)

    return int.from_bytes(slot_hash, "big")
