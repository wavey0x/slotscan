"""Slot computation utilities for mappings, arrays, and structs."""

from typing import Any, Tuple

from eth_abi import encode
from web3 import Web3


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
    # Encode the key based on type
    key_type_lower = key_type.lower()

    if "address" in key_type_lower:
        if isinstance(key, str):
            key = Web3.to_checksum_address(key)
        encoded_key = encode(["address"], [key])

    elif "uint" in key_type_lower or key_type_lower.startswith("t_uint"):
        encoded_key = encode(["uint256"], [int(key)])

    elif "int" in key_type_lower and "uint" not in key_type_lower:
        encoded_key = encode(["int256"], [int(key)])

    elif "bytes32" in key_type_lower:
        if isinstance(key, str) and key.startswith("0x"):
            key = bytes.fromhex(key[2:])
        encoded_key = encode(["bytes32"], [key])

    elif "bytes" in key_type_lower and "bytes32" not in key_type_lower:
        if isinstance(key, str) and key.startswith("0x"):
            key = bytes.fromhex(key[2:])
        elif isinstance(key, str):
            key = key.encode()
        encoded_key = encode(["bytes"], [key])

    else:
        # Default to bytes32
        if isinstance(key, str) and key.startswith("0x"):
            key = bytes.fromhex(key[2:].zfill(64))
        encoded_key = encode(["bytes32"], [key])

    # Encode the slot (always uint256)
    encoded_slot = encode(["uint256"], [base_slot])

    # Concatenate key + slot and hash
    combined = encoded_key + encoded_slot
    slot_hash = Web3.keccak(combined)

    return int.from_bytes(slot_hash, "big")


def compute_mapping_slot_hex(base_slot: int, key: Any, key_type: str) -> str:
    """Convenience: compute mapping slot and return hex string."""
    return hex(compute_mapping_slot(base_slot, key, key_type))


def compute_nested_mapping_slot(
    base_slot: int, keys: list[tuple[Any, str]]
) -> int:
    """
    Compute slot for nested mapping: mapping(K1 => mapping(K2 => V))

    Args:
        base_slot: Base slot of outermost mapping
        keys: List of (key_value, key_type) tuples, outer to inner

    Returns:
        Final slot number
    """
    current_slot = base_slot
    for key, key_type in keys:
        current_slot = compute_mapping_slot(current_slot, key, key_type)
    return current_slot


def compute_dynamic_array_slot(base_slot: int, index: int, element_slots: int = 1) -> int:
    """
    Compute storage slot for a dynamic array element.

    Array length is stored at base_slot.
    Elements start at keccak256(base_slot).

    Args:
        base_slot: The slot where array length is stored
        index: Array index (0-based)
        element_slots: Number of slots per element

    Returns:
        Slot number for the element
    """
    encoded_slot = encode(["uint256"], [base_slot])
    data_start = int.from_bytes(Web3.keccak(encoded_slot), "big")
    return data_start + (index * element_slots)


def compute_static_array_slot(base_slot: int, index: int, element_slots: int = 1) -> int:
    """
    Compute storage slot for a static array element.

    Static arrays store elements contiguously from base_slot.

    Args:
        base_slot: The starting slot of the array
        index: Array index (0-based)
        element_slots: Number of slots per element

    Returns:
        Slot number for the element
    """
    return base_slot + (index * element_slots)


def compute_struct_field_slot(
    base_slot: int, field_slot_offset: int, field_byte_offset: int = 0
) -> Tuple[int, int]:
    """
    Compute slot and byte offset for a struct field.

    Args:
        base_slot: Starting slot of the struct
        field_slot_offset: Slot offset of field within struct
        field_byte_offset: Byte offset within the slot

    Returns:
        (slot_number, byte_offset_within_slot)
    """
    return (base_slot + field_slot_offset, field_byte_offset)


def compute_string_data_slot(base_slot: int) -> int:
    """
    Compute the starting slot for string/bytes data.

    For strings > 31 bytes, data starts at keccak256(base_slot).
    """
    encoded_slot = encode(["uint256"], [base_slot])
    return int.from_bytes(Web3.keccak(encoded_slot), "big")
