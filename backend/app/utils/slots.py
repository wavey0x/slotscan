"""Compatibility imports for storage-slot algebra used by transaction analysis."""

from typing import Any

from app.services.storage_rules import (
    compute_solidity_mapping_slot,
    encode_mapping_key as _encode_mapping_key,
)


def encode_mapping_key(key: Any, key_type: str) -> bytes:
    """Encode one mapping key without an unknown-type fallback."""
    return _encode_mapping_key(key_type, key)


def compute_mapping_slot(base_slot: int, key: Any, key_type: str) -> int:
    """Compute Solidity ``keccak256(key || slot)`` mapping storage."""
    encoded_key = encode_mapping_key(key, key_type)
    return compute_solidity_mapping_slot(base_slot, encoded_key)
