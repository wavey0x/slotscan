# Layout Parser Service

## Overview

The Layout Parser takes verified Solidity source code and compiler settings, compiles it to extract `storageLayout`, and normalizes the output into an internal schema that the rest of the application can use for slot computation and value decoding. MVP constraints: only verified contracts get layouts; unverified stay hex-only. Compile once per (chain, address, compiler version), cache in Postgres JSONB, and reuse. If layout extraction fails, return "layout unavailable" (hex-only) instead of failing the request.
Preferred source: use Sourcify-provided `storageLayout` directly when available. Fallback: solc compile with full metadata (standard JSON).

## Implementation Status: ✅ Complete

### Key Implementation Decisions

1. **`parse_from_raw_layout()` Method**: Added to parse Sourcify's raw `storageLayout` JSON directly without recompilation. This is the preferred path when Sourcify provides layout data.

2. **FQName Contract Matching**: When extracting layout from compiled output, uses fully-qualified name matching (`path/to/Contract.sol:ContractName`) to locate the correct contract in multi-file compilations.

3. **Base Slot Index**: `StorageLayout.get_base_slot_index()` returns a dict mapping base slots to their mapping/array variables, enabling efficient slot-to-variable lookups in the tracer.

4. **Graceful Degradation**: If layout parsing fails for any reason, the system continues with `layout=None` rather than failing the request. Values display as hex-only.

## Location

```
backend/app/services/layout.py
```

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `solcx` | Python wrapper for solc compiler |
| Contract Resolver | Provides source code and compiler settings |
| Database Layer | Cache parsed layouts (Postgres JSONB) |
| Sourcify | Preferred layout source when available (no compilation) |

## Public Interface

```python
@dataclass
class StorageVariable:
    """A single storage variable in the layout."""
    name: str
    slot: int                    # Base slot number
    offset: int                  # Byte offset within slot (0-31)
    size: int                    # Size in bytes
    type_id: str                 # Reference to type in types dict
    label: str                   # Full label e.g. "mapping(address => uint256)"


@dataclass
class StorageType:
    """Type definition for storage variables."""
    id: str                      # Type identifier e.g. "t_uint256"
    label: str                   # Human label e.g. "uint256"
    kind: str                    # "value", "array", "mapping", "struct"
    encoding: str                # "inplace", "bytes", "dynamic_array", "mapping"
    num_bytes: Optional[int]     # Size for value types

    # For arrays
    element_type: Optional[str]  # Type ID of array element
    array_length: Optional[int]  # None for dynamic arrays

    # For mappings
    key_type: Optional[str]      # Type ID of mapping key
    value_type: Optional[str]    # Type ID of mapping value

    # For structs
    members: Optional[List[StorageVariable]]  # Struct fields


@dataclass
class StorageLayout:
    """Complete storage layout for a contract."""
    contract_name: str
    variables: List[StorageVariable]
    types: Dict[str, StorageType]

    def get_variable_by_slot(self, slot: int, offset: int = 0) -> Optional[StorageVariable]:
        """Find variable at given slot/offset."""
        pass

    def get_type(self, type_id: str) -> Optional[StorageType]:
        """Get type definition by ID."""
        pass


class LayoutParser:
    """Parses Solidity source into storage layout."""

    async def parse(
        self,
        contract_name: str,
        sources: Dict[str, str],
        compiler_version: str,
        compiler_settings: Optional[Dict] = None
    ) -> StorageLayout:
        """
        Compile sources and extract storage layout.

        Args:
            contract_name: Name of the target contract
            sources: Dict of filename -> source code
            compiler_version: Exact solc version e.g. "0.8.19"
            compiler_settings: Optimizer settings, etc.

        Returns:
            Normalized StorageLayout

        Raises:
            CompilationError: If compilation fails
            LayoutNotFoundError: If contract not found in output
        """
        pass

    def parse_from_solc_output(
        self,
        contract_name: str,
        solc_output: Dict
    ) -> StorageLayout:
        """
        Parse storage layout from existing solc output.

        Useful when layout is already available (e.g., from Sourcify metadata).
        """
        pass
```

## Implementation Details

### 1. Compiler Version Management

```python
import solcx

async def _ensure_solc_version(self, version: str) -> None:
    """
    Ensure the required solc version is installed.

    Handles version normalization (e.g., "v0.8.19+commit.abc" -> "0.8.19")
    """
    # Normalize version string
    normalized = self._normalize_version(version)

    # Check if already installed
    installed = solcx.get_installed_solc_versions()
    if normalized in [str(v) for v in installed]:
        return

    # Install the version
    try:
        solcx.install_solc(normalized)
    except Exception as e:
        raise CompilationError(f"Failed to install solc {normalized}: {e}")


def _normalize_version(self, version: str) -> str:
    """
    Normalize compiler version string.

    Examples:
        "v0.8.19+commit.7dd6d404" -> "0.8.19"
        "0.8.19" -> "0.8.19"
        "^0.8.0" -> raises error (need exact version)
    """
    # Remove 'v' prefix
    if version.startswith("v"):
        version = version[1:]

    # Remove commit hash
    if "+" in version:
        version = version.split("+")[0]

    # Validate it's a full version
    parts = version.split(".")
    if len(parts) != 3:
        raise CompilationError(f"Invalid compiler version: {version}")

    return version
```

### 2. Compilation with Storage Layout

```python
async def _compile_with_layout(
    self,
    contract_name: str,
    sources: Dict[str, str],
    version: str,
    settings: Optional[Dict]
) -> Dict:
    """
    Compile sources with storageLayout output enabled.

    Returns the full compiler output.
    """
    await self._ensure_solc_version(version)

    # Build standard JSON input
    standard_input = {
        "language": "Solidity",
        "sources": {
            filename: {"content": content}
            for filename, content in sources.items()
        },
        "settings": {
            "outputSelection": {
                "*": {
                    "*": ["storageLayout"]
                }
            }
        }
    }

    # Merge in provided settings (optimizer, etc.)
    if settings:
        if "optimizer" in settings:
            standard_input["settings"]["optimizer"] = settings["optimizer"]
        if "evmVersion" in settings:
            standard_input["settings"]["evmVersion"] = settings["evmVersion"]
        if "remappings" in settings:
            standard_input["settings"]["remappings"] = settings["remappings"]

    # Compile
    try:
        solcx.set_solc_version(version)
        output = solcx.compile_standard(standard_input)
    except Exception as e:
        raise CompilationError(f"Compilation failed: {e}")

    # Check for errors
    if "errors" in output:
        errors = [e for e in output["errors"] if e.get("severity") == "error"]
        if errors:
            raise CompilationError(f"Compilation errors: {errors}")

    return output
```

### 3. Layout Extraction and Normalization

```python
def _extract_layout(self, contract_name: str, solc_output: Dict) -> Dict:
    """
    Find and extract storageLayout for target contract.

    The contract might be in any source file, so we search all outputs.
    """
    for filename, contracts in solc_output.get("contracts", {}).items():
        if contract_name in contracts:
            contract_output = contracts[contract_name]
            if "storageLayout" in contract_output:
                return contract_output["storageLayout"]

    raise LayoutNotFoundError(f"No storage layout for {contract_name}")


def _normalize_layout(self, raw_layout: Dict) -> StorageLayout:
    """
    Convert solc storageLayout output to our internal schema.

    Handles:
    - Type normalization
    - Nested struct expansion
    - Array/mapping type resolution
    """
    # Parse types first (variables reference them)
    types = self._parse_types(raw_layout.get("types", {}))

    # Parse variables
    variables = self._parse_variables(raw_layout.get("storage", []), types)

    # Get contract name from first variable's contract field
    contract_name = ""
    if raw_layout.get("storage"):
        contract_name = raw_layout["storage"][0].get("contract", "")

    return StorageLayout(
        contract_name=contract_name,
        variables=variables,
        types=types
    )


def _parse_types(self, raw_types: Dict) -> Dict[str, StorageType]:
    """
    Parse type definitions from solc output.

    Example solc type:
    {
        "t_uint256": {
            "encoding": "inplace",
            "label": "uint256",
            "numberOfBytes": "32"
        },
        "t_mapping(t_address,t_uint256)": {
            "encoding": "mapping",
            "key": "t_address",
            "value": "t_uint256",
            "label": "mapping(address => uint256)"
        }
    }
    """
    types = {}

    for type_id, type_def in raw_types.items():
        encoding = type_def.get("encoding", "inplace")
        label = type_def.get("label", type_id)
        num_bytes = int(type_def.get("numberOfBytes", 0)) or None

        # Determine kind from encoding and type pattern
        kind = self._infer_kind(type_id, encoding)

        storage_type = StorageType(
            id=type_id,
            label=label,
            kind=kind,
            encoding=encoding,
            num_bytes=num_bytes,
            element_type=None,
            array_length=None,
            key_type=None,
            value_type=None,
            members=None
        )

        # Parse type-specific fields
        if encoding == "mapping":
            storage_type.key_type = type_def.get("key")
            storage_type.value_type = type_def.get("value")

        elif encoding == "dynamic_array":
            storage_type.element_type = type_def.get("base")

        elif "array" in type_id.lower() and "numberOfBytes" in type_def:
            # Static array - parse length from type ID
            storage_type.element_type = type_def.get("base")
            storage_type.array_length = self._parse_array_length(type_id)

        elif "members" in type_def:
            # Struct type
            storage_type.members = self._parse_struct_members(type_def["members"], raw_types)

        types[type_id] = storage_type

    return types


def _infer_kind(self, type_id: str, encoding: str) -> str:
    """Infer the kind of type from ID and encoding."""
    if encoding == "mapping":
        return "mapping"
    elif encoding == "dynamic_array":
        return "array"
    elif "array" in type_id.lower():
        return "array"
    elif type_id.startswith("t_struct"):
        return "struct"
    elif type_id.startswith("t_contract"):
        return "contract"
    else:
        return "value"


def _parse_array_length(self, type_id: str) -> Optional[int]:
    """
    Extract array length from type ID.

    Example: "t_array(t_uint256)10_storage" -> 10
    """
    import re
    match = re.search(r'\)(\d+)_', type_id)
    if match:
        return int(match.group(1))
    return None


def _parse_struct_members(
    self,
    raw_members: List[Dict],
    all_types: Dict
) -> List[StorageVariable]:
    """Parse struct member definitions into StorageVariables."""
    members = []
    for member in raw_members:
        members.append(StorageVariable(
            name=member.get("label", ""),
            slot=int(member.get("slot", 0)),
            offset=int(member.get("offset", 0)),
            size=int(all_types.get(member.get("type", ""), {}).get("numberOfBytes", 32)),
            type_id=member.get("type", ""),
            label=all_types.get(member.get("type", ""), {}).get("label", "")
        ))
    return members


def _parse_variables(
    self,
    raw_storage: List[Dict],
    types: Dict[str, StorageType]
) -> List[StorageVariable]:
    """
    Parse storage variables from solc output.

    Example solc variable:
    {
        "astId": 123,
        "contract": "contracts/Token.sol:Token",
        "label": "owner",
        "offset": 0,
        "slot": "0",
        "type": "t_address"
    }
    """
    variables = []

    for var in raw_storage:
        type_id = var.get("type", "")
        type_info = types.get(type_id)

        variables.append(StorageVariable(
            name=var.get("label", ""),
            slot=int(var.get("slot", 0)),
            offset=int(var.get("offset", 0)),
            size=type_info.num_bytes if type_info else 32,
            type_id=type_id,
            label=type_info.label if type_info else type_id
        ))

    return variables
```

### 4. Main Parse Flow

```python
async def parse(
    self,
    contract_name: str,
    sources: Dict[str, str],
    compiler_version: str,
    compiler_settings: Optional[Dict] = None
) -> StorageLayout:
    """
    Full parsing pipeline.

    1. Ensure compiler version installed
    2. Compile with storageLayout output
    3. Extract layout for target contract
    4. Normalize to internal schema
    """
    # Compile
    solc_output = await self._compile_with_layout(
        contract_name=contract_name,
        sources=sources,
        version=compiler_version,
        settings=compiler_settings
    )

    # Extract and normalize
    raw_layout = self._extract_layout(contract_name, solc_output)
    layout = self._normalize_layout(raw_layout)

    return layout


def parse_from_solc_output(
    self,
    contract_name: str,
    solc_output: Dict
) -> StorageLayout:
    """
    Parse from existing solc output (e.g., from Sourcify metadata).

    Skips compilation step.
    """
    raw_layout = self._extract_layout(contract_name, solc_output)
    return self._normalize_layout(raw_layout)
```

## StorageLayout Helper Methods

```python
@dataclass
class StorageLayout:
    contract_name: str
    variables: List[StorageVariable]
    types: Dict[str, StorageType]

    def get_variable_by_slot(
        self,
        slot: int,
        offset: int = 0
    ) -> Optional[StorageVariable]:
        """
        Find variable at given slot and offset.

        Handles packed variables (multiple vars in one slot).
        """
        for var in self.variables:
            if var.slot == slot:
                # Check if offset matches or overlaps
                if offset >= var.offset and offset < var.offset + var.size:
                    return var
        return None

    def get_variable_by_name(self, name: str) -> Optional[StorageVariable]:
        """Find variable by name."""
        for var in self.variables:
            if var.name == name:
                return var
        return None

    def get_type(self, type_id: str) -> Optional[StorageType]:
        """Get type definition by ID."""
        return self.types.get(type_id)

    def get_all_static_slots(self) -> List[Tuple[int, StorageVariable]]:
        """
        Get all statically-known slots.

        Returns list of (slot_number, variable) tuples.
        Excludes mappings and dynamic arrays (computed at runtime).
        """
        slots = []
        for var in self.variables:
            var_type = self.types.get(var.type_id)
            if var_type and var_type.encoding not in ("mapping", "dynamic_array"):
                slots.append((var.slot, var))
                # Add additional slots for large types
                if var_type.num_bytes and var_type.num_bytes > 32:
                    extra_slots = (var_type.num_bytes - 1) // 32
                    for i in range(1, extra_slots + 1):
                        slots.append((var.slot + i, var))
        return slots

    def to_dict(self) -> Dict:
        """Serialize to dictionary for JSON storage."""
        return {
            "contract_name": self.contract_name,
            "variables": [asdict(v) for v in self.variables],
            "types": {k: asdict(v) for k, v in self.types.items()}
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "StorageLayout":
        """Deserialize from dictionary."""
        return cls(
            contract_name=data["contract_name"],
            variables=[StorageVariable(**v) for v in data["variables"]],
            types={k: StorageType(**v) for k, v in data["types"].items()}
        )
```

## Error Handling

```python
class CompilationError(Exception):
    """Raised when solc compilation fails."""
    pass


class LayoutNotFoundError(Exception):
    """Raised when contract not found in compiler output."""
    def __init__(self, contract_name: str):
        self.contract_name = contract_name
        super().__init__(f"Storage layout not found for {contract_name}")
```

## Caching Strategy

Layouts are cached in the `contracts` table as JSONB and skipped on subsequent requests unless verification metadata or code hash changes. If layout retrieval fails, return hex-only with a warning instead of erroring.

| Data | Cache Key | TTL |
|------|-----------|-----|
| Storage layout | `(chain_id, address)` | Permanent (tied to code_hash) |

Layout is recomputed if:
- `code_hash` changes (proxy upgrade)
- Contract becomes verified (was unverified before)

## Testing Strategy

### Unit Tests

1. **Version normalization**
   - "v0.8.19+commit.abc" -> "0.8.19"
   - Various edge cases

2. **Type parsing**
   - Value types (uint, address, bool, bytes)
   - Mapping types (simple and nested)
   - Array types (static and dynamic)
   - Struct types

3. **Variable parsing**
   - Simple variables
   - Packed variables (offset > 0)
   - Complex nested types

4. **Layout helpers**
   - `get_variable_by_slot`
   - `get_all_static_slots`
   - Serialization round-trip

### Integration Tests

1. **Real contract compilation**
   - Compile simple ERC20
   - Compile contract with structs
   - Compile contract with mappings

2. **Error cases**
   - Invalid source code
   - Missing contract name
   - Unsupported compiler version

## Performance Considerations

1. **Compiler caching**: `solcx` caches installed compilers
2. **Skip recompilation**: If layout cached, don't recompile
3. **Lazy type resolution**: Only fully resolve types when needed
4. **Parallel compilation**: Not needed (single contract per request)

## Example Usage

```python
parser = LayoutParser()

# From sources
layout = await parser.parse(
    contract_name="USDC",
    sources={
        "USDC.sol": "contract USDC { ... }",
        "ERC20.sol": "contract ERC20 { ... }"
    },
    compiler_version="0.8.19",
    compiler_settings={"optimizer": {"enabled": True, "runs": 200}}
)

# Explore layout
for var in layout.variables:
    print(f"{var.name}: slot={var.slot}, offset={var.offset}, type={var.label}")

# Find specific variable
owner_var = layout.get_variable_by_name("owner")
if owner_var:
    owner_type = layout.get_type(owner_var.type_id)
    print(f"owner is {owner_type.label} at slot {owner_var.slot}")
```

## Appendix: Solidity Storage Layout Rules

For reference, the rules this parser must handle:

1. **Value types** (uint, int, address, bool, bytesN) are stored inline
2. **Structs** are stored starting at their slot, members packed
3. **Static arrays** store elements contiguously starting at base slot
4. **Dynamic arrays** store length at base slot, elements at `keccak256(slot)`
5. **Mappings** don't store anything at base slot; values at `keccak256(key, slot)`
6. **Packing**: Multiple values <32 bytes can share a slot (right-aligned)
7. **Inheritance**: Parent contract storage comes first
