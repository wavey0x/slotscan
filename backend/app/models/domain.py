"""Domain models for SlotScan."""

import re
from dataclasses import dataclass, asdict
from typing import Optional, Any

# Pre-compiled regex patterns for type synthesis (performance optimization)
_UINT_PATTERN = re.compile(r'^t_uint(\d+)$')
_INT_PATTERN = re.compile(r'^t_int(\d+)$')
_BYTES_PATTERN = re.compile(r'^t_bytes(\d+)$')
_HASHMAP_PATTERN = re.compile(r'^HashMap\[(.+),\s*(.+)\]$')
_DYNARRAY_PATTERN = re.compile(r'^DynArray\[(.+),\s*(\d+)\]$')
_STATIC_ARRAY_PATTERN = re.compile(r'^(.+)\[(\d+)\]$')
# Vyper patterns (without t_ prefix)
_VYPER_UINT_PATTERN = re.compile(r'^uint(\d+)$')
_VYPER_INT_PATTERN = re.compile(r'^int(\d+)$')
_VYPER_BYTES_PATTERN = re.compile(r'^bytes(\d+)$')


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
    resolver_version: int = 1
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

    def get_variable_by_name(self, name: str) -> Optional[StorageVariable]:
        """Find variable by name."""
        for var in self.variables:
            if var.name == name:
                return var
        return None

    def get_static_array_index(self, var: StorageVariable, slot: int) -> Optional[int]:
        """
        Calculate array index for a slot within a static array.
        Returns None if slot doesn't belong to this array or type isn't static array.
        """
        var_type = self.get_type(var.type_id)
        if not var_type or var_type.encoding != "inplace" or not var_type.array_length:
            return None

        # Skip Vyper String[N] types which have array_length but aren't real arrays
        if var_type.element_type and var_type.element_type.lower() in ("string", "bytes"):
            return None

        # A packed slot can contain multiple array elements. This compatibility
        # helper returns the first; callers that decode values must use
        # ``get_static_array_locations`` and inspect every byte range.
        locations = self.get_static_array_locations(var, slot)
        return locations[0][0] if locations else None

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
        """Get type definition by ID, synthesizing primitives if not found."""
        if type_id in self.types:
            return self.types[type_id]

        # Synthesize common primitive types if not in dictionary
        synthesized = self._synthesize_primitive_type(type_id)
        if synthesized:
            # Cache synthesized type to avoid repeated regex matching
            self.types[type_id] = synthesized
        return synthesized

    def _synthesize_primitive_type(self, type_id: str) -> Optional[StorageType]:
        """Create StorageType for common primitive types not in the types dict."""
        # uint types: t_uint8, t_uint16, ..., t_uint256
        uint_match = _UINT_PATTERN.match(type_id)
        if uint_match:
            bits = int(uint_match.group(1))
            return StorageType(
                id=type_id,
                label=f"uint{bits}",
                kind="value",
                encoding="inplace",
                num_bytes=bits // 8,
            )

        # int types: t_int8, t_int16, ..., t_int256
        int_match = _INT_PATTERN.match(type_id)
        if int_match:
            bits = int(int_match.group(1))
            return StorageType(
                id=type_id,
                label=f"int{bits}",
                kind="value",
                encoding="inplace",
                num_bytes=bits // 8,
            )

        # address type
        if type_id == 't_address':
            return StorageType(
                id=type_id,
                label="address",
                kind="value",
                encoding="inplace",
                num_bytes=20,
            )

        # address payable type
        if type_id == 't_address_payable':
            return StorageType(
                id=type_id,
                label="address payable",
                kind="value",
                encoding="inplace",
                num_bytes=20,
            )

        # bool type
        if type_id == 't_bool':
            return StorageType(
                id=type_id,
                label="bool",
                kind="value",
                encoding="inplace",
                num_bytes=1,
            )

        # bytesN types: t_bytes1, t_bytes2, ..., t_bytes32
        bytes_match = _BYTES_PATTERN.match(type_id)
        if bytes_match:
            n = int(bytes_match.group(1))
            return StorageType(
                id=type_id,
                label=f"bytes{n}",
                kind="value",
                encoding="inplace",
                num_bytes=n,
            )

        # string storage (dynamic)
        if type_id == 't_string_storage':
            return StorageType(
                id=type_id,
                label="string",
                kind="value",
                encoding="bytes",
                num_bytes=32,
            )

        # bytes storage (dynamic)
        if type_id == 't_bytes_storage':
            return StorageType(
                id=type_id,
                label="bytes",
                kind="value",
                encoding="bytes",
                num_bytes=32,
            )

        # --- Vyper type synthesis ---

        # Vyper HashMap: HashMap[key_type, value_type]
        hashmap_match = _HASHMAP_PATTERN.match(type_id)
        if hashmap_match:
            return StorageType(
                id=type_id,
                label=type_id,
                kind="mapping",
                encoding="mapping",
                key_type=hashmap_match.group(1).strip(),
                value_type=hashmap_match.group(2).strip(),
                num_bytes=32,
            )

        # Vyper DynArray: DynArray[element_type, max_len]
        dynarray_match = _DYNARRAY_PATTERN.match(type_id)
        if dynarray_match:
            return StorageType(
                id=type_id,
                label=type_id,
                kind="array",
                encoding="dynamic_array",
                element_type=dynarray_match.group(1).strip(),
                array_length=int(dynarray_match.group(2)),
                num_bytes=32,
            )

        # Vyper static array: type[length] e.g. uint256[10]
        static_array_match = _STATIC_ARRAY_PATTERN.match(type_id)
        if static_array_match:
            element_type = static_array_match.group(1).strip()
            length = int(static_array_match.group(2))
            # Estimate bytes based on element count (assume 32 bytes per element)
            return StorageType(
                id=type_id,
                label=type_id,
                kind="array",
                encoding="inplace",
                element_type=element_type,
                array_length=length,
                num_bytes=32 * length,
            )

        # Vyper primitive types (same names as Solidity but without t_ prefix)
        # address
        if type_id == 'address':
            return StorageType(
                id=type_id,
                label="address",
                kind="value",
                encoding="inplace",
                num_bytes=20,
            )

        # bool
        if type_id == 'bool':
            return StorageType(
                id=type_id,
                label="bool",
                kind="value",
                encoding="inplace",
                num_bytes=1,
            )

        # Vyper uint types: uint8, uint16, ..., uint256
        vyper_uint_match = _VYPER_UINT_PATTERN.match(type_id)
        if vyper_uint_match:
            bits = int(vyper_uint_match.group(1))
            return StorageType(
                id=type_id,
                label=f"uint{bits}",
                kind="value",
                encoding="inplace",
                num_bytes=bits // 8,
            )

        # Vyper int types: int8, int16, ..., int256
        vyper_int_match = _VYPER_INT_PATTERN.match(type_id)
        if vyper_int_match:
            bits = int(vyper_int_match.group(1))
            return StorageType(
                id=type_id,
                label=f"int{bits}",
                kind="value",
                encoding="inplace",
                num_bytes=bits // 8,
            )

        # Vyper bytes types: bytes1, bytes2, ..., bytes32
        vyper_bytes_match = _VYPER_BYTES_PATTERN.match(type_id)
        if vyper_bytes_match:
            n = int(vyper_bytes_match.group(1))
            return StorageType(
                id=type_id,
                label=f"bytes{n}",
                kind="value",
                encoding="inplace",
                num_bytes=n,
            )

        # Vyper Bytes (dynamic bytes)
        if type_id == 'Bytes':
            return StorageType(
                id=type_id,
                label="Bytes",
                kind="value",
                encoding="bytes",
                num_bytes=32,
            )

        # Vyper String
        if type_id == 'String':
            return StorageType(
                id=type_id,
                label="String",
                kind="value",
                encoding="bytes",
                num_bytes=32,
            )

        return None

    def get_all_static_slots(self) -> list[tuple[int, StorageVariable]]:
        """Get all statically-known slots."""
        slots = []
        for var in self.variables:
            var_type = self.types.get(var.type_id)
            if var_type and var_type.encoding not in ("mapping", "dynamic_array"):
                slots.append((var.slot, var))
                if var_type.num_bytes and var_type.num_bytes > 32:
                    extra_slots = (var_type.num_bytes - 1) // 32
                    for i in range(1, extra_slots + 1):
                        slots.append((var.slot + i, var))
        return slots

    def get_base_slot_index(self) -> dict[int, StorageVariable]:
        """Build index of base slot -> variable for mappings and arrays."""
        index: dict[int, StorageVariable] = {}
        for var in self.variables:
            var_type = self.types.get(var.type_id)
            if not var_type:
                continue
            if var_type.encoding in ("mapping", "dynamic_array", "array"):
                index[var.slot] = var
        return index

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        return {
            "contract_name": self.contract_name,
            "resolver_version": self.resolver_version,
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
        for k, v in data.get("types", {}).items():
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
            variables=[StorageVariable(**v) for v in data.get("variables", [])],
            types=types,
            resolver_version=int(data.get("resolver_version", 1)),
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "decoded": self.decoded,
            "type_label": self.type_label,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecodedValue":
        # Older cache rows may contain the removed presentation-only `display`
        # property. Domain deserialization intentionally ignores it.
        return cls(
            raw=data["raw"],
            decoded=data.get("decoded"),
            type_label=data["type_label"],
        )


@dataclass
class SlotValue:
    """A single storage slot with its value."""

    slot: str
    raw_value: str
    variable: Optional[StorageVariable] = None
    decoded_value: Optional[DecodedValue] = None
    variable_path: Optional[str] = None


@dataclass
class StorageSnapshot:
    """Complete storage state at a block."""

    chain_id: int
    address: str
    block_number: int
    slots: list[SlotValue]
    is_complete: bool
    layout: Optional[StorageLayout] = None

    def to_dict(self) -> dict:
        """Serialize for caching."""
        return {
            "chain_id": self.chain_id,
            "address": self.address,
            "block_number": self.block_number,
            "is_complete": self.is_complete,
            "slots": [
                {
                    "slot": s.slot,
                    "raw_value": s.raw_value,
                    "variable_path": s.variable_path,
                    "variable": asdict(s.variable) if s.variable else None,
                    "decoded_value": s.decoded_value.to_dict() if s.decoded_value else None,
                }
                for s in self.slots
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StorageSnapshot":
        """Deserialize from cache."""
        slots = []
        for s in data.get("slots", []):
            variable = StorageVariable(**s["variable"]) if s.get("variable") else None
            decoded = None
            if s.get("decoded_value"):
                decoded = DecodedValue.from_dict(s["decoded_value"])
            slots.append(
                SlotValue(
                    slot=s["slot"],
                    raw_value=s["raw_value"],
                    variable=variable,
                    decoded_value=decoded,
                    variable_path=s.get("variable_path"),
                )
            )
        return cls(
            chain_id=data["chain_id"],
            address=data["address"],
            block_number=data["block_number"],
            slots=slots,
            is_complete=data["is_complete"],
            layout=None,  # Layout not stored in cache
        )


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

    def to_dict(self) -> dict:
        """Serialize for caching."""
        return {
            "chain_id": self.chain_id,
            "contract_address": self.contract_address,
            "tx_hash": self.tx_hash,
            "block_number": self.block_number,
            "is_complete": self.is_complete,
            "trace_unavailable": self.trace_unavailable,
            "contract_name": self.contract_name,
            "execution_order_available": self.execution_order_available,
            "frame_outcomes_available": self.frame_outcomes_available,
            "write_old_values_available": self.write_old_values_available,
            "final_state_values_available": self.final_state_values_available,
            "trace_step_count": self.trace_step_count,
            "changes": [
                {
                    "slot": c.slot,
                    "mapping_base_slot": c.mapping_base_slot,
                    "old_value": c.old_value,
                    "new_value": c.new_value,
                    "variable_path": c.variable_path,
                    "variable": asdict(c.variable) if c.variable else None,
                    "mapping_key": c.mapping_key,
                    "is_mapping": c.is_mapping,
                    "encoding": c.encoding,
                    "key_type": c.key_type,
                    "value_type": c.value_type,
                    "element_type_id": c.element_type_id,
                    "array_index": c.array_index,
                    "change_index": c.change_index,
                    "pc": c.pc,
                    "effect": c.effect,
                    "frame_id": c.frame_id,
                    "depth": c.depth,
                    "code_address": c.code_address,
                    "changed_value": c.changed_value,
                    "frame_outcome": c.frame_outcome,
                    "opcode": c.opcode,
                    "namespace": c.namespace,
                    "state_initial_value": c.state_initial_value,
                    "state_final_value": c.state_final_value,
                    "state_values_known": c.state_values_known,
                    "old_decoded": c.old_decoded.to_dict() if c.old_decoded else None,
                    "new_decoded": c.new_decoded.to_dict() if c.new_decoded else None,
                }
                for c in self.changes
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TransactionDiff":
        """Deserialize from cache."""
        changes = []
        for c in data.get("changes", []):
            variable = StorageVariable(**c["variable"]) if c.get("variable") else None
            old_decoded = (
                DecodedValue.from_dict(c["old_decoded"]) if c.get("old_decoded") else None
            )
            new_decoded = (
                DecodedValue.from_dict(c["new_decoded"]) if c.get("new_decoded") else None
            )
            changes.append(
                StorageChange(
                    slot=c["slot"],
                    mapping_base_slot=c.get("mapping_base_slot"),
                    old_value=c["old_value"],
                    new_value=c["new_value"],
                    variable=variable,
                    variable_path=c.get("variable_path"),
                    old_decoded=old_decoded,
                    new_decoded=new_decoded,
                    mapping_key=c.get("mapping_key"),
                    is_mapping=c.get("is_mapping", False),
                    encoding=c.get("encoding"),
                    key_type=c.get("key_type"),
                    value_type=c.get("value_type"),
                    element_type_id=c.get("element_type_id"),
                    array_index=c.get("array_index"),
                    change_index=c.get("change_index", 0),
                    pc=c.get("pc"),
                    effect=c.get("effect", "applied"),
                    frame_id=c.get("frame_id"),
                    depth=c.get("depth"),
                    code_address=c.get("code_address"),
                    changed_value=c.get("changed_value"),
                    frame_outcome=c.get("frame_outcome", "applied"),
                    opcode=c.get("opcode", "SSTORE"),
                    namespace=c.get("namespace", "persistent"),
                    state_initial_value=c.get("state_initial_value"),
                    state_final_value=c.get("state_final_value"),
                    state_values_known=c.get("state_values_known", True),
                )
            )
        return cls(
            chain_id=data["chain_id"],
            contract_address=data["contract_address"],
            tx_hash=data["tx_hash"],
            block_number=data["block_number"],
            changes=changes,
            is_complete=data["is_complete"],
            trace_unavailable=data.get("trace_unavailable", False),
            layout=None,
            contract_name=data.get("contract_name"),
            execution_order_available=data.get("execution_order_available", False),
            frame_outcomes_available=data.get("frame_outcomes_available", False),
            write_old_values_available=data.get("write_old_values_available", False),
            final_state_values_available=data.get("final_state_values_available", False),
            trace_step_count=data.get("trace_step_count"),
        )


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
    is_proxy: bool = False
    proxy_type: Optional[str] = None
    implementation_address: Optional[str] = None
    is_verified: bool = False
    verification_source: Optional[str] = None
    name: Optional[str] = None
    compiler_version: Optional[str] = None
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
