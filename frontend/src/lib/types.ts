// === Value Types ===

export interface ValuePair {
  value_encoded: string | null;
  value_decoded: unknown;
}

export interface ValuePairDecoded {
  value_decoded: unknown;
}

// === Response Types ===

export interface ContractResponse {
  chain_id: number;
  address: string;
  name: string | null;
  code_hash: string | null;
  is_proxy: boolean;
  proxy_type: string | null;
  implementation_address: string | null;
  is_verified: boolean;
  verification_source: string | null;
  compiler_version: string | null;
  has_layout: boolean;
}

export interface StorageTypeResponse {
  id: string;
  label: string;
  kind: string;
  encoding: string;
  num_bytes: number | null;
  element_type: string | null;
  array_length: number | null;
  key_type: string | null;
  value_type: string | null;
}

export interface StorageVariableResponse {
  name: string;
  slot: number;
  offset: number;
  size: number;
  type_id: string;
  type_label: string;
  provenance: string;
  confidence: string;
}

export interface StorageLayoutResponse {
  contract_name: string;
  variables: StorageVariableResponse[];
  types: Record<string, StorageTypeResponse>;
}

export interface SlotValueResponse {
  slot: string;
  value_encoded: string;
  value_decoded: unknown;
  variable_name: string | null;
  variable_path: string | null;
  type_label: string | null;
}

export interface StorageSnapshotResponse {
  chain_id: number;
  address: string;
  block_number: number;
  slots: SlotValueResponse[];
  is_complete: boolean;
  is_verified: boolean;
}

export interface StorageChangeResponse {
  // A single interim change (one SSTORE)
  before: ValuePair;
  after: ValuePair;
  pc: number | null;
  step: number | null; // Sequence number in overall transaction execution
  effect: 'applied' | 'noop' | 'reverted';
  storage_address: string | null;
  code_address: string | null;
  changed_value: boolean | null;
  frame_outcome: 'applied' | 'reverted';
  frame_id: number | null;
  depth: number | null;
  opcode: 'SSTORE' | 'TSTORE';
  namespace: 'persistent' | 'transient';
}

export interface PackedFieldResponse {
  // A single field within a packed storage slot
  name: string;
  type_label: string;
  offset: number;
  size: number;
  before: ValuePairDecoded;
  after: ValuePairDecoded;
}

export interface StructMemberResponse {
  // A single member of a struct definition
  name: string;
  type_label: string;
  slot_offset: number;  // Offset within struct (e.g., 0, 1, 2, 3, 4, 5)
  byte_offset: number;  // Byte offset within the slot
  size: number;  // Size in bytes
}

export interface StructDefinitionResponse {
  // Full struct definition with all members
  name: string;  // Struct type name (e.g., "RewardData")
  members: StructMemberResponse[];
}

export interface MappingParamResponse {
  // A single mapping parameter (key) with its type and value
  type: string;  // Type of the key (e.g., "address", "uint256")
  value: string;  // The actual key value
  label?: string | null;  // Optional resolved label (ENS, contract name)
}

export interface SlotChangeResponse {
  // All changes to a single slot, grouped together
  slot: string;
  slot_decimal: string | null;
  is_static_slot: boolean;  // True only when proven by the layout index
  provenance: string;
  confidence: 'exact' | 'inferred' | 'unknown';
  namespace: 'persistent' | 'transient';
  net_changed: boolean | null;
  classification: 'net_changed' | 'restored' | 'reverted_only' | 'noop_only' | 'unchanged' | 'unknown';
  first_write_step: number | null;
  last_write_step: number | null;
  event_count: number;
  state_values_known: boolean;
  variable_name: string | null;
  variable_path: string | null;
  resolved_paths: string[];
  type_label: string | null;
  // Unified mapping params
  params: MappingParamResponse[] | null;  // Mapping parameters with types and values
  mapping_base_slot: number | null;
  is_mapping: boolean;
  is_dynamic_array: boolean;
  array_index: number | null;
  encoding: string | null;
  value_type: string | null;
  // Summary: before (initial) and after (final) values
  before: ValuePair;
  after: ValuePair;
  // Packed storage fields (multiple values in one slot)
  packed_fields: PackedFieldResponse[] | null;
  struct_field: string | null; // Resolved struct field name (e.g., "lockStart")
  // Struct definition (when this slot is part of a struct)
  struct_definition: StructDefinitionResponse | null;
  // All interim changes (sorted by step)
  changes: StorageChangeResponse[];
}

export interface TransactionDiffResponse {
  chain_id: number;
  address: string;
  tx_hash: string;
  block_number: number;
  slots: SlotChangeResponse[];
  is_complete: boolean;
  is_verified: boolean;
  trace_unavailable: boolean;
  contract_name: string | null;
  layout_available: boolean;
  execution_order_available: boolean; // True if step values are real EVM execution order
  frame_outcomes_available: boolean;
  write_old_values_available: boolean;
  final_state_values_available: boolean;
  trace_step_count: number | null;
}

export interface TransactionCapabilitiesResponse {
  write_history_complete: boolean;
  values_complete: boolean;
  rollback_classification_complete: boolean;
  execution_order_available: boolean;
  final_state_values_available: boolean;
  state_reconciliation_complete: boolean;
  address_attribution_complete: boolean;
  code_attribution_complete: boolean;
}

export interface TransactionSummaryResponse {
  storage_owners: number;
  slots_written: number;
  sstore_events: number;
  net_changed_slots: number;
  restored_slots: number;
  reverted_only_slots: number;
  noop_only_slots: number;
  reverted_writes: number;
  noop_writes: number;
  resolved_slots: number;
}

export interface ContractHistoryCountsResponse {
  slots_written: number;
  sstore_events: number;
  net_changed_slots: number;
  restored_slots: number;
  reverted_only_slots: number;
  noop_only_slots: number;
  reverted_writes: number;
  noop_writes: number;
}

export interface ContractHistoryResponse {
  storage_address: string;
  name: string | null;
  is_proxy: boolean;
  is_verified: boolean;
  implementation_addresses: string[];
  code_addresses: string[];
  first_write_step: number | null;
  last_write_step: number | null;
  layout_available: boolean;
  resolution: { resolved: number; total: number };
  counts: ContractHistoryCountsResponse;
  errors: string[];
  slots: SlotChangeResponse[];
}

export interface GlobalStorageEventReferenceResponse {
  ordinal: number;
  step: number | null;
  storage_address: string;
  slot: string;
  event_index: number;
}

export interface TransactionStorageHistoryResponse {
  chain_id: number;
  tx_hash: string;
  block_number: number;
  status: 'success' | 'reverted';
  from_address: string | null;
  to_address: string | null;
  created_contract: string | null;
  analysis_version: number;
  capabilities: TransactionCapabilitiesResponse;
  summary: TransactionSummaryResponse;
  contracts: ContractHistoryResponse[];
  global_order: GlobalStorageEventReferenceResponse[] | null;
  is_complete: boolean;
  trace_unavailable: boolean;
}

export interface ErrorResponse {
  error: string;
  code: string;
  details?: Record<string, unknown>;
}

export interface LayoutErrorResponse {
  error: string;
  code: 'NOT_CONTRACT' | 'NOT_VERIFIED' | 'NO_LAYOUT' | 'PROXY_IMPL_NOT_VERIFIED' | 'LAYOUT_PARSE_ERROR' | 'RPC_ERROR';
  proxy_type?: string;
  implementation_address?: string;
}

// === Layout Page Types ===

export interface ComputedSlotLookup {
  keys?: string[];           // for mappings - the key values used
  index?: number;            // for arrays - the index used
  computedSlot: string;      // hex slot address
  rawValue: string;          // hex raw value
  decodedValue: unknown;     // decoded value
}
