// === Value Types ===

interface ValuePair {
  value_encoded: string | null;
  value_decoded: unknown;
}

interface ValuePairDecoded {
  value_decoded: unknown;
}

// === Response Types ===

interface StorageViewContract {
  address: string;
  storage_address: string;
  effective_code_address: string;
  name: string | null;
  is_proxy: boolean;
  proxy_type: string | null;
  is_verified: boolean;
  layout_provenance: 'verified_source' | 'bytecode_equivalent' | null;
  layout_source_address: string | null;
}

interface StorageViewMember {
  name: string;
  slot: string;
  byte_offset: number;
  byte_size: string;
  type_id: string;
  label: string;
}

export interface StorageViewType {
  id: string;
  label: string;
  kind: string;
  encoding: string;
  num_bytes: string | null;
  base_type: string | null;
  element_type: string | null;
  array_length: string | null;
  key_type: string | null;
  value_type: string | null;
  members: StorageViewMember[];
}

export interface StorageViewVariable {
  declaration_id: string;
  name: string;
  slot: string;
  byte_offset: number;
  byte_size: string;
  type_id: string;
  type_label: string;
  provenance: string;
  confidence: string;
}

export interface StorageViewValueItem {
  declaration_id: string;
  path: string;
  status: 'ok' | 'on_demand' | 'unsupported' | 'deferred_budget';
  slot: string;
  byte_offset: number;
  value_encoded: string | null;
  value_decoded: unknown;
}

export interface StorageViewResponse {
  block_ref: {
    number: string;
    hash: string;
  };
  contract: StorageViewContract;
  layout_id: string | null;
  layout: {
    status: 'ok' | 'unverified' | 'unsupported';
    variables: StorageViewVariable[];
    types: Record<string, StorageViewType>;
    storage_rules: {
      mapping_preimage_order: 'key_then_slot' | 'slot_then_key';
      array_storage_scheme: 'solidity' | 'vyper_sequential' | 'vyper_legacy_hashed';
    } | null;
  };
  values: {
    status: 'ok' | 'error' | 'unavailable';
    items: StorageViewValueItem[];
    error_code: string | null;
  };
}

export interface StorageQueryRequest {
  chain_id: string;
  address: string;
  block_ref: {
    number: string;
    hash: string;
  };
  layout_id: string;
  access: {
    declaration_id: string;
    steps: Array<{
      kind: 'mapping_key' | 'array_index';
      value: string;
    }>;
  };
}

export interface StorageQueryResponse {
  block_ref: {
    number: string;
    hash: string;
  };
  layout_id: string;
  declaration_id: string;
  path: string;
  location: {
    slot: string;
    byte_offset: number;
    byte_size: number;
  };
  value_encoded: string;
  value_decoded: unknown;
  array_length: string | null;
}

export interface StorageQueryLookup {
  keys?: string[];
  index?: string;
  slot: string;
  rawValue: string;
  decodedValue: unknown;
}

interface ComparisonScope {
  id: string;
  kind: 'default' | 'erc7201';
  root_slot: string;
  formula: string | null;
}

interface ComparisonLocation {
  slot: string;
  byte_offset: number;
  byte_size: string;
  end_slot: string;
  is_root: boolean;
}

interface ComparisonType {
  label: string;
  kind: string;
  encoding: string;
  byte_size: string;
  array_length: string | null;
  element_stride: string | null;
}

export interface ComparisonRegion {
  scope: ComparisonScope;
  location: ComparisonLocation;
  path: string;
  type: ComparisonType;
}

export interface ComparisonEntry {
  id: string;
  impact: 'conflict' | 'ambiguous' | 'none';
  kind: string;
  from_region: ComparisonRegion | null;
  to_region: ComparisonRegion | null;
  details: string[];
}

export interface ComparisonSummary {
  conflicts: number;
  ambiguous: number;
  changes: number;
  unchanged: number;
}

export interface ResolvedLayoutSubject {
  input_address: string;
  storage_address: string;
  code_address: string;
  kind: 'direct' | 'proxy' | 'eip7702';
  block_ref: {
    number: string;
    hash: string;
  };
  name: string | null;
  layout_provenance: 'verified_source' | 'bytecode_equivalent' | null;
  layout_source_address: string | null;
  layout_status:
    | 'ok'
    | 'unverified'
    | 'unsupported'
    | 'non_exact'
    | 'not_contract'
    | 'invalid_layout';
}

export interface LayoutComparisonResponse {
  chain_id: number;
  verdict: 'no_conflicts' | 'conflicts' | 'indeterminate' | 'unavailable';
  from_subject: ResolvedLayoutSubject | null;
  to_subject: ResolvedLayoutSubject | null;
  summary: ComparisonSummary | null;
  entries: ComparisonEntry[];
  limitations: string[];
}

export interface LayoutComparisonRequest {
  fromAddress: string;
  toAddress: string;
  fromBlock?: string;
  fromBlockHash?: string;
  toBlock?: string;
  toBlockHash?: string;
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

interface StructMemberResponse {
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

interface MappingParamResponse {
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

interface TransactionCapabilitiesResponse {
  write_history_complete: boolean;
  values_complete: boolean;
  rollback_classification_complete: boolean;
  execution_order_available: boolean;
  final_state_values_available: boolean;
  state_reconciliation_complete: boolean;
  address_attribution_complete: boolean;
  code_attribution_complete: boolean;
}

interface TransactionSummaryResponse {
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

interface ContractHistoryCountsResponse {
  slots_written: number;
  sstore_events: number;
  net_changed_slots: number;
  restored_slots: number;
  reverted_only_slots: number;
  noop_only_slots: number;
  reverted_writes: number;
  noop_writes: number;
}

export type ContractResolutionStatus =
  | 'resolved'
  | 'no_verified_source'
  | 'timed_out'
  | 'failed'
  | 'not_resolved';

export interface ContractHistoryResponse {
  storage_address: string;
  name: string | null;
  is_proxy: boolean;
  is_verified: boolean;
  layout_provenance: 'verified_source' | 'bytecode_equivalent' | null;
  layout_source_address: string | null;
  implementation_addresses: string[];
  code_addresses: string[];
  first_write_step: number | null;
  last_write_step: number | null;
  layout_available: boolean;
  resolution_status: ContractResolutionStatus;
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
  capabilities: TransactionCapabilitiesResponse;
  summary: TransactionSummaryResponse;
  contracts: ContractHistoryResponse[];
  global_order: GlobalStorageEventReferenceResponse[] | null;
  is_complete: boolean;
  trace_unavailable: boolean;
  degraded_reason: 'trace_limit' | 'tracer_unavailable' | null;
}
