"""Domain models for SlotScan."""

from dataclasses import dataclass, asdict
from typing import Optional, Any


@dataclass
class StorageVariable:
    """A single storage variable in the layout."""

    name: str
    slot: int
    offset: int
    size: int
    type_id: str
    label: str
    provenance: str = "compiler_layout"
    confidence: str = "exact"


@dataclass
class StorageType:
    """Type definition for storage variables."""

    id: str
    label: str
    kind: str  # "value", "array", "mapping", "struct", "contract"
    encoding: str  # "inplace", "bytes", "dynamic_array", "mapping"
    num_bytes: Optional[int] = None
    base_type: Optional[str] = None

    # For arrays
    element_type: Optional[str] = None
    array_length: Optional[int] = None

    # For mappings
    key_type: Optional[str] = None
    value_type: Optional[str] = None

    # For structs
    members: Optional[list[StorageVariable]] = None


@dataclass
class StorageLayout:
    """Complete storage layout for a contract."""

    contract_name: str
    variables: list[StorageVariable]
    types: dict[str, StorageType]
    language: Optional[str] = None
    compiler_version: Optional[str] = None
    storage_scheme: Optional[str] = None

    def get_variable_by_slot(
        self, slot: int, offset: int = 0
    ) -> Optional[StorageVariable]:
        """Find variable at given slot and offset (exact match)."""
        for var in self.variables:
            if var.slot == slot:
                if offset >= var.offset and offset < var.offset + var.size:
                    return var
        return None

    def get_variable_for_slot(self, slot: int) -> Optional[StorageVariable]:
        """
        Find variable that spans the given slot, accounting for multi-slot values.

        For mappings/dynamic arrays, only matches the exact base slot (which stores
        nothing for mappings, or the array length for dynamic arrays).
        Does not attempt to resolve hashed element slots (requires keys/indices).
        """
        # Imported lazily to keep domain models independent of service wiring.
        from app.services.layout_index import LayoutIndex

        entry = LayoutIndex(self).first_at(slot)
        return entry.variable if entry else None

    def get_mapping_by_base_slot(self, slot: int) -> Optional[StorageVariable]:
        """
        Find mapping variable whose base slot matches.

        Searches both top-level variables and mappings inside struct members.
        For struct members, returns a StorageVariable with the full path name
        (e.g., "vaultStorage.users" instead of just "users").
        """
        # First, check top-level variables (direct mappings)
        for var in self.variables:
            if var.slot == slot:
                var_type = self.types.get(var.type_id)
                if var_type and var_type.encoding == "mapping":
                    return var

        # Second, check mappings inside struct members
        # For a struct at slot N, a member at relative slot M has absolute slot N+M
        for var in self.variables:
            var_type = self.types.get(var.type_id)
            if not var_type or var_type.kind != "struct" or not var_type.members:
                continue

            # Check each member of the struct
            for member in var_type.members:
                absolute_slot = var.slot + member.slot
                if absolute_slot == slot:
                    member_type = self.types.get(member.type_id)
                    if member_type and member_type.encoding == "mapping":
                        # Return a synthetic variable with full path name
                        return StorageVariable(
                            name=f"{var.name}.{member.name}",
                            slot=absolute_slot,  # Use absolute slot
                            offset=member.offset,
                            size=member.size,
                            type_id=member.type_id,
                            label=member.label,
                        )

        return None

    def get_all_variables_in_slot(self, slot: int) -> list[StorageVariable]:
        """Get ALL variables that share this slot (for packed storage)."""
        result = []
        for var in self.variables:
            if var.slot == slot:
                result.append(var)
        return sorted(result, key=lambda v: v.offset)

    def get_static_array_locations(
        self, var: StorageVariable, slot: int
    ) -> tuple[tuple[int, Any], ...]:
        """Return every static-array element represented by a storage word."""
        from app.services.layout_index import array_packing

        var_type = self.get_type(var.type_id)
        if (
            not var_type
            or var_type.encoding != "inplace"
            or var_type.array_length is None
            or not var_type.element_type
            or var_type.element_type.lower() in {"string", "bytes"}
        ):
            return ()
        element_type = self.get_type(var_type.element_type) if var_type.element_type else None
        packing = array_packing(element_type)
        return packing.locations_in_slot(
            var.slot,
            slot,
            length=var_type.array_length,
        )

    def get_type(self, type_id: str) -> Optional[StorageType]:
        """Get a type without mutating the layout's type registry."""
        if type_id in self.types:
            return self.types[type_id]

        from app.services.storage_rules import synthesize_storage_type

        return synthesize_storage_type(type_id)

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        return {
            "contract_name": self.contract_name,
            "language": self.language,
            "compiler_version": self.compiler_version,
            "storage_scheme": self.storage_scheme,
            "variables": [asdict(v) for v in self.variables],
            "types": {
                k: {
                    **asdict(v),
                    "members": [asdict(m) for m in v.members] if v.members else None,
                }
                for k, v in self.types.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StorageLayout":
        """Deserialize from dictionary."""
        types = {}
        for k, v in data["types"].items():
            members = None
            if v.get("members"):
                members = [StorageVariable(**m) for m in v["members"]]
            types[k] = StorageType(
                id=v["id"],
                label=v["label"],
                kind=v["kind"],
                encoding=v["encoding"],
                num_bytes=v.get("num_bytes"),
                base_type=v.get("base_type"),
                element_type=v.get("element_type"),
                array_length=v.get("array_length"),
                key_type=v.get("key_type"),
                value_type=v.get("value_type"),
                members=members,
            )

        return cls(
            contract_name=data["contract_name"],
            variables=[StorageVariable(**v) for v in data["variables"]],
            types=types,
            language=data.get("language"),
            compiler_version=data.get("compiler_version"),
            storage_scheme=data.get("storage_scheme"),
        )


@dataclass
class DecodedValue:
    """A decoded storage value."""

    raw: str
    decoded: Any
    type_label: str


@dataclass
class StorageChange:
    """A single storage slot change in a transaction."""

    slot: str
    old_value: Optional[str]
    new_value: str
    mapping_base_slot: Optional[int] = None
    variable: Optional[StorageVariable] = None
    variable_path: Optional[str] = None
    old_decoded: Optional[DecodedValue] = None
    new_decoded: Optional[DecodedValue] = None
    # New fields for enhanced API
    mapping_key: Optional[str] = None  # The key used for mapping lookup (e.g., address)
    is_mapping: bool = False  # Whether this is a mapping entry
    encoding: Optional[str] = None  # Type encoding (inplace, mapping, bytes, etc.)
    key_type: Optional[str] = None  # Key type for mappings
    value_type: Optional[str] = None  # Value type for mappings
    element_type_id: Optional[str] = None  # Element type ID for dynamic arrays (for struct lookup)
    array_index: Optional[int] = None  # Array index for dynamic array entries
    change_index: int = 0  # Order of change within transaction
    pc: Optional[int] = None  # Program counter of the SSTORE operation
    effect: str = "applied"  # applied | noop | reverted
    frame_id: Optional[int] = None
    depth: Optional[int] = None
    code_address: Optional[str] = None
    changed_value: Optional[bool] = None
    frame_outcome: str = "applied"
    opcode: str = "SSTORE"
    namespace: str = "persistent"
    state_initial_value: Optional[str] = None
    state_final_value: Optional[str] = None
    state_values_known: bool = True


@dataclass
class TransactionDiff:
    """All storage changes for a contract in a transaction."""

    chain_id: int
    contract_address: str
    tx_hash: str
    block_number: int
    changes: list[StorageChange]
    is_complete: bool
    layout: Optional[StorageLayout] = None
    trace_unavailable: bool = False
    contract_name: Optional[str] = None  # Name of the contract
    execution_order_available: bool = False  # True if step values are real EVM execution order
    frame_outcomes_available: bool = False
    write_old_values_available: bool = False
    final_state_values_available: bool = False
    trace_step_count: Optional[int] = None


@dataclass(frozen=True)
class RawCompilerArtifact:
    """Versioned raw compiler evidence retained independently of parsing."""

    fingerprint: str
    language: str
    compiler_version: str
    pipeline: str
    standard_input: dict
    compiler_output: dict
    source_hashes: dict[str, str]


@dataclass
class ContractMetadata:
    """Result of contract resolution."""

    chain_id: int
    address: str
    code_hash: Optional[str] = None
    is_delegated: bool = False
    delegate_address: Optional[str] = None
    delegate_code_hash: Optional[str] = None
    is_proxy: bool = False
    proxy_type: Optional[str] = None
    implementation_address: Optional[str] = None
    is_verified: bool = False
    verification_source: Optional[str] = None
    name: Optional[str] = None
    compiler_version: Optional[str] = None
    compilation_target: Optional[dict[str, str]] = None
    sources: Optional[dict[str, str]] = None
    compiler_settings: Optional[dict] = None
    storage_layout: Optional[StorageLayout] = None
    compiler_artifact_fingerprint: Optional[str] = None


@dataclass
class ProxyInfo:
    """Proxy detection result."""

    proxy_type: str
    implementation_address: str
    admin_address: Optional[str] = None


@dataclass
class VerificationResult:
    """Verification lookup result."""

    source: str  # "sourcify" or "etherscan"
    match_type: str  # "full" or "partial"
    name: Optional[str] = None
    compilation_target: Optional[dict] = None
    compiler_version: Optional[str] = None
    compiler_settings: Optional[dict] = None
    sources: Optional[dict[str, str]] = None
    storage_layout: Optional[dict] = None
    language: str = "Solidity"  # "Solidity" or "Vyper"
