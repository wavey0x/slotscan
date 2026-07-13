"""Versioned Vyper storage-allocation policy.

Vyper changed storage algebra several times during the 0.2.x line.  Keep the
version boundaries in one place so source inference and trace decoding cannot
silently apply a rule learned from one compiler era to another.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


LEGACY_HASHED_STORAGE = "vyper_legacy_hashed"
SEQUENTIAL_STORAGE = "vyper_sequential"

LOCK_SENTINEL = "sentinel_per_key"
LOCK_AFTER_GLOBALS = "after_globals_per_key"
LOCK_AFTER_STORAGE = "after_storage_per_key"
LOCK_FRONT_PER_FUNCTION = "front_per_function"
LOCK_FRONT_PER_KEY = "front_per_key"


@dataclass(frozen=True)
class VyperStoragePolicy:
    version: tuple[int, int, int] | None
    storage_scheme: str
    lock_scheme: str
    compiler_layout_supported: bool


def parse_vyper_version(value: str | None) -> tuple[int, int, int] | None:
    """Extract a semantic compiler version from Sourcify/Etherscan spellings."""
    if not value:
        return None
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", value)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def vyper_storage_policy(value: str | tuple[int, int, int] | None) -> VyperStoragePolicy:
    """Return the compiler-era storage policy for an exact Vyper version.

    Unknown versions use the modern sequential model, but callers must retain
    inferred provenance and validate it against trace evidence before display.
    """
    version = value if isinstance(value, tuple) else parse_vyper_version(value)

    if version is not None and version <= (0, 2, 8):
        scheme = LEGACY_HASHED_STORAGE
        locks = LOCK_SENTINEL
    elif version is not None and version <= (0, 2, 12):
        scheme = LEGACY_HASHED_STORAGE
        locks = LOCK_AFTER_GLOBALS
    elif version is not None and version <= (0, 2, 14):
        scheme = SEQUENTIAL_STORAGE
        locks = LOCK_AFTER_STORAGE
    elif version is not None and version <= (0, 3, 0):
        scheme = SEQUENTIAL_STORAGE
        locks = LOCK_FRONT_PER_FUNCTION
    else:
        scheme = SEQUENTIAL_STORAGE
        locks = LOCK_FRONT_PER_KEY

    return VyperStoragePolicy(
        version=version,
        storage_scheme=scheme,
        lock_scheme=locks,
        compiler_layout_supported=(
            version is not None and version >= (0, 2, 16)
        ),
    )
