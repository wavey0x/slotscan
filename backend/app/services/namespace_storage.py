"""Parser for ERC-7201 namespaced storage patterns.

Detects and parses contracts that use namespaced storage (diamond storage pattern),
where state variables are stored in a struct at a specific slot rather than
sequential slots.

Example pattern:
    bytes32 private constant SLOT = 0x1234...;
    function load() internal pure returns (MyState storage $) {
        assembly { $.slot := SLOT }
    }
"""

import re
import logging
from typing import Optional
from dataclasses import dataclass

from app.models.domain import StorageLayout, StorageType, StorageVariable

logger = logging.getLogger(__name__)


@dataclass
class NamespaceInfo:
    """Information about a detected namespace storage pattern."""
    namespace_name: str  # e.g., "AutopoolState"
    base_slot: int  # The base slot constant
    struct_name: str  # Name of the storage struct
    library_name: str  # Name of the library containing load()


@dataclass
class StructMember:
    """A parsed struct member."""
    name: str
    type_str: str
    slot_offset: int  # Offset from struct base
    byte_offset: int  # Byte offset within slot (for packed types)
    size: int  # Size in bytes


# Type sizes in bytes (simplified)
SOLIDITY_TYPE_SIZES = {
    "bool": 1,
    "uint8": 1,
    "uint16": 2,
    "uint32": 4,
    "uint64": 8,
    "uint128": 16,
    "uint256": 32,
    "int8": 1,
    "int16": 2,
    "int32": 4,
    "int64": 8,
    "int128": 16,
    "int256": 32,
    "address": 20,
    "bytes1": 1,
    "bytes4": 4,
    "bytes8": 8,
    "bytes20": 20,
    "bytes32": 32,
}

# Types that always take a full slot (complex types)
COMPLEX_TYPE_PATTERNS = [
    "mapping",
    "EnumerableSet",
    "StructuredLinkedList",
    "string",
    "bytes",  # dynamic bytes
]


class NamespaceStorageParser:
    """Parses namespaced storage patterns from Solidity source code."""

    def detect_namespace_storage(self, sources: dict[str, str]) -> list[NamespaceInfo]:
        """
        Detect namespaced storage patterns in source files.

        Looks for patterns like:
            bytes32 private constant SLOT = 0x...;
            assembly { $.slot := SLOT }
        """
        namespaces = []

        for filename, content in sources.items():
            # Look for assembly blocks that assign to $.slot
            # Pattern: assembly { $.slot := SOME_CONSTANT }
            slot_pattern = r'assembly\s*\{[^}]*\$\.slot\s*:=\s*(\w+)[^}]*\}'
            matches = re.finditer(slot_pattern, content, re.DOTALL)

            for match in matches:
                constant_name = match.group(1)

                # Find the constant definition
                const_pattern = rf'bytes32\s+(?:private\s+)?constant\s+{constant_name}\s*=\s*(0x[a-fA-F0-9]+)'
                const_match = re.search(const_pattern, content)

                if const_match:
                    slot_hex = const_match.group(1)
                    base_slot = int(slot_hex, 16)

                    # Find the library name
                    lib_pattern = r'library\s+(\w+)\s*\{'
                    lib_match = re.search(lib_pattern, content)
                    library_name = lib_match.group(1) if lib_match else "Unknown"

                    # Find the return type (struct name)
                    # Pattern: returns (StructName storage $)
                    return_pattern = r'returns\s*\(\s*(\w+)\s+storage\s+\$\s*\)'
                    return_match = re.search(return_pattern, content)
                    struct_name = return_match.group(1) if return_match else "Unknown"

                    namespaces.append(NamespaceInfo(
                        namespace_name=struct_name,
                        base_slot=base_slot,
                        struct_name=struct_name,
                        library_name=library_name,
                    ))

                    logger.info(
                        f"Detected namespace storage: {library_name}.{struct_name} "
                        f"at slot 0x{base_slot:064x}"
                    )

        return namespaces

    def find_struct_definition(
        self, struct_name: str, sources: dict[str, str]
    ) -> Optional[str]:
        """Find the struct definition in source files."""
        # Pattern: struct StructName { ... }
        # Handle nested braces
        for filename, content in sources.items():
            # Simple pattern for struct without nested structs
            pattern = rf'struct\s+{struct_name}\s*\{{([^}}]+)\}}'
            match = re.search(pattern, content, re.DOTALL)

            if match:
                return match.group(1)

            # Try pattern that handles nested braces (for complex structs)
            # This is a simplified version - may not handle all cases
            start_pattern = rf'struct\s+{struct_name}\s*\{{'
            start_match = re.search(start_pattern, content)

            if start_match:
                start_pos = start_match.end()
                brace_count = 1
                pos = start_pos

                while pos < len(content) and brace_count > 0:
                    if content[pos] == '{':
                        brace_count += 1
                    elif content[pos] == '}':
                        brace_count -= 1
                    pos += 1

                if brace_count == 0:
                    return content[start_pos:pos - 1]

        return None

    def parse_struct_members(self, struct_body: str) -> list[StructMember]:
        """
        Parse struct members and calculate storage slot offsets.

        Uses Solidity storage layout rules:
        - Each slot is 32 bytes
        - Value types < 32 bytes can pack into same slot
        - Complex types (mappings, arrays, structs) start a new slot
        - Mappings take 1 slot (base), data at keccak(key || slot)
        """
        members = []
        current_slot = 0
        current_offset = 0

        # Pattern to match struct members: type name;
        # Handle comments and whitespace
        member_pattern = r'(?:///[^\n]*\n\s*)*(\S+(?:\s*<[^>]+>)?(?:\s*\[[^\]]*\])?)\s+(\w+)\s*;'

        for match in re.finditer(member_pattern, struct_body):
            type_str = match.group(1).strip()
            name = match.group(2).strip()

            # Determine if this is a complex type
            is_complex = self._is_complex_type(type_str)

            if is_complex:
                # Start new slot for complex types
                if current_offset > 0:
                    current_slot += 1
                    current_offset = 0

                members.append(StructMember(
                    name=name,
                    type_str=type_str,
                    slot_offset=current_slot,
                    byte_offset=0,
                    size=32,  # Complex types take at least 1 slot
                ))

                # Complex types may span multiple slots, but we mark base only
                current_slot += 1

            else:
                size = self._get_type_size(type_str)

                # Check if it fits in current slot
                if current_offset + size > 32:
                    current_slot += 1
                    current_offset = 0

                members.append(StructMember(
                    name=name,
                    type_str=type_str,
                    slot_offset=current_slot,
                    byte_offset=current_offset,
                    size=size,
                ))

                current_offset += size

                if current_offset >= 32:
                    current_slot += 1
                    current_offset = 0

        return members

    def _is_complex_type(self, type_str: str) -> bool:
        """Check if a type is complex (takes full slot, can't pack)."""
        # Remove generic parameters for checking
        base_type = re.sub(r'<[^>]+>', '', type_str)
        base_type = re.sub(r'\[[^\]]*\]', '', base_type)

        for pattern in COMPLEX_TYPE_PATTERNS:
            if pattern in base_type:
                return True

        # Interface/contract types are addresses (20 bytes) but we treat them as complex
        # because they often represent pointers to other contracts
        if base_type.startswith('I') and base_type[1].isupper():
            return True

        # Struct types (contains a dot like AutopoolToken.TokenData)
        if '.' in type_str:
            return True

        return False

    def _get_type_size(self, type_str: str) -> int:
        """Get the size in bytes for a type."""
        # Check known types
        if type_str in SOLIDITY_TYPE_SIZES:
            return SOLIDITY_TYPE_SIZES[type_str]

        # Enum types - default to uint8 size
        if type_str.endswith('Status') or '.VaultShutdownStatus' in type_str:
            return 1

        # Default to 32 bytes (full slot)
        return 32

    def create_namespace_layout(
        self,
        namespace: NamespaceInfo,
        members: list[StructMember],
    ) -> StorageLayout:
        """
        Create a StorageLayout for namespaced storage.

        Variables will have slots offset by the namespace base slot.
        """
        variables = []
        types = {}

        for member in members:
            # Calculate absolute slot
            absolute_slot = namespace.base_slot + member.slot_offset

            # Create type entry
            type_id = f"t_{member.type_str.replace(' ', '_').replace('.', '_')}"

            if type_id not in types:
                is_mapping = "mapping" in member.type_str.lower()
                is_array = "[" in member.type_str

                types[type_id] = StorageType(
                    id=type_id,
                    label=member.type_str,
                    kind="mapping" if is_mapping else ("array" if is_array else "value"),
                    encoding="mapping" if is_mapping else "inplace",
                    num_bytes=member.size,
                )

            variables.append(StorageVariable(
                name=member.name,
                slot=absolute_slot,
                offset=member.byte_offset,
                size=member.size,
                type_id=type_id,
                label=member.type_str,
            ))

        return StorageLayout(
            contract_name=namespace.struct_name,
            variables=variables,
            types=types,
        )

    def parse_namespaced_storage(
        self, sources: dict[str, str]
    ) -> Optional[StorageLayout]:
        """
        Full pipeline: detect, parse, and create layout for namespaced storage.

        Returns a combined StorageLayout if namespaced storage is found.
        """
        namespaces = self.detect_namespace_storage(sources)

        if not namespaces:
            return None

        # For now, handle the first namespace found
        # TODO: Support multiple namespaces
        namespace = namespaces[0]

        struct_body = self.find_struct_definition(namespace.struct_name, sources)

        if not struct_body:
            logger.warning(f"Could not find struct definition for {namespace.struct_name}")
            return None

        members = self.parse_struct_members(struct_body)

        if not members:
            logger.warning(f"No members found in struct {namespace.struct_name}")
            return None

        layout = self.create_namespace_layout(namespace, members)

        logger.info(
            f"Created namespace layout with {len(layout.variables)} variables "
            f"for {namespace.struct_name}"
        )

        return layout
