# Variable Naming Research

This document tracks issues and findings related to storage variable name resolution in StorageScan.

## Fixed Issues

### 1. Dynamic Array/Mapping Base Slots Not Resolved (Fixed 2024-12-07)

**Problem**: Slot 1 (`rewards` dynamic array) was not resolving to a variable name.

**Root Cause**: `get_variable_for_slot()` in `domain.py` was completely skipping mappings/dynamic arrays:
```python
# OLD CODE (bug):
if var_type.encoding in ("mapping", "dynamic_array"):
    continue  # Skipped ALL slots for these types
```

**Fix**: Changed to return the variable when slot exactly matches the base slot:
```python
# NEW CODE:
if var_type.encoding in ("mapping", "dynamic_array"):
    if var.slot == slot:
        return var  # Return base slot matches
    continue  # Still skip hashed element slots
```

**Location**: `backend/app/models/domain.py:60-82`

### 2. is_static_slot Always False (Fixed 2024-12-07)

**Problem**: The `is_static_slot` field in API responses was always `False`.

**Root Cause**: The field had default `False` but was never computed in `transactions.py`.

**Fix**: Added calculation before SlotChangeResponse creation:
```python
# Calculate is_static_slot - slot < 100 is likely a static slot (not a keccak256 hash)
try:
    slot_int = int(slot, 16) if slot.startswith("0x") else int(slot)
    is_static_slot = slot_int < 100
except ValueError:
    is_static_slot = False
```

**Location**: `backend/app/api/routes/transactions.py:395-406`

### 3. Dynamic String/Bytes Data Slots Not Linked (Fixed 2024-12-08)

**Problem**: When a dynamic string is stored across multiple slots, the data slots were not linked to the variable.

**Example** (tx `0x852eca15...` on contract `0x6e90c85a...`):
- Slot 19 (`name` variable, type `string`): Stores length indicator `0x59` (89)
- Slot `0x66de8ffda797e3de9c05e8fc57b3bf0ec28a930d40b0d285d93c06501cf6a090`: Stores actual string data

The relationship: `keccak256(19) == 0x66de8ffda...` - this is the Solidity dynamic bytes storage pattern.

**Fix**: Added two methods to tracer.py:
1. `_build_dynamic_bytes_index()` - builds index mapping `keccak256(slot)` -> variable for all encoding="bytes" variables
2. `_try_match_dynamic_bytes_slot()` - matches slots to dynamic bytes/string data using the index

**Result**:
- Slot 19: `variable_path: "name"`, `encoding: "bytes"`, `is_static_slot: True`
- Slot `0x66de8...`: `variable_path: "name[data]"`, `encoding: "bytes"`, `is_static_slot: False`
- Slot `0x66de8...+1`: `variable_path: "name[data:1]"` (for longer strings spanning multiple slots)

**Location**: `backend/app/services/tracer.py:1165-1217` (new methods), `1312` (index build), `1426-1436` (matching call)

### 4. Dynamic String/Bytes Decoding Not Working (Fixed 2024-12-08)

**Problem**: Some slots like slot 19 (`name`) show `type_label: "string"` but decoded value was raw bytes instead of descriptive information.

**Root Cause**: The TypeDecoder class didn't have specialized methods for decoding dynamic bytes/string storage.

**Fix**: Added two new decoder methods to `decoder.py`:

1. `decode_dynamic_bytes_slot()` - Decodes the base slot for dynamic bytes/string:
   - Short strings (< 32 bytes): Returns actual string content
   - Long strings: Returns `"<N bytes>"` and display `"N bytes at keccak256(slot)"`

2. `decode_dynamic_bytes_data_slot()` - Decodes data slots for long strings:
   - Decodes UTF-8 content and returns actual string
   - Handles multi-slot strings with `data_offset` parameter

**Integration**: Updated `tracer.py` to use these methods:
- For static bytes-encoding variables (base slots): Uses `decode_dynamic_bytes_slot()`
- For matched dynamic bytes data slots: Uses `decode_dynamic_bytes_data_slot()`

**Result**:
- Slot 19 (base): `final_decoded: "<44 bytes>"`, `final_display: "44 bytes at keccak256(slot)"`
- Slot 0x66de8...: `final_decoded: "Resupply Pair (CurveLend: crvUSD"`, `final_display: "\"Resupply Pair (CurveLend: crvUSD\""`
- Slot 0x66de8...+1: `final_decoded: "/wstUSR) - 1"`, `final_display: "\"/wstUSR) - 1\""`

**Location**: `backend/app/services/decoder.py:275-383` (new methods), `backend/app/services/tracer.py:1357-1370` (static slot decoding), `backend/app/services/tracer.py:1435-1449` (data slot decoding)

---

## Open Issues

(None currently)

---

## Storage Layout Quick Reference

### Encoding Types

| Encoding | Description | Storage Pattern |
|----------|-------------|-----------------|
| `inplace` | Fixed-size value | Stored directly in slot |
| `bytes` | Dynamic bytes/string | Short: inline, Long: length at base, data at keccak256(slot) |
| `dynamic_array` | Dynamic array | Length at base slot, elements at keccak256(slot) |
| `mapping` | Mapping | Nothing at base slot, entries at keccak256(key || slot) |

### Slot Resolution Flow

```
slot -> get_variable_for_slot()
  |-- Static variable? -> Return variable
  |-- Dynamic array base? -> Return variable (shows length)
  |-- Mapping base? -> Return variable (slot unused)
  +-- Unknown -> Try mapping/array element resolution
        |-- Check preimage_lookup (SHA3 trace)
        |-- Try candidate key matching
        +-- Try dynamic array index matching
```

---

## Test Transactions

| Transaction | Contract | Issue |
|-------------|----------|-------|
| `0x852eca15...` | `0x6e90c85a...` | Dynamic string data slots |
| `0xe42fc6ac...` | `0x22222222...` | Packed struct fields |
| `0x5b745c2b...` | `0x11111111...` | Dynamic array struct elements |
