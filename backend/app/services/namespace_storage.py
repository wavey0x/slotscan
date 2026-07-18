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
import hashlib
from math import ceil
from typing import Optional
from dataclasses import dataclass

from web3 import Web3

from app.models.domain import (
    StorageLayout,
    StorageScope,
    StorageType,
    StorageVariable,
)
from app.utils.vyper import (
    LEGACY_HASHED_STORAGE,
    LOCK_AFTER_GLOBALS,
    LOCK_AFTER_STORAGE,
    LOCK_FRONT_PER_FUNCTION,
    LOCK_FRONT_PER_KEY,
    LOCK_SENTINEL,
    vyper_storage_policy,
)

logger = logging.getLogger(__name__)


@dataclass
class NamespaceInfo:
    """Information about a detected namespace storage pattern."""
    namespace_name: str  # e.g., "AutopoolState"
    base_slot: int  # The base slot constant
    struct_name: str  # Name of the storage struct
    library_name: str  # Name of the library containing load()
    storage_type: str = ""
    variable_name: str = ""


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

# Known library type slot counts - ONLY for well-known standard libraries
# with guaranteed stable storage layouts. Everything else is parsed from source.
STANDARD_LIBRARY_SLOT_COUNTS = {
    # OpenZeppelin EnumerableSet - always 2 slots: _values[] + _indexes mapping
    "EnumerableSet": 2,
    # Solidity primitives that use 1 slot for metadata
    "mapping": 1,
    "string": 1,
    "bytes": 1,
}

ERC7201_HARNESS_SOURCE = "__slotscan__/NamespaceHarness.sol"
ERC7201_HARNESS_CONTRACT = "SlotScanNamespaceHarness"


def compute_erc7201_root(identifier: str) -> int:
    """Return the ERC-7201 root for one namespace identifier."""
    first_hash = int.from_bytes(Web3.keccak(text=identifier), "big")
    encoded = ((first_hash - 1) % (1 << 256)).to_bytes(32, "big")
    return int.from_bytes(Web3.keccak(encoded), "big") & ~0xFF


class NamespaceStorageParser:
    """Parses namespaced storage patterns from Solidity source code."""

    def detect_namespace_storage(self, sources: dict[str, str]) -> list[NamespaceInfo]:
        """
        Detect namespaced storage patterns in source files.

        Looks for patterns like:
            bytes32 private constant SLOT = 0x...;
            assembly { $.slot := SLOT }
        """
        namespaces: list[NamespaceInfo] = []
        constants = self.extract_slot_constants(sources)

        for filename, content in sources.items():
            function_pattern = re.compile(r"function\s+(?P<name>\w+)\s*\(")
            for function_match in function_pattern.finditer(content):
                opening_brace = content.find("{", function_match.end())
                semicolon = content.find(";", function_match.end())
                if opening_brace < 0 or (semicolon >= 0 and semicolon < opening_brace):
                    continue
                header = content[function_match.end():opening_brace]
                returns_match = re.search(r"\breturns\s*\(", header)
                if not returns_match:
                    continue
                return_open = returns_match.end() - 1
                depth = 0
                return_close = None
                for position in range(return_open, len(header)):
                    if header[position] == "(":
                        depth += 1
                    elif header[position] == ")":
                        depth -= 1
                        if depth == 0:
                            return_close = position
                            break
                if return_close is None:
                    continue
                return_match = re.fullmatch(
                    r"\s*(?P<type>.+?)\s+storage\s+(?P<name>[\w$]+)\s*",
                    header[return_open + 1:return_close],
                    re.DOTALL,
                )
                if not return_match:
                    continue
                body = self._balanced_body(content, opening_brace)
                if body is None:
                    continue
                return_name = return_match.group("name")
                assignment = re.search(
                    rf"(?<!\w){re.escape(return_name)}\.slot\s*:=\s*(\w+)",
                    body,
                )
                if not assignment:
                    continue
                slot_reference = assignment.group(1)
                local_alias = re.search(
                    rf"bytes32\s+{re.escape(slot_reference)}\s*=\s*(\w+)\s*;",
                    body,
                )
                if local_alias:
                    slot_reference = local_alias.group(1)
                base_slot = constants.get(slot_reference)
                if base_slot is None:
                    continue

                storage_type = re.sub(r"\s+", " ", return_match.group("type").strip())
                struct_name = storage_type.split(".")[-1]
                library_match = re.search(r"library\s+(\w+)\s*\{", content)
                namespace = NamespaceInfo(
                    namespace_name=struct_name,
                    base_slot=base_slot,
                    struct_name=struct_name,
                    library_name=library_match.group(1) if library_match else "Unknown",
                    storage_type=storage_type,
                    variable_name=return_name,
                )
                if not any(
                    existing.base_slot == namespace.base_slot
                    and existing.variable_name == namespace.variable_name
                    for existing in namespaces
                ):
                    namespaces.append(namespace)
                    logger.info(
                        "Detected source storage %s at slot 0x%064x",
                        storage_type,
                        base_slot,
                    )

        return namespaces

    @staticmethod
    def _balanced_body(content: str, opening_brace: int) -> Optional[str]:
        depth = 0
        for position in range(opening_brace, len(content)):
            if content[position] == "{":
                depth += 1
            elif content[position] == "}":
                depth -= 1
                if depth == 0:
                    return content[opening_brace + 1:position]
        return None

    def extract_slot_constants(self, sources: dict[str, str]) -> dict[str, int]:
        """Evaluate deterministic bytes32 storage-position constants."""
        expressions: dict[str, str] = {}
        pattern = re.compile(
            r"bytes32\s+(?:(?:public|private|internal)\s+)*constant\s+"
            r"(?P<name>\w+)\s*=\s*(?P<expr>.*?);",
            re.DOTALL,
        )
        for content in sources.values():
            for match in pattern.finditer(content):
                expressions[match.group("name")] = match.group("expr").strip()

        resolved: dict[str, int] = {}

        def evaluate(name: str, stack: set[str]) -> Optional[int]:
            if name in resolved:
                return resolved[name]
            if name in stack or name not in expressions:
                return None
            expression = expressions[name]
            compact = re.sub(r"\s+", "", expression)
            value: Optional[int] = None
            if re.fullmatch(r"0x[a-fA-F0-9]+", compact):
                value = int(compact, 16)
            else:
                erc7201 = re.fullmatch(
                    r"keccak256\(abi\.encode\(uint256\(keccak256\(\"([^\"]+)\"\)\)-1\)\)"
                    r"&~bytes32\(uint256\(0xff\)\)",
                    compact,
                )
                if erc7201:
                    value = compute_erc7201_root(erc7201.group(1))
                literal = re.search(r'keccak256\((?:bytes\()?"([^"]+)"\)?\)', compact)
                if value is None and literal:
                    value = int.from_bytes(Web3.keccak(text=literal.group(1)), "big")
                    if re.search(r"-1\)*$", compact):
                        value -= 1
                elif value is None and re.fullmatch(r"\w+", compact):
                    value = evaluate(compact, stack | {name})
            if value is not None:
                resolved[name] = value % (1 << 256)
            return value

        for constant_name in expressions:
            evaluate(constant_name, set())
        return resolved

    @staticmethod
    def _ast_nodes(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from NamespaceStorageParser._ast_nodes(child)
        elif isinstance(value, list):
            for child in value:
                yield from NamespaceStorageParser._ast_nodes(child)

    @staticmethod
    def _documentation_text(node: dict) -> str:
        documentation = node.get("documentation")
        if isinstance(documentation, str):
            return documentation
        if isinstance(documentation, dict):
            text = documentation.get("text")
            return text if isinstance(text, str) else ""
        return ""

    @staticmethod
    def _compiler_version_at_least_0820(version: Optional[str]) -> bool:
        if not version:
            return False
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", version)
        if not match:
            return False
        return tuple(int(part) for part in match.groups()) >= (0, 8, 20)

    def build_exact_erc7201_harness(
        self,
        compiler_output: dict,
    ) -> Optional[str]:
        """Build compiler-only declarations that expose annotated struct layouts."""
        declarations: list[tuple[str, str]] = []
        for filename, source_output in sorted(
            (compiler_output.get("sources") or {}).items()
        ):
            if (
                not isinstance(filename, str)
                or any(character in filename for character in {'"', "\n", "\r", "\0"})
                or not isinstance(source_output, dict)
                or not isinstance(source_output.get("ast"), dict)
            ):
                continue
            for node in self._ast_nodes(source_output["ast"]):
                if node.get("nodeType") != "StructDefinition":
                    continue
                if not re.search(
                    r"@custom:storage-location\s+erc7201:([^\s*]+)",
                    self._documentation_text(node),
                ):
                    continue
                canonical_name = node.get("canonicalName") or node.get("name")
                if not isinstance(canonical_name, str) or not re.fullmatch(
                    r"[A-Za-z_$][A-Za-z0-9_$]*"
                    r"(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*",
                    canonical_name,
                ):
                    continue
                declarations.append((filename, canonical_name))

        declarations = sorted(set(declarations))
        if not declarations:
            return None

        filenames = sorted({filename for filename, _ in declarations})
        aliases = {
            filename: f"SlotScanSource{index}"
            for index, filename in enumerate(filenames)
        }
        imports = [
            f'import * as {aliases[filename]} from "{filename}";'
            for filename in filenames
        ]
        variables = [
            (
                f"    {aliases[filename]}.{canonical_name} private "
                f"namespace_{index};"
            )
            for index, (filename, canonical_name) in enumerate(declarations)
        ]
        return "\n".join(
            (
                "pragma solidity >=0.8.20;",
                *imports,
                f"contract {ERC7201_HARNESS_CONTRACT} {{",
                *variables,
                "}",
            )
        )

    @staticmethod
    def _type_occupancy(
        type_info: StorageType,
    ) -> tuple[int, int]:
        if type_info.encoding in {"mapping", "dynamic_array", "bytes"}:
            return 1, 32
        size = type_info.num_bytes or 32
        return max(1, ceil(size / 32)), min(size, 32)

    def promote_exact_erc7201(
        self,
        layout: StorageLayout,
        *,
        compiler_output: dict,
        sources: dict[str, str],
        compiler_version: Optional[str],
        max_slots: int,
    ) -> StorageLayout:
        """Promote namespaces only when AST, root, pointer, and type graph agree."""
        if max_slots <= 0:
            return layout
        if not self._compiler_version_at_least_0820(compiler_version):
            return layout
        ast_roots = [
            source.get("ast")
            for source in (compiler_output.get("sources") or {}).values()
            if isinstance(source, dict) and isinstance(source.get("ast"), dict)
        ]
        if not ast_roots:
            return layout

        pointer_namespaces = self.detect_namespace_storage(sources)
        variables = list(layout.variables)
        scopes = {scope.id: scope for scope in layout.scopes}

        for ast_root in ast_roots:
            for node in self._ast_nodes(ast_root):
                if node.get("nodeType") != "StructDefinition":
                    continue
                annotation = re.search(
                    r"@custom:storage-location\s+erc7201:([^\s*]+)",
                    self._documentation_text(node),
                )
                if not annotation:
                    continue
                identifier = annotation.group(1)
                root = compute_erc7201_root(identifier)
                struct_name = node.get("name")
                canonical_name = node.get("canonicalName") or struct_name
                pointer = next(
                    (
                        namespace
                        for namespace in pointer_namespaces
                        if namespace.base_slot == root
                        and namespace.struct_name == struct_name
                    ),
                    None,
                )
                if pointer is None:
                    continue

                type_matches = [
                    type_info
                    for type_info in layout.types.values()
                    if type_info.kind == "struct"
                    and type_info.members
                    and (
                        type_info.label.removeprefix("struct ") == canonical_name
                        or type_info.label.removeprefix("struct ").endswith(
                            f".{struct_name}"
                        )
                        or type_info.label.removeprefix("struct ") == struct_name
                    )
                ]
                if len(type_matches) != 1:
                    continue
                struct_type = type_matches[0]
                occupied: set[tuple[int, int]] = set()
                exact_members: list[StorageVariable] = []
                valid = True
                scope_id = f"erc7201:{identifier}"
                for member in struct_type.members or ():
                    member_type = layout.types.get(member.type_id)
                    if member_type is None:
                        valid = False
                        break
                    slot_count, first_word_size = self._type_occupancy(member_type)
                    if (
                        member.slot < 0
                        or slot_count > max_slots
                        or member.slot + slot_count > max_slots
                    ):
                        valid = False
                        break
                    absolute_slot = root + member.slot
                    if absolute_slot >= 1 << 256 or absolute_slot + slot_count > 1 << 256:
                        valid = False
                        break
                    for relative in range(slot_count):
                        byte_start = member.offset if relative == 0 else 0
                        byte_size = (
                            min(member.size, first_word_size)
                            if relative == 0
                            else 32
                        )
                        for byte in range(byte_start, byte_start + byte_size):
                            key = (absolute_slot + relative, byte)
                            if byte >= 32 or key in occupied:
                                valid = False
                                break
                            occupied.add(key)
                        if not valid:
                            break
                    if not valid:
                        break
                    exact_members.append(
                        StorageVariable(
                            name=member.name,
                            slot=absolute_slot,
                            offset=member.offset,
                            size=member.size,
                            type_id=member.type_id,
                            label=member.label,
                            provenance="compiler_layout",
                            confidence="exact",
                            scope_id=scope_id,
                        )
                    )
                if not valid:
                    continue

                inferred_scope_ids = {
                    scope.id
                    for scope in scopes.values()
                    if scope.root_slot == root
                    and scope.kind in {"custom", "unstructured"}
                    and scope.confidence != "exact"
                }
                variables = [
                    variable
                    for variable in variables
                    if variable.scope_id not in inferred_scope_ids
                ]
                for inferred_scope_id in inferred_scope_ids:
                    scopes.pop(inferred_scope_id, None)
                variables.extend(exact_members)
                scopes[scope_id] = StorageScope(
                    id=scope_id,
                    kind="erc7201",
                    root_slot=root,
                    formula=f"erc7201:{identifier}",
                    provenance="compiler_layout",
                    confidence="exact",
                )

        return StorageLayout(
            contract_name=layout.contract_name,
            variables=variables,
            types=layout.types,
            language=layout.language,
            compiler_version=layout.compiler_version,
            storage_scheme=layout.storage_scheme,
            scopes=list(scopes.values()),
        )

    def find_struct_definition(
        self, struct_name: str, sources: dict[str, str]
    ) -> Optional[str]:
        """Find the struct definition in source files."""
        # Always use balanced braces. NatSpec/comments can contain examples
        # such as ``{report}``, which makes a first-``}`` regex truncate an
        # otherwise simple struct.
        for filename, content in sources.items():
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

    def parse_struct_members(
        self,
        struct_body: str,
        sources: Optional[dict[str, str]] = None,
    ) -> list[StructMember]:
        """
        Parse struct members and calculate storage slot offsets.

        Uses Solidity storage layout rules:
        - Each slot is 32 bytes
        - Value types < 32 bytes can pack into same slot
        - Complex types (mappings, arrays, structs) start a new slot
        - Mappings take 1 slot (base), data at keccak(key || slot)

        Args:
            struct_body: The content inside the struct braces
            sources: All source files (for recursive struct parsing)
        """
        members = []
        current_slot = 0
        current_offset = 0
        slot_count_cache: dict[str, int] = {}

        # Pattern to match struct members: type name;
        # Handle comments and whitespace
        # Must handle complex types like:
        #   mapping(address => uint256)
        #   mapping(address => mapping(address => uint256))
        #   EnumerableSet.AddressSet
        #   uint256
        # We capture everything up to the last identifier before the semicolon
        member_pattern = r'(?:///[^\n]*\n\s*)*([^;\n]+?)\s+(\w+)\s*;'

        for match in re.finditer(member_pattern, struct_body):
            type_str = match.group(1).strip()
            name = match.group(2).strip()

            # Determine if this is a complex type
            is_complex = self._is_complex_type(type_str, sources or {})

            if is_complex:
                # Start new slot for complex types
                if current_offset > 0:
                    current_slot += 1
                    current_offset = 0

                # Get slot count for this complex type (recursively parses nested structs)
                slot_count = self._get_complex_type_slots(
                    type_str,
                    sources or {},
                    slot_count_cache,
                )

                members.append(StructMember(
                    name=name,
                    type_str=type_str,
                    slot_offset=current_slot,
                    byte_offset=0,
                    size=32 * slot_count,  # Size in bytes
                ))

                # Advance by the number of slots this type occupies
                current_slot += slot_count

            else:
                size = self._get_type_size(type_str, sources or {})

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

    def _is_complex_type(
        self,
        type_str: str,
        sources: Optional[dict[str, str]] = None,
    ) -> bool:
        """Check if a type is complex (takes full slot, can't pack)."""
        if "[" in type_str or type_str.strip().startswith("mapping"):
            return True
        # Remove generic parameters for checking
        base_type = re.sub(r'<[^>]+>', '', type_str)
        base_type = re.sub(r'\[[^\]]*\]', '', base_type)

        for pattern in COMPLEX_TYPE_PATTERNS:
            if pattern in base_type:
                return True

        # Interface/contract values use the same 20-byte representation as an
        # address and may pack with adjacent value types.
        if base_type.startswith('I') and len(base_type) > 1 and base_type[1].isupper():
            return False

        # Struct types (contains a dot like AutopoolToken.TokenData)
        if '.' in type_str:
            return True

        if sources and type_str and type_str[0].isupper():
            return self.find_struct_definition(type_str.split(".")[-1], sources) is not None

        return False

    def _get_type_size(
        self,
        type_str: str,
        sources: Optional[dict[str, str]] = None,
    ) -> int:
        """Get the size in bytes for a type."""
        # Check known types
        if type_str in SOLIDITY_TYPE_SIZES:
            return SOLIDITY_TYPE_SIZES[type_str]

        integer_match = re.fullmatch(r"u?int(\d*)", type_str)
        if integer_match:
            bits = int(integer_match.group(1) or "256")
            return bits // 8

        bytes_match = re.fullmatch(r"bytes(\d+)", type_str)
        if bytes_match:
            return int(bytes_match.group(1))

        if (
            (type_str.startswith("I") and len(type_str) > 1 and type_str[1].isupper())
            or type_str.startswith("contract ")
        ):
            return 20

        if type_str and type_str[0].isupper() and not (
            sources and self.find_struct_definition(type_str.split(".")[-1], sources)
        ):
            return 20

        # Enum types - default to uint8 size
        if type_str.endswith('Status') or '.VaultShutdownStatus' in type_str:
            return 1

        # Default to 32 bytes (full slot)
        return 32

    def _get_complex_type_slots(
        self,
        type_str: str,
        sources: dict[str, str],
        cache: Optional[dict[str, int]] = None,
    ) -> int:
        """
        Get number of storage slots a complex type occupies.

        For struct types, recursively parses their definitions from source.
        Results are cached to avoid re-parsing.
        """
        if cache is None:
            cache = {}

        # Check cache first
        if type_str in cache:
            return cache[type_str]

        # Check standard library types (well-known, stable layouts)
        for lib_pattern, slot_count in STANDARD_LIBRARY_SLOT_COUNTS.items():
            if lib_pattern in type_str:
                cache[type_str] = slot_count
                return slot_count

        static_array_match = re.fullmatch(r"(.+)\[(\d+)\]", type_str.strip())
        if static_array_match:
            element_name = static_array_match.group(1).strip()
            length = int(static_array_match.group(2))
            if self._is_complex_type(element_name, sources):
                element_slots = self._get_complex_type_slots(element_name, sources, cache)
                slot_count = length * element_slots
            else:
                element_size = self._get_type_size(element_name, sources)
                slot_count = (length * element_size + 31) // 32
            cache[type_str] = max(1, slot_count)
            return cache[type_str]

        if "[]" in type_str or type_str.strip().startswith("mapping"):
            cache[type_str] = 1
            return 1

        # Struct types (e.g., "AutopoolToken.TokenData" or "TokenData")
        # Try to find and parse the struct definition from source
        if '.' in type_str or type_str[0].isupper():
            # Extract struct name (last part after dot, or full name)
            struct_name = type_str.split('.')[-1] if '.' in type_str else type_str

            # Try to find the struct definition
            struct_body = self.find_struct_definition(struct_name, sources)

            if struct_body:
                # Recursively calculate slot count for this struct
                slot_count = self._calculate_struct_slot_count(struct_body, sources, cache)
                cache[type_str] = slot_count
                logger.debug(f"Parsed struct {type_str}: {slot_count} slots")
                return slot_count
            else:
                # Struct definition not found - default to 1 slot
                logger.debug(f"Struct definition not found for {type_str}, defaulting to 1 slot")
                cache[type_str] = 1
                return 1

        # Default: 1 slot
        cache[type_str] = 1
        return 1

    def _calculate_struct_slot_count(
        self,
        struct_body: str,
        sources: dict[str, str],
        cache: dict[str, int],
    ) -> int:
        """Calculate total slots occupied by a struct from its body."""
        current_slot = 0
        current_byte_offset = 0

        # Pattern to match struct members
        member_pattern = r'(?:///[^\n]*\n\s*)*([^;\n]+?)\s+(\w+)\s*;'

        for match in re.finditer(member_pattern, struct_body):
            type_str = match.group(1).strip()

            is_complex = self._is_complex_type(type_str, sources)

            if is_complex:
                # Complex types start on new slot
                if current_byte_offset > 0:
                    current_slot += 1
                    current_byte_offset = 0

                slot_count = self._get_complex_type_slots(type_str, sources, cache)
                current_slot += slot_count

            else:
                size = self._get_type_size(type_str, sources)

                if current_byte_offset + size > 32:
                    current_slot += 1
                    current_byte_offset = 0

                current_byte_offset += size

                if current_byte_offset >= 32:
                    current_slot += 1
                    current_byte_offset = 0

        # Account for any remaining bytes in the last slot
        if current_byte_offset > 0:
            current_slot += 1

        return max(1, current_slot)

    def create_namespace_layout(
        self,
        namespace: NamespaceInfo,
        members: list[StructMember],
        sources: Optional[dict[str, str]] = None,
    ) -> StorageLayout:
        """
        Create a StorageLayout for namespaced storage.

        Variables will have slots offset by the namespace base slot.
        """
        variables: list[StorageVariable] = []
        types: dict[str, StorageType] = {}
        scope_id = f"namespace:{namespace.base_slot:064x}"

        for member in members:
            # Calculate absolute slot
            absolute_slot = namespace.base_slot + member.slot_offset

            type_id = self._ensure_source_type(member.type_str, types, sources or {})

            variables.append(StorageVariable(
                name=member.name,
                slot=absolute_slot,
                offset=member.byte_offset,
                size=member.size,
                type_id=type_id,
                label=member.type_str,
                provenance="source_inference",
                confidence="inferred",
                scope_id=scope_id,
            ))

        return StorageLayout(
            contract_name=namespace.struct_name,
            variables=variables,
            types=types,
            language="Solidity",
            scopes=[
                StorageScope("default", "default", 0),
                StorageScope(
                    id=scope_id,
                    kind="custom",
                    root_slot=namespace.base_slot,
                    formula=None,
                    provenance="source_inference",
                    confidence="inferred",
                ),
            ],
        )

    @staticmethod
    def _source_type_id(type_str: str) -> str:
        normalized = re.sub(r"\s+", " ", type_str.strip())
        primitive = {
            "uint": "t_uint256",
            "int": "t_int256",
            "address payable": "t_address",
        }.get(normalized, f"t_{normalized}")
        if re.fullmatch(r"t_(?:u?int\d*|address|bool|bytes\d*)", primitive):
            return primitive
        digest = hashlib.sha256(normalized.encode()).hexdigest()[:16]
        return f"t_source_{digest}"

    @staticmethod
    def _mapping_parts(type_str: str) -> Optional[tuple[str, str]]:
        normalized = type_str.strip()
        if not normalized.startswith("mapping"):
            return None
        opening = normalized.find("(")
        if opening < 0 or not normalized.endswith(")"):
            return None
        inner = normalized[opening + 1:-1]
        depth = 0
        for index in range(len(inner) - 1):
            char = inner[index]
            if char in "([":
                depth += 1
            elif char in ")]":
                depth -= 1
            elif inner[index:index + 2] == "=>" and depth == 0:
                return inner[:index].strip(), inner[index + 2:].strip()
        return None

    def _ensure_source_type(
        self,
        type_str: str,
        types: dict[str, StorageType],
        sources: dict[str, str],
    ) -> str:
        normalized = re.sub(r"\s+", " ", type_str.strip())
        aliases = {"uint": "uint256", "int": "int256", "address payable": "address"}
        normalized = aliases.get(normalized, normalized)
        type_id = self._source_type_id(normalized)
        if type_id in types:
            return type_id

        mapping_parts = self._mapping_parts(normalized)
        if mapping_parts:
            key, value = mapping_parts
            key_id = self._ensure_source_type(key, types, sources)
            value_id = self._ensure_source_type(value, types, sources)
            types[type_id] = StorageType(
                id=type_id,
                label=normalized,
                kind="mapping",
                encoding="mapping",
                num_bytes=32,
                key_type=key_id,
                value_type=value_id,
            )
            return type_id

        array_match = re.fullmatch(r"(.+)\[(\d*)\]", normalized)
        if array_match:
            element_name, length_text = array_match.groups()
            element_id = self._ensure_source_type(element_name.strip(), types, sources)
            array_length = int(length_text) if length_text else None
            element_type = types[element_id]
            if array_length is None:
                num_bytes = 32
            elif element_type.num_bytes and element_type.num_bytes < 32:
                num_bytes = ((element_type.num_bytes * array_length + 31) // 32) * 32
            else:
                element_slots = max(1, (element_type.num_bytes or 32) // 32)
                num_bytes = 32 * element_slots * array_length
            types[type_id] = StorageType(
                id=type_id,
                label=normalized,
                kind="array",
                encoding="dynamic_array" if array_length is None else "inplace",
                num_bytes=num_bytes,
                element_type=element_id,
                array_length=array_length,
            )
            return type_id

        struct_name = normalized.split(".")[-1]
        struct_body = self.find_struct_definition(struct_name, sources)
        if struct_body:
            # Install a placeholder before recursing so self-referential source
            # types cannot loop forever.
            types[type_id] = StorageType(
                id=type_id,
                label=f"struct {normalized}",
                kind="struct",
                encoding="inplace",
                num_bytes=32,
                members=[],
            )
            parsed_members = self.parse_struct_members(struct_body, sources)
            storage_members: list[StorageVariable] = []
            for member in parsed_members:
                member_type_id = self._ensure_source_type(member.type_str, types, sources)
                member_type = types[member_type_id]
                if member_type.kind == "struct" and member_type.members:
                    for nested in member_type.members:
                        storage_members.append(StorageVariable(
                            name=f"{member.name}.{nested.name}",
                            slot=member.slot_offset + nested.slot,
                            offset=nested.offset,
                            size=nested.size,
                            type_id=nested.type_id,
                            label=nested.label,
                            provenance="source_inference",
                            confidence="inferred",
                        ))
                else:
                    storage_members.append(StorageVariable(
                        name=member.name,
                        slot=member.slot_offset,
                        offset=member.byte_offset,
                        size=member.size,
                        type_id=member_type_id,
                        label=member.type_str,
                        provenance="source_inference",
                        confidence="inferred",
                    ))
            slot_count = max(
                (
                    member.slot + max(1, (member.size + 31) // 32)
                    for member in storage_members
                ),
                default=1,
            )
            types[type_id].members = storage_members
            types[type_id].num_bytes = slot_count * 32
            return type_id

        primitive_sizes = {
            "bool": 1,
            "address": 20,
            "string": 32,
            "bytes": 32,
        }
        size = primitive_sizes.get(normalized)
        integer_match = re.fullmatch(r"u?int(\d*)", normalized)
        fixed_bytes_match = re.fullmatch(r"bytes(\d+)", normalized)
        if integer_match:
            size = int(integer_match.group(1) or "256") // 8
        elif fixed_bytes_match:
            size = int(fixed_bytes_match.group(1))
        elif size is None and normalized and normalized[0].isupper():
            size = 20
        size = size or 32
        types[type_id] = StorageType(
            id=type_id,
            label=normalized,
            kind="contract" if normalized and normalized[0].isupper() else "value",
            encoding="bytes" if normalized in {"string", "bytes"} else "inplace",
            num_bytes=size,
        )
        return type_id

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

        variables = []
        types = {}
        scopes: dict[str, StorageScope] = {
            "default": StorageScope("default", "default", 0)
        }
        names = []
        for namespace in namespaces:
            if namespace.storage_type.strip().startswith("mapping"):
                namespace_types: dict[str, StorageType] = {}
                type_id = self._ensure_source_type(
                    namespace.storage_type,
                    namespace_types,
                    sources,
                )
                variable_name = namespace.variable_name or namespace.namespace_name
                scope_id = f"namespace:{namespace.base_slot:064x}"
                namespace_layout = StorageLayout(
                    contract_name=variable_name,
                    variables=[StorageVariable(
                        name=variable_name,
                        slot=namespace.base_slot,
                        offset=0,
                        size=32,
                        type_id=type_id,
                        label=namespace.storage_type,
                        provenance="source_inference",
                        confidence="inferred",
                        scope_id=scope_id,
                    )],
                    types=namespace_types,
                    scopes=[
                        StorageScope("default", "default", 0),
                        StorageScope(
                            id=scope_id,
                            kind="custom",
                            root_slot=namespace.base_slot,
                            provenance="source_inference",
                            confidence="inferred",
                        ),
                    ],
                )
            else:
                struct_body = self.find_struct_definition(namespace.struct_name, sources)
                if not struct_body:
                    logger.warning(f"Could not find struct definition for {namespace.struct_name}")
                    continue
                members = self.parse_struct_members(struct_body, sources)
                if not members:
                    logger.warning(f"No members found in struct {namespace.struct_name}")
                    continue
                namespace_layout = self.create_namespace_layout(namespace, members, sources)
            variables.extend(namespace_layout.variables)
            types.update(namespace_layout.types)
            scopes.update({scope.id: scope for scope in namespace_layout.scopes})
            names.append(namespace.struct_name)

        if not variables:
            return None
        logger.info(
            "Created inferred layouts for %s namespaces with %s variables",
            len(names),
            len(variables),
        )
        return StorageLayout(
            contract_name=" + ".join(names),
            variables=variables,
            types=types,
            language="Solidity",
            scopes=list(scopes.values()),
        )

    @staticmethod
    def _constant_variable_name(name: str) -> str:
        for suffix in ("_POSITION", "_SLOT"):
            if name.endswith(suffix):
                name = name[:-len(suffix)]
                break
        parts = [part.lower() for part in name.split("_") if part]
        return parts[0] + "".join(part.title() for part in parts[1:]) if parts else name

    def parse_unstructured_constants(
        self,
        sources: dict[str, str],
    ) -> Optional[StorageLayout]:
        """Infer direct unstructured value slots from verified source usage."""
        constants = self.extract_slot_constants(sources)
        if not constants:
            return None
        combined = "\n".join(sources.values())
        variables: list[StorageVariable] = []
        types: dict[str, StorageType] = {}
        scopes: list[StorageScope] = [StorageScope("default", "default", 0)]
        for constant_name, slot in constants.items():
            usage = re.search(
                rf"\b{re.escape(constant_name)}\."
                r"(?:get|set)(?:Storage)?(?P<type>Uint\d*|Int\d*|Address|Bool|Bytes\d*|String|LowUint\d+|HighUint\d+)",
                combined,
            )
            if not usage:
                continue
            raw_type = usage.group("type").lower()
            if "address" in raw_type:
                type_name = "address"
            elif "bool" in raw_type:
                type_name = "bool"
            elif "string" in raw_type:
                type_name = "string"
            elif "bytes" in raw_type:
                digits = "".join(char for char in raw_type if char.isdigit())
                type_name = f"bytes{digits}" if digits else "bytes"
            elif "int" in raw_type:
                digits = "".join(char for char in raw_type if char.isdigit())
                type_name = f"uint{digits or '256'}"
            else:
                type_name = "uint256"
            type_id = self._ensure_source_type(type_name, types, sources)
            scope_id = f"unstructured:{slot:064x}"
            scopes.append(
                StorageScope(
                    id=scope_id,
                    kind="unstructured",
                    root_slot=slot,
                    provenance="source_inference",
                    confidence="inferred",
                )
            )
            variables.append(StorageVariable(
                name=self._constant_variable_name(constant_name),
                slot=slot,
                offset=0,
                size=types[type_id].num_bytes or 32,
                type_id=type_id,
                label=type_name,
                provenance="source_inference",
                confidence="inferred",
                scope_id=scope_id,
            ))
        if not variables:
            return None
        return StorageLayout(
            contract_name="unstructured storage",
            variables=variables,
            types=types,
            language="Solidity",
            scopes=scopes,
        )

    @staticmethod
    def _strip_comments(content: str) -> str:
        content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
        return re.sub(r"//[^\n]*", "", content)

    def _contract_definitions(
        self,
        sources: dict[str, str],
    ) -> dict[str, tuple[list[str], str]]:
        definitions: dict[str, tuple[list[str], str]] = {}
        pattern = re.compile(
            r"(?:abstract\s+)?contract\s+(?P<name>\w+)"
            r"(?:\s+is\s+(?P<bases>[^\{]+))?\s*\{",
        )
        for raw_content in sources.values():
            content = self._strip_comments(raw_content)
            for match in pattern.finditer(content):
                body = self._balanced_body(content, match.end() - 1)
                if body is None:
                    continue
                bases = []
                for raw_base in (match.group("bases") or "").split(","):
                    base_match = re.match(r"\s*(\w+)", raw_base)
                    if base_match:
                        bases.append(base_match.group(1))
                definitions[match.group("name")] = (bases, body)
        return definitions

    @staticmethod
    def _top_level_statements(body: str) -> list[str]:
        statements: list[str] = []
        buffer: list[str] = []
        brace_depth = 0
        string_quote: Optional[str] = None
        escaped = False
        for char in body:
            if string_quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == string_quote:
                    string_quote = None
                if brace_depth == 0:
                    buffer.append(char)
                continue
            if char in {'"', "'"}:
                string_quote = char
                if brace_depth == 0:
                    buffer.append(char)
            elif char == "{":
                if brace_depth == 0:
                    buffer.clear()
                brace_depth += 1
            elif char == "}":
                brace_depth = max(0, brace_depth - 1)
                if brace_depth == 0:
                    buffer.clear()
            elif brace_depth == 0:
                buffer.append(char)
                if char == ";":
                    statement = "".join(buffer).strip()
                    if statement:
                        statements.append(statement[:-1].strip())
                    buffer.clear()
        return statements

    @staticmethod
    def _state_declaration(statement: str) -> Optional[tuple[str, str]]:
        normalized = re.sub(r"\s+", " ", statement).strip()
        if not normalized or normalized.startswith((
            "using ", "event ", "error ", "function ", "modifier ",
            "constructor", "import ", "pragma ", "type ", "return ",
        )):
            return None
        if re.search(r"\b(?:constant|immutable)\b", normalized):
            return None
        # Drop a top-level initializer without being confused by mapping arrows.
        depth = 0
        declaration = normalized
        for index, char in enumerate(normalized):
            if char in "([":
                depth += 1
            elif char in ")]":
                depth -= 1
            elif char == "=" and depth == 0 and not (
                index + 1 < len(normalized) and normalized[index + 1] == ">"
            ):
                declaration = normalized[:index].strip()
                break
        name_match = re.search(r"([A-Za-z_]\w*)\s*$", declaration)
        if not name_match:
            return None
        name = name_match.group(1)
        prefix = declaration[:name_match.start()].strip()
        prefix = re.sub(
            r"\b(?:public|private|internal|external|virtual|override|transient)\b",
            "",
            prefix,
        )
        type_name = re.sub(r"\s+", " ", prefix).strip()
        if not type_name or type_name.startswith(("struct ", "enum ")):
            return None
        return type_name, name

    def parse_standard_storage(
        self,
        sources: dict[str, str],
        contract_name: str,
    ) -> Optional[StorageLayout]:
        """Infer conventional Solidity state layout without invoking a compiler."""
        definitions = self._contract_definitions(sources)
        if contract_name not in definitions:
            return None
        ordered_contracts: list[str] = []
        visiting: set[str] = set()

        def visit(name: str) -> None:
            if name in ordered_contracts or name in visiting:
                return
            visiting.add(name)
            bases, _ = definitions.get(name, ([], ""))
            for base in bases:
                visit(base)
            visiting.remove(name)
            ordered_contracts.append(name)

        visit(contract_name)
        declarations: list[tuple[str, str]] = []
        for name in ordered_contracts:
            _, body = definitions.get(name, ([], ""))
            for statement in self._top_level_statements(body):
                declaration = self._state_declaration(statement)
                if declaration:
                    declarations.append(declaration)
        if not declarations:
            return None

        variables: list[StorageVariable] = []
        types: dict[str, StorageType] = {}
        current_slot = 0
        current_offset = 0
        for type_name, variable_name in declarations:
            type_id = self._ensure_source_type(type_name, types, sources)
            storage_type = types[type_id]
            is_full_slot = (
                storage_type.encoding in {"mapping", "dynamic_array", "bytes"}
                or storage_type.kind in {"struct", "array"}
                or (storage_type.num_bytes or 32) >= 32
            )
            size = storage_type.num_bytes or 32
            if is_full_slot:
                if current_offset:
                    current_slot += 1
                    current_offset = 0
                variables.append(StorageVariable(
                    name=variable_name,
                    slot=current_slot,
                    offset=0,
                    size=size,
                    type_id=type_id,
                    label=storage_type.label,
                    provenance="source_inference",
                    confidence="inferred",
                ))
                current_slot += max(1, (size + 31) // 32)
                continue
            if current_offset + size > 32:
                current_slot += 1
                current_offset = 0
            variables.append(StorageVariable(
                name=variable_name,
                slot=current_slot,
                offset=current_offset,
                size=size,
                type_id=type_id,
                label=storage_type.label,
                provenance="source_inference",
                confidence="inferred",
            ))
            current_offset += size
            if current_offset == 32:
                current_slot += 1
                current_offset = 0
        return StorageLayout(
            contract_name=contract_name,
            variables=variables,
            types=types,
            language="Solidity",
        )

    @staticmethod
    def _unwrap_vyper_public(type_name: str) -> str:
        normalized = type_name.strip()
        if normalized.startswith("public(") and normalized.endswith(")"):
            return normalized[7:-1].strip()
        return normalized

    @classmethod
    def _vyper_storage_type(cls, raw_type: str) -> Optional[str]:
        """Return the allocated type, or ``None`` for code-only declarations."""
        normalized = raw_type.strip()
        while normalized.startswith("public(") and normalized.endswith(")"):
            normalized = normalized[7:-1].strip()
        if normalized.startswith(("constant(", "immutable(")):
            return None
        return normalized

    def parse_vyper_storage(
        self,
        sources: dict[str, str],
        contract_name: str,
        compiler_version: str | None = None,
    ) -> Optional[StorageLayout]:
        """Infer a Vyper layout from verified source without compiling it."""
        source = next(
            (
                content
                for filename, content in sources.items()
                if filename.endswith(".vy") and contract_name.lower() in filename.lower()
            ),
            next((content for filename, content in sources.items() if filename.endswith(".vy")), None),
        )
        if not source:
            return None
        version_match = re.search(
            r"^\s*#\s*@version[^\n]*?(\d+)\.(\d+)\.(\d+)",
            source,
            flags=re.MULTILINE,
        )
        vyper_version = (
            tuple(int(part) for part in version_match.groups())
            if version_match
            else None
        )
        policy = vyper_storage_policy(compiler_version or vyper_version)
        legacy_hashed = policy.storage_scheme == LEGACY_HASHED_STORAGE
        source = self._strip_comments(source)
        source = re.sub(r"#[^\n]*", "", source)
        integer_constants = {
            match.group(1): int(match.group(2).replace("_", ""), 0)
            for match in re.finditer(
                r"^([A-Za-z_]\w*)\s*:\s*constant\([^\n)]+\)\s*=\s*"
                r"(0[xX][0-9a-fA-F_]+|[0-9][0-9_]*)\s*$",
                source,
                flags=re.MULTILINE,
            )
        }
        struct_fields: dict[str, list[tuple[str, str]]] = {}
        lines = source.splitlines()
        index = 0
        while index < len(lines):
            match = re.match(r"^struct\s+(\w+)\s*:\s*$", lines[index])
            if not match:
                index += 1
                continue
            fields: list[tuple[str, str]] = []
            index += 1
            while index < len(lines) and (not lines[index].strip() or lines[index][0].isspace()):
                field_match = re.match(r"^\s+([A-Za-z_]\w*)\s*:\s*(.+?)\s*$", lines[index])
                if field_match:
                    fields.append((field_match.group(1), field_match.group(2)))
                index += 1
            struct_fields[match.group(1)] = fields

        types: dict[str, StorageType] = {}

        def split_generic(type_name: str) -> Optional[tuple[str, str, str]]:
            for prefix in ("HashMap", "DynArray"):
                if not type_name.startswith(prefix + "[") or not type_name.endswith("]"):
                    continue
                inner = type_name[len(prefix) + 1:-1]
                depth = 0
                for position, char in enumerate(inner):
                    if char == "[":
                        depth += 1
                    elif char == "]":
                        depth -= 1
                    elif char == "," and depth == 0:
                        return prefix, inner[:position].strip(), inner[position + 1:].strip()
            return None

        def ensure_type(raw_type: str) -> tuple[str, int]:
            type_name = self._unwrap_vyper_public(raw_type)
            if type_name in types:
                type_info = types[type_name]
                return type_name, max(1, (type_info.num_bytes or 32) // 32)
            generic = split_generic(type_name)
            if generic and generic[0] == "HashMap":
                _, key_name, value_name = generic
                key_id, _ = ensure_type(key_name)
                value_id, _ = ensure_type(value_name)
                types[type_name] = StorageType(
                    id=type_name,
                    label=type_name,
                    kind="mapping",
                    encoding="mapping",
                    num_bytes=32,
                    key_type=key_id,
                    value_type=value_id,
                )
                return type_name, 1
            if generic and generic[0] == "DynArray":
                _, element_name, maximum = generic
                element_id, element_slots = ensure_type(element_name)
                maximum_value = integer_constants.get(maximum)
                if maximum_value is None:
                    maximum_value = int(maximum.replace("_", ""), 0)
                slots = 1 + maximum_value * element_slots
                types[type_name] = StorageType(
                    id=type_name,
                    label=type_name,
                    kind="array",
                    encoding="dynamic_array",
                    num_bytes=slots * 32,
                    element_type=element_id,
                    array_length=maximum_value,
                )
                return type_name, slots
            array_match = re.fullmatch(
                r"(.+)\[([A-Za-z_]\w*|[0-9][0-9_]*)\]",
                type_name,
            )
            if array_match and not type_name.startswith(("String[", "Bytes[")):
                element_id, element_slots = ensure_type(array_match.group(1).strip())
                length_token = array_match.group(2)
                length = integer_constants.get(length_token)
                if length is None:
                    length = int(length_token.replace("_", ""), 0)
                slots = length * element_slots
                types[type_name] = StorageType(
                    id=type_name,
                    label=type_name,
                    kind="array",
                    encoding="inplace",
                    num_bytes=slots * 32,
                    element_type=element_id,
                    array_length=length,
                )
                return type_name, slots
            if type_name in struct_fields:
                members: list[StorageVariable] = []
                slot = 0
                # Placeholder protects recursive source types.
                types[type_name] = StorageType(
                    id=type_name,
                    label=f"struct {type_name}",
                    kind="struct",
                    encoding="inplace",
                    num_bytes=32,
                    members=[],
                )
                for field_name, field_type_name in struct_fields[type_name]:
                    field_id, field_slots = ensure_type(field_type_name)
                    members.append(StorageVariable(
                        name=field_name,
                        slot=(len(members) if legacy_hashed else slot),
                        offset=0,
                        size=field_slots * 32,
                        type_id=field_id,
                        label=self._unwrap_vyper_public(field_type_name),
                        provenance="source_inference",
                        confidence="inferred",
                    ))
                    slot += 1 if legacy_hashed else field_slots
                types[type_name].members = members
                types[type_name].num_bytes = max(1, slot) * 32
                return type_name, max(1, slot)
            bounded_match = re.fullmatch(r"(?:String|Bytes)\[(\d+)\]", type_name)
            if bounded_match:
                # Hashed-layout Vyper stores length at keccak(base) followed
                # by payload words. Sequential 0.2.x uses two metadata words;
                # 0.3.x and newer uses one.
                metadata_slots = 1 if legacy_hashed else (
                    2
                    if policy.version is not None and policy.version < (0, 3, 0)
                    else 1
                )
                slots = metadata_slots + (int(bounded_match.group(1)) + 31) // 32
                types[type_name] = StorageType(
                    id=type_name,
                    label=type_name,
                    kind="value",
                    encoding="bytes",
                    num_bytes=slots * 32,
                )
                return type_name, slots
            primitive_sizes = {"address": 20, "bool": 1, "bytes32": 32}
            integer_match = re.fullmatch(r"u?int(\d+)", type_name)
            size = primitive_sizes.get(type_name, 32)
            if integer_match:
                size = int(integer_match.group(1)) // 8
            types[type_name] = StorageType(
                id=type_name,
                label=type_name,
                kind="value",
                encoding="inplace",
                num_bytes=size,
            )
            return type_name, 1

        variables: list[StorageVariable] = []
        lock_occurrences = re.findall(
            r"@nonreentrant\([\"']([^\"']+)[\"']\)",
            source,
        )
        unique_locks = list(dict.fromkeys(lock_occurrences))
        locks = (
            lock_occurrences
            if policy.lock_scheme == LOCK_FRONT_PER_FUNCTION
            else unique_locks
        )
        lock_type_id, _ = ensure_type("uint256")

        declaration_pattern = re.compile(r"^([A-Za-z_]\w*)\s*:\s*(.+?)\s*$")
        declarations: list[tuple[str, str, int, str]] = []
        for line in lines:
            if not line or line[0].isspace():
                continue
            match = declaration_pattern.match(line)
            if not match:
                continue
            variable_name, raw_type = match.groups()
            storage_type = self._vyper_storage_type(raw_type)
            if storage_type is None or variable_name in {
                "event", "struct", "enum", "interface",
                "implements", "exports", "initializes", "uses",
            }:
                continue
            type_id, slots = ensure_type(storage_type)
            declarations.append((variable_name, type_id, slots, storage_type))

        def add_lock(lock: str, slot: int) -> None:
            variables.append(StorageVariable(
                name=f"nonreentrant.{lock}",
                slot=slot,
                offset=0,
                size=32,
                type_id=lock_type_id,
                label="uint256",
                provenance="source_inference",
                confidence="inferred",
            ))

        front_locks = policy.lock_scheme in {
            LOCK_FRONT_PER_FUNCTION,
            LOCK_FRONT_PER_KEY,
        }
        if front_locks:
            for lock_slot, lock in enumerate(locks):
                add_lock(lock, lock_slot)

        state_slot = len(locks) if front_locks else 0
        for variable_name, type_id, slots, storage_type in declarations:
            allocated_slots = 1 if legacy_hashed else slots
            variables.append(StorageVariable(
                name=variable_name,
                slot=state_slot,
                offset=0,
                size=allocated_slots * 32,
                type_id=type_id,
                label=storage_type,
                provenance="source_inference",
                confidence="inferred",
            ))
            state_slot += allocated_slots

        if policy.lock_scheme == LOCK_SENTINEL:
            for offset, lock in enumerate(locks):
                add_lock(lock, 0xFFFFFF + offset)
        elif policy.lock_scheme == LOCK_AFTER_GLOBALS:
            for offset, lock in enumerate(locks):
                add_lock(lock, len(declarations) + offset)
        elif policy.lock_scheme == LOCK_AFTER_STORAGE:
            for offset, lock in enumerate(locks):
                add_lock(lock, state_slot + offset)

        if not variables:
            return None
        return StorageLayout(
            contract_name=contract_name,
            variables=variables,
            types=types,
            language="Vyper",
            compiler_version=(
                compiler_version
                or (".".join(str(part) for part in vyper_version) if vyper_version else None)
            ),
            storage_scheme=policy.storage_scheme,
        )
