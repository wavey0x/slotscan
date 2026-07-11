"""Pydantic models for API request/response validation."""

from typing import Any, Optional

from pydantic import BaseModel, Field


# === Value Types ===


class ValuePair(BaseModel):
    """Encoded and decoded value pair."""

    value_encoded: Optional[str]
    value_decoded: Optional[Any] = None


class ValuePairDecoded(BaseModel):
    """Decoded value only (for packed fields where encoded is shared)."""

    value_decoded: Optional[Any] = None


# === Response Models ===


class ContractResponse(BaseModel):
    """Contract metadata response."""

    chain_id: int
    address: str
    name: Optional[str] = None
    code_hash: Optional[str] = None

    is_proxy: bool
    proxy_type: Optional[str] = None
    implementation_address: Optional[str] = None

    is_verified: bool
    verification_source: Optional[str] = None
    compiler_version: Optional[str] = None

    has_layout: bool


class StorageTypeResponse(BaseModel):
    """Storage type definition."""

    id: str
    label: str
    kind: str
    encoding: str
    num_bytes: Optional[int] = None
    element_type: Optional[str] = None
    array_length: Optional[int] = None
    key_type: Optional[str] = None
    value_type: Optional[str] = None


class StorageVariableResponse(BaseModel):
    """Storage variable definition."""

    name: str
    slot: int
    offset: int
    size: int
    type_id: str
    type_label: str
    provenance: str = "compiler_layout"
    confidence: str = "exact"


class StorageLayoutResponse(BaseModel):
    """Full storage layout."""

    contract_name: str
    variables: list[StorageVariableResponse]
    types: dict[str, StorageTypeResponse]


class SlotValueResponse(BaseModel):
    """A single slot with its value."""

    slot: str
    value_encoded: str
    value_decoded: Optional[Any] = None
    variable_name: Optional[str] = None
    variable_path: Optional[str] = None
    type_label: Optional[str] = None


class StorageSnapshotResponse(BaseModel):
    """Storage state at a block."""

    chain_id: int
    address: str
    block_number: int
    slots: list[SlotValueResponse]
    is_complete: bool
    is_verified: bool
    layout_available: bool = True


class StorageChangeResponse(BaseModel):
    """A single storage change (interim step)."""

    before: ValuePair
    after: ValuePair
    pc: Optional[int] = None  # Program counter of the SSTORE operation
    step: Optional[int] = None  # Sequence number in overall transaction execution
    effect: str = "applied"
    storage_address: Optional[str] = None
    code_address: Optional[str] = None
    changed_value: Optional[bool] = None
    frame_outcome: str = "applied"
    frame_id: Optional[int] = None
    depth: Optional[int] = None
    opcode: str = "SSTORE"
    namespace: str = "persistent"


class PackedFieldResponse(BaseModel):
    """A single field within a packed storage slot."""

    name: str
    type_label: str
    offset: int
    size: int
    before: ValuePairDecoded
    after: ValuePairDecoded


class StructMemberResponse(BaseModel):
    """A single member of a struct definition."""

    name: str
    type_label: str
    slot_offset: int  # Offset within struct (e.g., 0, 1, 2, 3, 4, 5)
    byte_offset: int  # Byte offset within the slot
    size: int  # Size in bytes


class StructDefinitionResponse(BaseModel):
    """Full struct definition with all members."""

    name: str  # Struct type name (e.g., "RewardData")
    members: list[StructMemberResponse]


class MappingParamResponse(BaseModel):
    """A single mapping parameter (key) with its type and value."""

    type: str  # Type of the key (e.g., "address", "uint256")
    value: str  # The actual key value
    label: Optional[str] = None  # Optional resolved label (ENS, contract name)


class SlotChangeResponse(BaseModel):
    """All changes to a single slot, grouped together."""

    slot: str
    slot_decimal: Optional[str] = None  # Decimal representation (only for static slots)
    is_static_slot: bool = False  # True only when proven by the layout index
    provenance: str = "raw"
    confidence: str = "unknown"
    namespace: str = "persistent"
    net_changed: Optional[bool] = None
    classification: str = "unknown"
    first_write_step: Optional[int] = None
    last_write_step: Optional[int] = None
    event_count: int = 0
    state_values_known: bool = True
    variable_name: Optional[str] = None
    variable_path: Optional[str] = None
    resolved_paths: list[str] = Field(default_factory=list)
    type_label: Optional[str] = None

    # Unified mapping params (replaces separate key/type arrays)
    params: Optional[list[MappingParamResponse]] = None  # Mapping parameters with types
    mapping_base_slot: Optional[int] = None
    is_mapping: bool = False  # Whether this is a mapping entry
    is_dynamic_array: bool = False  # Whether this is a dynamic array entry
    array_index: Optional[int] = None  # Index for dynamic array entries
    encoding: Optional[str] = None  # Type encoding (inplace, mapping, bytes, etc.)
    value_type: Optional[str] = None  # Value type for mappings (cleaned up)

    # Summary: first and last values
    before: ValuePair
    after: ValuePair

    # Packed storage fields (multiple values in one slot)
    packed_fields: Optional[list[PackedFieldResponse]] = None
    struct_field: Optional[str] = None  # Resolved struct field name (e.g., "lockStart")

    # Struct definition (when this slot is part of a struct)
    struct_definition: Optional[StructDefinitionResponse] = None

    # All interim changes (sorted by step)
    changes: list[StorageChangeResponse] = Field(default_factory=list)


class TransactionDiffResponse(BaseModel):
    """Storage changes in a transaction, grouped by slot."""

    chain_id: int
    address: str
    tx_hash: str
    block_number: int
    slots: list[SlotChangeResponse]  # Changes grouped by slot
    is_complete: bool
    is_verified: bool
    trace_unavailable: bool = False
    contract_name: Optional[str] = None  # Name of the contract
    layout_available: bool = False  # Whether storage layout was available
    execution_order_available: bool = False  # True if step values are real EVM execution order
    frame_outcomes_available: bool = False
    write_old_values_available: bool = False
    final_state_values_available: bool = False
    trace_step_count: Optional[int] = None


class TransactionCapabilitiesResponse(BaseModel):
    """Trace-wide evidence guarantees for transaction history."""

    write_history_complete: bool
    values_complete: bool
    rollback_classification_complete: bool
    execution_order_available: bool
    final_state_values_available: bool
    state_reconciliation_complete: bool
    address_attribution_complete: bool
    code_attribution_complete: bool


class TransactionSummaryResponse(BaseModel):
    storage_owners: int
    slots_written: int
    sstore_events: int
    net_changed_slots: int
    restored_slots: int
    reverted_only_slots: int
    noop_only_slots: int
    reverted_writes: int
    noop_writes: int
    resolved_slots: int


class ContractHistoryCountsResponse(BaseModel):
    slots_written: int
    sstore_events: int
    net_changed_slots: int
    restored_slots: int
    reverted_only_slots: int
    noop_only_slots: int
    reverted_writes: int
    noop_writes: int


class ContractResolutionResponse(BaseModel):
    resolved: int
    total: int


class ContractHistoryResponse(BaseModel):
    storage_address: str
    name: Optional[str] = None
    is_proxy: bool = False
    is_verified: bool = False
    implementation_addresses: list[str] = Field(default_factory=list)
    code_addresses: list[str] = Field(default_factory=list)
    first_write_step: Optional[int] = None
    last_write_step: Optional[int] = None
    layout_available: bool = False
    resolution: ContractResolutionResponse
    counts: ContractHistoryCountsResponse
    errors: list[str] = Field(default_factory=list)
    slots: list[SlotChangeResponse] = Field(default_factory=list)


class GlobalStorageEventReferenceResponse(BaseModel):
    """Reference into contracts[].slots[].changes without duplicating events."""

    ordinal: int
    step: Optional[int] = None
    storage_address: str
    slot: str
    event_index: int


class TransactionStorageHistoryResponse(BaseModel):
    chain_id: int
    tx_hash: str
    block_number: int
    status: str
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    created_contract: Optional[str] = None
    analysis_version: int = 5
    capabilities: TransactionCapabilitiesResponse
    summary: TransactionSummaryResponse
    contracts: list[ContractHistoryResponse] = Field(default_factory=list)
    global_order: Optional[list[GlobalStorageEventReferenceResponse]] = None
    is_complete: bool
    trace_unavailable: bool = False


class ErrorResponse(BaseModel):
    """Error response."""

    error: str
    code: str
    details: Optional[dict] = None
