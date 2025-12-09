"""Pydantic models for API request/response validation."""

from typing import Any, Optional

from pydantic import BaseModel, Field


# === Value Types ===


class ValuePair(BaseModel):
    """Encoded and decoded value pair."""

    value_encoded: str
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
    is_static_slot: bool = False  # True if slot < 100 (not a keccak256 hash)
    variable_name: Optional[str] = None
    variable_path: Optional[str] = None
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


class ErrorResponse(BaseModel):
    """Error response."""

    error: str
    code: str
    details: Optional[dict] = None
