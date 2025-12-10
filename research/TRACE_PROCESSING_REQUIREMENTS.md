# Trace Processing Requirements

This document enumerates all data collection and processing requirements for trace processing in SlotScan. It is derived from the current implementation and identifies what is currently implemented, what is partially implemented, and what is missing.

## Table of Contents

1. [Overview](#overview)
2. [Trace Collection Requirements](#trace-collection-requirements)
3. [Slot Matching Requirements](#slot-matching-requirements)
4. [Type Decoding Requirements](#type-decoding-requirements)
5. [API Response Requirements](#api-response-requirements)
6. [Known Limitations & Next Steps](#known-limitations--next-steps)

---

## Overview

SlotScan traces Ethereum transactions to extract and decode storage changes for a specific contract. The process involves:

1. **Trace Execution**: Running `debug_traceTransaction` to capture all SSTORE operations
2. **SHA3 Preimage Collection**: Capturing keccak256 inputs to decode mapping keys
3. **Slot Matching**: Mapping raw storage slots to variable names using storage layout
4. **Type Decoding**: Converting raw hex values to typed Solidity values
5. **API Response Building**: Structuring data for frontend display

---

## Trace Collection Requirements

### REQ-TRACE-001: SSTORE Operation Capture

**Status**: ✅ Implemented

Must capture all SSTORE operations with:
- `slot`: The storage slot being written (32-byte hex)
- `value`: The new value being stored (32-byte hex)
- `pc`: Program counter (for debugging/ordering)
- `index`: Execution order index
- `address`: Contract address performing the write
- `depth`: Call depth (for nested calls)

**Implementation**: `TransactionTracer.STORAGE_TRACER` (JS tracer) and `_execute_structlogs_trace()` (Reth fallback)

### REQ-TRACE-002: SHA3/Keccak256 Preimage Capture

**Status**: ✅ Implemented

Must capture SHA3 operations to decode mapping keys:
- `preimage`: The data being hashed (64-128 bytes for mappings)
- `hash`: The resulting keccak256 hash
- `address`: Contract address
- `size`: Preimage size (64 bytes = single mapping, 96+ = nested)

**Implementation**: Captured in `STORAGE_TRACER` and `_execute_structlogs_trace()`

### REQ-TRACE-003: Pre-State Storage Capture

**Status**: ✅ Implemented

Must capture initial storage state using `prestateTracer` with `diffMode: true`:
- Pre-transaction storage values for all affected slots
- Post-transaction storage values (for validation)

**Implementation**: `_execute_trace()` with `prestateTracer`

### REQ-TRACE-004: Candidate Address Collection

**Status**: ✅ Implemented

Must collect potential mapping key addresses from:
- Transaction sender (`from`)
- Transaction recipient (`to`)
- Event log addresses (from receipt)
- Internal call addresses (from trace)

**Implementation**: `_collect_candidate_addresses()`

### REQ-TRACE-005: Candidate uint256 Collection

**Status**: ✅ Implemented

Must collect potential mapping key uint256 values from:
- Event log topics (token IDs, amounts)
- Small integers (0-1000) for common indices

**Implementation**: `_collect_candidate_uint256_values()`

### REQ-TRACE-006: Multiple Node Type Support

**Status**: ✅ Implemented

Must support different node implementations:
- **Geth**: Custom JS tracer (preferred)
- **Reth**: structLogs fallback with memory parsing
- **Other**: graceful degradation to prestateTracer only

**Implementation**: `_execute_storage_trace()` with fallback chain

### REQ-TRACE-007: Intermediate Write Capture

**Status**: ✅ Implemented

Must capture ALL writes to a slot, not just the final diff:
- Multiple writes to same slot within one transaction
- Each write preserves its execution order (index)
- Each write preserves its program counter (PC)

**Implementation**: `_build_changes_from_sstore_trace()`

### REQ-TRACE-008: No-Drop Guarantee on SSTORE Events

**Status**: ✅ Implemented (must remain)

Must never drop or filter SSTORE entries after collection, even if later decoding/matching fails:
- Every captured SSTORE must appear in the decoded change list with raw values intact
- Decoding/matching errors must be logged and surfaced but must not remove the change
- Unmatched slots still return `variable_name = null` with raw `old_value/new_value`

**Implementation**: `_decode_changes()` must propagate all collected writes regardless of decode/match outcome

### REQ-TRACE-009: Prestate Reconciliation

**Status**: ✅ Implemented

Must merge `prestateTracer` diffs with the SSTORE tracer output so missing writes are never dropped:
- Compare slots captured by SSTORE against pre/post-state diff
- Any slots present only in the pre/post diff are added as synthetic changes
- Execution order is downgraded (marked unordered) when synthetic entries are merged

**Implementation**: `TransactionTracer.trace_transaction()` merges `_extract_contract_changes()` output into SSTORE results and disables strict ordering when synthetic slots are added

---

## Slot Matching Requirements

### REQ-MATCH-001: Static Slot Matching

**Status**: ✅ Implemented

Must match slots 0-100 (approximately) to static variables:
- Direct slot to variable mapping
- Multi-slot variables (bytes32[], large structs)
- Packed storage (multiple variables in one slot)

**Implementation**: `StorageLayout.get_variable_for_slot()`

### REQ-MATCH-002: Packed Storage Detection

**Status**: ✅ Implemented

Must detect and decode packed storage:
- Multiple variables sharing a single 32-byte slot
- Each variable has offset (byte position) and size
- Examples: `uint128 + uint128`, `address + bool + uint32`

**Implementation**: `StorageLayout.get_all_variables_in_slot()`, `TypeDecoder.decode_packed_slot()`

### REQ-MATCH-003: Simple Mapping Slot Resolution

**Status**: ✅ Implemented

Must resolve mapping slots via SHA3 preimage lookup:
- Slot = keccak256(key . baseSlot) where `.` is concatenation
- Preimage format: 32-byte key + 32-byte base slot
- Support for address, uint256, bytes32 keys

**Implementation**: `_try_match_slot_from_preimage()`

### REQ-MATCH-004: Nested Mapping Support

**Status**: ✅ Implemented

Must support nested mappings (e.g., `mapping(address => mapping(address => uint256))`):
- Outer slot = keccak256(outerKey . baseSlot)
- Inner slot = keccak256(innerKey . outerSlot)
- Chain preimage lookups to resolve full key path

**Implementation**: `_try_match_slot_from_preimage()` with recursive lookup

### REQ-MATCH-005: Mapping to Struct Resolution

**Status**: ✅ Implemented

Must handle mappings that point to structs:
- Base slot = keccak256(key . baseSlot)
- Struct field slot = baseSlot + fieldOffset
- Must resolve struct field name from offset

**Implementation**: `_resolve_struct_field()`, struct offset detection in `_decode_changes()`

### REQ-MATCH-006: Dynamic Array Base Slot Resolution

**Status**: ✅ Implemented

Must handle dynamic arrays (`Type[]`):
- Length stored at base slot
- Data stored at keccak256(baseSlot) + index * elementSlots
- Must compute array index from slot offset

**Implementation**: `_try_match_dynamic_array_slot()`, `_build_dynamic_array_index()`

### REQ-MATCH-007: Dynamic Array of Structs

**Status**: ✅ Implemented

Must handle dynamic arrays of structs:
- Array index = (slot - dataStart) // elementSlots
- Struct field offset = (slot - dataStart) % elementSlots
- Must resolve both array index AND struct field name

**Implementation**: `_try_match_dynamic_array_slot()` handles multi-slot elements

### REQ-MATCH-008: Variable Path Generation

**Status**: ✅ Implemented

Must generate human-readable variable paths:
- Simple: `balances`
- Mapping: `balances[0x1234...5678]`
- Nested mapping: `allowances[0x1234...][0x5678...]`
- Struct field: `accountData[0x1234...].balance`
- Array element: `proposals[3].votesFor`

**Implementation**: Throughout `_decode_changes()` and matching functions

### REQ-MATCH-009: Struct Offset Detection (Without Preimage)

**Status**: ✅ Implemented

Must detect struct member access when base slot is known:
- If slot X is unmatched but slot X-N (N=1-9) is in preimage lookup
- This indicates struct member at offset N
- Path: `variable[key].fieldAtOffset`

**Implementation**: Struct offset detection in `_decode_changes()` and `_try_match_slot_from_preimage()`

---

## Type Decoding Requirements

### REQ-DECODE-001: Basic Type Decoding

**Status**: ✅ Implemented

Must decode all basic Solidity types:
- `bool`: Single byte, 0 = false, non-zero = true
- `address`: 20 bytes, right-aligned, checksummed output
- `uintN`: N bits, big-endian unsigned
- `intN`: N bits, two's complement signed
- `bytesN`: N bytes, left-aligned

**Implementation**: `TypeDecoder._decode_by_type()`

### REQ-DECODE-002: Packed Value Extraction

**Status**: ✅ Implemented

Must extract values from packed slots:
- Storage is right-aligned (offset from right)
- Extract `size` bytes starting at `offset` from right
- `start = 32 - offset - size`, `end = 32 - offset`

**Implementation**: `TypeDecoder.decode()` with offset parameter

### REQ-DECODE-003: Heuristic Decoding

**Status**: ✅ Implemented

Must provide heuristic decoding when type info unavailable:
- Zero detection
- Small integer detection (< 10^18)
- Address pattern detection (12 leading zero bytes)
- Large integer / bytes32 fallback

**Implementation**: `TypeDecoder.decode_heuristic()`

### REQ-DECODE-004: Contract Type Decoding

**Status**: ✅ Implemented

Must decode contract types as addresses:
- Contract types stored as 20-byte addresses
- Display with checksum formatting

**Implementation**: `TypeDecoder._decode_by_type()` handles `kind == "contract"`

### REQ-DECODE-005: Enum Decoding

**Status**: ✅ Implemented

Must decode enums as unsigned integers:
- Enums stored as smallest uint that fits all values
- Display as integer (name resolution not implemented)

**Implementation**: `TypeDecoder._decode_by_type()` handles "enum" in label

### REQ-DECODE-006: Display Formatting

**Status**: ✅ Implemented

Must format decoded values for display:
- Addresses: `0xAbCd...EfGh` (truncated)
- Integers: comma-separated (e.g., `1,234,567`)
- Booleans: `true` / `false`
- Hex strings: truncated with ellipsis

**Implementation**: `TypeDecoder.format_value()`

### REQ-DECODE-007: Custom Struct Decoding (Per-Known ABI)

**Status**: ⚠️ Partially Implemented

Must decode known ABI structs into per-field objects (not a single bigint/hex):
- Use metadata/ABI/layout to recognize structs such as `ResupplyPairCore.CurrentRateInfo`, `ResupplyPairCore.ExchangeRateInfo`, `RewardDistributorMultiEpoch.RewardType`
- For packed single-slot structs, split fields by declared widths/order
- For multi-slot structs/struct arrays, decode each slot by offset and assemble a field map
- Preserve both structured `decoded` and human-readable `display`

**Implementation Gap**: Add per-struct decoders and array-element handling in `TypeDecoder` / tracer; ensure arrays of structs return element-level decoded objects.

### REQ-DECODE-008: Decode-Fallback Safety

**Status**: ✅ Implemented (must remain)

Decoding errors must not break response construction:
- If typed decoding fails, fall back to heuristic decoding
- If heuristic decoding fails, return raw hex as display/decoded
- Never raise exceptions that prevent a change from being returned

---

## API Response Requirements

### REQ-API-001: Change Grouping by Slot

**Status**: ✅ Implemented

Must group all changes to the same slot:
- Multiple writes to same slot in one transaction
- Sort by execution order (change_index)
- Provide initial (before) and final (after) values

**Implementation**: `_group_changes_by_slot()`

### REQ-API-002: Mapping Parameter Display

**Status**: ✅ Implemented

Must provide mapping access parameters:
- `params`: Array of `{type, value}` for each mapping level
- Support nested mappings with multiple keys
- Extract key types from storage layout

**Implementation**: `_build_mapping_params()`, `_get_mapping_key_types()`

### REQ-API-003: Struct Definition Exposure

**Status**: ✅ Implemented

Must expose struct definitions for context:
- Struct name and members list
- Each member: name, type, slot offset, byte offset, size
- For mappings-to-structs and arrays-of-structs

**Implementation**: `_get_struct_definition()`, `_get_struct_definition_from_type_id()`

### REQ-API-004: Packed Fields Response

**Status**: ✅ Implemented

Must provide decoded packed field values:
- For static packed slots AND mapping-to-struct base slots
- Each field: name, type, offset, size, initial/final values
- Both decoded value and display string

**Implementation**: `PackedFieldResponse` in `_group_changes_by_slot()`

### REQ-API-005: Struct Field Resolution

**Status**: ✅ Implemented

Must resolve struct field names from offsets:
- When accessing `mapping[key].field` or `array[i].field`
- Extract field name from variable_path (e.g., "lockStart" from "data[addr].lockStart")
- Provide struct definition for context

**Implementation**: `struct_field` extraction in `_group_changes_by_slot()`

### REQ-API-006: Slot Metadata

**Status**: ✅ Implemented

Must provide slot metadata:
- `slot`: Raw hex slot value
- `slot_decimal`: Decimal representation (for static slots)
- `is_static_slot`: True if slot < ~100
- `variable_name`: Base variable name
- `variable_path`: Full access path
- `type_label`: Variable type (cleaned)
- `encoding`: Storage encoding type

**Implementation**: `SlotChangeResponse` fields

### REQ-API-007: Program Counter (PC) Tracking

**Status**: ✅ Implemented

Must track program counter for each write:
- Useful for debugging and EVM-level analysis
- Preserved in `StorageChangeResponse.pc`

**Implementation**: PC passed through from SSTORE trace

### REQ-API-008: Value Type Display

**Status**: ✅ Implemented

Must provide cleaned value type for display:
- Strip `t_` prefixes
- Clean up struct notation (e.g., "struct(Reward)2384" -> "Reward")
- Remove "_storage" suffixes

**Implementation**: `_clean_value_type()`, `_strip_type_prefix()`

### REQ-API-009: Dynamic Array Index Display

**Status**: ⚠️ Partially Implemented

Must expose array index for dynamic array entries:
- Currently: Index is embedded in variable_path (e.g., `proposalData[1].field`)
- **Missing**: Separate `array_index` field for explicit access in frontend drill-down

**Implementation Gap**: `array_index` field added to domain model but not passed through in tracer

### REQ-API-010: Element Type ID for Struct Lookup

**Status**: ✅ Implemented

Must provide element type ID for dynamic array struct lookup:
- `element_type_id`: Type ID of array element (for struct definition retrieval)
- Used to look up struct members when array contains structs

**Implementation**: `element_type_id` field in `StorageChange`

### REQ-API-011: Preserve Raw Values and Change Count

**Status**: ✅ Implemented (must remain)

Must return every captured change with raw values even if decoding/matching is partial:
- Do not drop or filter changes because type/struct decoding failed
- `initial_raw` / `final_raw` must always be present
- Slot list length must equal the number of captured slots (after grouping by slot)

### REQ-API-012: Struct and Array Value Shape

**Status**: ⚠️ Partially Implemented

Must represent decoded structs/arrays as structured JSON in the API:
- Structs: object with field names/values, not a single bigint
- Arrays of structs: array of per-element objects, not just length
- Packed struct base slots must include per-field `packed_fields` metadata when applicable

**Implementation Gap**: Ensure tracer and decoder emit structured `decoded`/`display` for known structs and arrays.

---

## Known Limitations & Next Steps

### Currently Missing or Incomplete

#### 1. Dynamic Array Index in API Response
**Priority**: High

The array index is computed in `_try_match_dynamic_array_slot()` but not stored in `StorageChange` or passed to the API response. The `array_index` field was added to the domain model but needs wiring:

```python
# In tracer.py _decode_changes(), around line 1345-1367
# Need to capture: array_index = array_match.get("array_index")
# And pass to StorageChange constructor
```

**Files to modify**:
- `backend/app/services/tracer.py`: Capture and store array_index
- `backend/app/api/routes/transactions.py`: Pass array_index to SlotChangeResponse
- `frontend/src/lib/types.ts`: Add array_index to type
- `frontend/src/components/diff/SlotRow.tsx`: Display array index

#### 2. Nested Struct Resolution
**Priority**: High

When a struct field's type is itself a struct (e.g., `Proposal.results` is `struct Vote`), the nested struct members aren't available in the storage layout from Sourcify/Solc.

**Issue**: The Vote struct type exists (`t_struct(Vote)478_storage`) but has no members in the parsed layout because Solidity's storage layout output only includes members for structs that are directly used as storage variables.

**Potential solutions**:
1. Parse the source code directly to extract nested struct definitions
2. Request full AST from Sourcify to reconstruct nested structs
3. Store struct definitions separately and link them

#### 3. Mapping Key Type Resolution for Non-Address Keys
**Priority**: Medium

Currently address keys are well-supported. uint256 and bytes32 keys work but could be improved:
- Token ID mapping: `mapping(uint256 => TokenInfo)` - display token ID
- Bytes32 keys: Could be string hashes, ENS namehashes, etc.

#### 4. String/Bytes Dynamic Content
**Priority**: Medium

Dynamic `string` and `bytes` types use special encoding:
- Short encoding: length < 32, data + length in same slot
- Long encoding: length >= 32, data at keccak256(slot)

**Currently**: Not decoded (would need multiple slot reads)
**Implementation**: `TypeDecoder.decode_dynamic_bytes()` exists but not integrated

#### 5. Static Array Support
**Priority**: Low

Static arrays (`Type[N]`) are different from dynamic:
- No length slot (length is compile-time known)
- Data starts at base slot directly
- Elements at: baseSlot + index * elementSlots

**Currently**: Partially handled via multi-slot variable detection

#### 6. Enum Name Resolution
**Priority**: Low

Enums are decoded as integers but could show enum member names if we had the enum definition.

#### 7. User-Defined Value Types
**Priority**: Low

Solidity 0.8.8+ supports user-defined value types. These are decoded as their underlying type but could be annotated with the custom type name.

### Performance Considerations

1. **Large Transactions**: Transactions with >1000 SSTORE ops are truncated
2. **Trace Caching**: Currently disabled for testing; should be re-enabled
3. **Layout Parsing**: Solc compilation is slow; layouts should be cached

### Error Handling Gaps

1. **Partial Layout Match**: When layout exists but doesn't cover all slots
2. **Invalid Preimage Data**: Malformed SHA3 preimages should be handled gracefully
3. **Type Decode Failures**: Some edge cases in type decoding may panic

---

## Appendix: Data Flow

```
Transaction Hash + Contract Address
        │
        ▼
┌───────────────────────────────────────────┐
│         Trace Execution                   │
│  - prestateTracer (pre/post state)        │
│  - STORAGE_TRACER (SSTORE + SHA3 ops)     │
└───────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────┐
│         Data Collection                   │
│  - SSTORE: slot, value, pc, index         │
│  - SHA3: preimage → hash mapping          │
│  - Candidates: addresses, uint256s        │
└───────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────┐
│         Slot Matching                     │
│  - Static slots → layout variables        │
│  - Mapping slots → preimage lookup        │
│  - Dynamic arrays → index calculation     │
│  - Struct offsets → member resolution     │
└───────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────┐
│         Type Decoding                     │
│  - With layout: typed decoding            │
│  - Without layout: heuristic decoding     │
│  - Packed slots: multi-value extraction   │
└───────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────┐
│         API Response Building             │
│  - Group by slot                          │
│  - Build params array                     │
│  - Resolve struct definitions             │
│  - Format for display                     │
└───────────────────────────────────────────┘
        │
        ▼
      JSON Response
```

---

## Version History

| Date | Version | Changes |
|------|---------|---------|
| 2025-12-07 | 1.0 | Initial documentation from code analysis |
