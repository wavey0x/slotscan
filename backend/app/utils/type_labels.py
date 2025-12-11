"""Type label utilities for storage layout display."""

import re
from typing import Optional


def strip_type_prefix(label: str) -> str:
    """Strip 't_' prefix from Solidity type identifiers for display.

    Also handles t_ prefixes inside complex types like mapping(t_address,t_uint256).
    """
    if not label:
        return label

    # First strip leading t_
    result = label
    if result.startswith("t_"):
        result = result[2:]

    # Strip t_ inside parentheses (for complex types)
    # e.g., "mapping(t_address,t_uint256)" -> "mapping(address,uint256)"
    result = re.sub(r'\bt_([a-zA-Z])', r'\1', result)

    # Clean up mapping syntax: "mapping(address,uint256)" -> "mapping(address => uint256)"
    # Handle nested mappings too
    def format_mapping(m):
        inner = m.group(1)
        # Split on comma, but be careful with nested mappings
        # Simple case: just key,value
        if '(' not in inner:
            parts = inner.split(',')
            if len(parts) == 2:
                return f"mapping({parts[0].strip()} => {parts[1].strip()})"
        return m.group(0)

    result = re.sub(r'mapping\(([^)]+)\)', format_mapping, result)

    return result


def strip_struct_parent(label: str) -> str:
    """Strip parent contract/interface name from struct labels.

    e.g., "struct GovStaker.RewardData" -> "struct RewardData"
         "struct RewardDistributorMultiEpoch.RewardType[]" -> "struct RewardType[]"
         "mapping(address => struct Parent.Child)" -> "mapping(address => struct Child)"
    """
    if not label:
        return label

    # Handle struct types with parent prefix at the start
    if label.startswith("struct "):
        rest = label[7:]  # Remove "struct " prefix
        # Check for parent.Name pattern
        if "." in rest:
            # Split at last dot to handle nested types, preserve array suffix
            # e.g., "Parent.Child[]" -> "Child[]"
            parts = rest.rsplit(".", 1)
            return f"struct {parts[1]}"
        return label

    # Handle struct references embedded in complex types (mappings, arrays, etc.)
    # e.g., "mapping(address => struct Parent.Child)"
    def replace_struct(match):
        struct_type = match.group(1)  # e.g., "Parent.Child" or "Parent.Child[]"
        if "." in struct_type:
            # Strip parent, preserve suffix (like [])
            parts = struct_type.rsplit(".", 1)
            return f"struct {parts[1]}"
        return match.group(0)  # Return unchanged if no parent

    # Find and replace all "struct Parent.Child" patterns
    result = re.sub(r'struct\s+([A-Za-z0-9_.]+(?:\[\])?)', replace_struct, label)
    return result


def clean_type_label(label: str) -> str:
    """Clean a type label for display: strip t_ prefix and struct parent names."""
    result = strip_type_prefix(label)
    return strip_struct_parent(result)


def normalize_contract_label(label: str, kind: Optional[str] = None) -> str:
    """Convert contract/interface labels to address for display.

    Contract types (ERC20, IERC20, contract Foo, etc.) are all stored as addresses
    in the EVM, so we display them as "address" for clarity.

    Args:
        label: The type label (e.g., "ERC20", "contract IERC20", "address")
        kind: The StorageType.kind value (e.g., "contract", "value")

    Returns:
        "address" for contract types, cleaned label otherwise
    """
    # Check if kind explicitly indicates this is a contract type
    if kind and kind.lower() == "contract":
        return "address"

    # Check if label indicates a contract/interface type
    if label:
        label_lower = label.lower()
        # "contract Foo" or "contract(Foo)"
        if label_lower.startswith("contract"):
            return "address"
        # Common interface patterns: IERC20, ERC20, ERC721, etc.
        # These are contract types that Vyper/Solidity stores as addresses
        if label_lower.startswith("ierc") or label_lower.startswith("erc"):
            return "address"

    return clean_type_label(label) if label else label
