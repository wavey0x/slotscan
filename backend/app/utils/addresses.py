"""Canonical EVM address helpers."""

import re


def normalize_evm_address(value: str | int | None) -> str | None:
    """Return a lowercase, 20-byte hex address from stack/RPC representations."""
    if value is None:
        return None
    if isinstance(value, int):
        if value < 0:
            return None
        clean = f"{value:x}"
    else:
        clean = value[2:] if value.startswith(("0x", "0X")) else value
    if not clean or not re.fullmatch(r"[0-9a-fA-F]+", clean):
        return None
    return "0x" + clean[-40:].lower().zfill(40)
