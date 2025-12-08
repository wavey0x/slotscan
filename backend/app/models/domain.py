"""Domain models for StorageScan."""

from dataclasses import dataclass, field, asdict
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
        Does not attempt to resolve mapping/dynamic array elements (requires keys/indices).
        """
        for var in self.variables:
            var_type = self.types.get(var.type_id)
            if not var_type:
                continue

            # Skip mappings/dynamic arrays; without keys/indices we can't map hashed slots
            if var_type.encoding in ("mapping", "dynamic_array"):
                continue

            span_slots = max(1, (var.size + 31) // 32 if var.size else 1)
            if var.slot <= slot < var.slot + span_slots:
                return var
        return None

    def get_mapping_by_base_slot(self, slot: int) -> Optional[StorageVariable]:
        """Find mapping variable whose base slot matches."""
        for var in self.variables:
            if var.slot == slot:
                var_type = self.types.get(var.type_id)
                if var_type and var_type.encoding == "mapping":
                    return var
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

    def get_type(self, type_id: str) -> Optional[StorageType]:
        """Get type definition by ID."""
        return self.types.get(type_id)

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
        )


@dataclass
class DecodedValue:
    """A decoded storage value."""

    raw: str
    decoded: Any
    type_label: str
    display: str


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
                    "decoded_value": (
                        {
                            "raw": s.decoded_value.raw,
                            "decoded": s.decoded_value.decoded,
                            "type_label": s.decoded_value.type_label,
                            "display": s.decoded_value.display,
                        }
                        if s.decoded_value
                        else None
                    ),
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
                decoded = DecodedValue(**s["decoded_value"])
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
    old_value: str
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
                    "change_index": c.change_index,
                    "pc": c.pc,
                    "old_decoded": (
                        {
                            "raw": c.old_decoded.raw,
                            "decoded": c.old_decoded.decoded,
                            "type_label": c.old_decoded.type_label,
                            "display": c.old_decoded.display,
                        }
                        if c.old_decoded
                        else None
                    ),
                    "new_decoded": (
                        {
                            "raw": c.new_decoded.raw,
                            "decoded": c.new_decoded.decoded,
                            "type_label": c.new_decoded.type_label,
                            "display": c.new_decoded.display,
                        }
                        if c.new_decoded
                        else None
                    ),
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
                DecodedValue(**c["old_decoded"]) if c.get("old_decoded") else None
            )
            new_decoded = (
                DecodedValue(**c["new_decoded"]) if c.get("new_decoded") else None
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
                    change_index=c.get("change_index", 0),
                    pc=c.get("pc"),
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
        )


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
