# Variable Naming Research: Reverse Engineering EVM Storage Slots

This document summarizes the research and implementation work done to resolve storage slot addresses back to human-readable variable names in transaction diffs.

## The Problem

When viewing an Ethereum transaction's storage changes, you see raw slot addresses like:
```
0x55bd702e64d2b1d4e26b159c2cf94f7b2831a77c184cfc30eefb12cf49581478
```

Without context, these are meaningless. The goal is to display:
```
rewardData[0x57ab1e...][+4]  (struct member at offset 4)
```

## Progress: 4/8 to 8/8 Named Slots

Starting point: Only 4 of 8 storage slots had variable names assigned.
End result: All 8 slots now have variable names.

## Key Concepts

### 1. EVM Storage Layout

Solidity stores variables in 256-bit (32-byte) storage slots. Simple variables get assigned sequential slots starting from 0:

```solidity
contract Example {
    uint256 public a;     // slot 0
    uint256 public b;     // slot 1
    address public owner; // slot 2
}
```

### 2. Mapping Storage Slots

For mappings, the slot is computed using keccak256:

```
slot = keccak256(key || base_slot)
```

Where:
- `key` = the mapping key, left-padded to 32 bytes
- `base_slot` = the slot number where the mapping is declared, left-padded to 32 bytes
- `||` = concatenation

Example:
```solidity
mapping(address => uint256) public balances;  // declared at slot 3
```

Accessing `balances[0xABC...]`:
```
slot = keccak256(
    0x000000000000000000000000ABC...  // key (32 bytes)
    0x0000000000000000000000000000000000000000000000000000000000000003  // base slot
)
```

### 3. Nested Mappings

For `mapping(address => mapping(address => uint256))`:
```
inner_slot = keccak256(outer_key || base_slot)
final_slot = keccak256(inner_key || inner_slot)
```

### 4. Struct Member Offsets

For mappings to structs:
```solidity
struct AccountData {
    uint256 balance;        // offset 0
    uint256 lastUpdate;     // offset 1
    uint256 rewards;        // offset 2
    uint256 rewardDebt;     // offset 3
    uint128 lockStart;      // offset 4
    uint128 lockEnd;        // offset 5
}
mapping(address => AccountData) public accountData;
```

The base slot is `keccak256(address || slot)`, then:
- `accountData[addr].balance` = base + 0
- `accountData[addr].lastUpdate` = base + 1
- `accountData[addr].lockStart` = base + 4
- etc.

## Solution Architecture

### Two-Phase Approach

1. **Storage Layout from Etherscan**: Get the contract's storage layout via verified source code
2. **SHA3 Preimage Capture**: Trace transaction execution to capture keccak256 inputs/outputs

### Types of Tracing

#### Option A: Custom JavaScript Tracer (Geth)
Geth supports custom JS tracers that can be injected:

```javascript
{
    sha3s: [],
    pendingSha3: null,
    step: function(log, db) {
        if (this.pendingSha3 !== null) {
            this.pendingSha3.hash = toHex(log.stack.peek(0));
            this.sha3s.push(this.pendingSha3);
            this.pendingSha3 = null;
        }
        if (log.op.toString() === "SHA3" || log.op.toString() === "KECCAK256") {
            var offset = log.stack.peek(0).valueOf();
            var size = log.stack.peek(1).valueOf();
            if (size >= 64 && size <= 128) {
                this.pendingSha3 = {
                    preimage: toHex(log.memory.slice(offset, offset + size)),
                    size: size,
                    depth: log.getDepth()
                };
            }
        }
    },
    // ...
}
```

**Pros**: Efficient, captures only what you need
**Cons**: Not supported by all clients (Reth doesn't support custom JS tracers)

#### Option B: structLogs Trace (Reth-compatible)

Use the built-in debug tracer with memory enabled:

```python
result = await w3.provider.make_request(
    "debug_traceTransaction",
    [tx_hash, {"enableMemory": True, "enableReturnData": True}]
)
struct_logs = result["result"]["structLogs"]
```

Then parse the SHA3/KECCAK256 opcodes manually:

```python
for i, log in enumerate(struct_logs):
    op = log.get("op", "")

    # Capture result from NEXT step (hash is pushed to stack)
    if pending_sha3 is not None:
        if stack:
            pending_sha3["hash"] = normalize_slot(stack[-1])
            sha3s.append(pending_sha3)
        pending_sha3 = None

    if op in ("SHA3", "KECCAK256"):
        stack = log.get("stack", [])
        memory = log.get("memory", [])

        # Stack[-1] = offset (top), stack[-2] = size
        offset = int(stack[-1], 16)
        size = int(stack[-2], 16)

        # Only capture mapping-sized preimages (64-128 bytes)
        if 64 <= size <= 128:
            preimage = extract_memory_slice(memory, offset, size)
            pending_sha3 = {"preimage": preimage, "size": size}
```

**Pros**: Works with any EVM client (Geth, Reth, Erigon, etc.)
**Cons**: More data transfer (full execution trace), requires parsing

## Preimage Parsing

A 64-byte preimage for a simple mapping:
```
[32 bytes: key][32 bytes: base_slot]
```

A 128-byte preimage for a nested mapping of structs:
```
[32 bytes: outer_key][32 bytes: first_level_slot][32 bytes: inner_key][32 bytes: second_level_slot]
```

Parsing code:
```python
def parse_preimage(preimage: str, size: int):
    preimage_clean = preimage[2:] if preimage.startswith("0x") else preimage

    if size == 64:
        key = "0x" + preimage_clean[:64]
        base_slot = "0x" + preimage_clean[64:128]
        return {"key": key, "base_slot": int(base_slot, 16)}

    elif size == 128:
        outer_key = "0x" + preimage_clean[:64]
        mid_slot = "0x" + preimage_clean[64:128]
        inner_key = "0x" + preimage_clean[128:192]
        base_slot = "0x" + preimage_clean[192:256]
        return {
            "outer_key": outer_key,
            "inner_key": inner_key,
            "base_slot": int(base_slot, 16)
        }
```

## Key Fixes Made

### Fix 1: Use `get_mapping_by_base_slot()` instead of `get_variable_for_slot()`

The original code used `get_variable_for_slot()` which explicitly skips mappings:

```python
# domain.py - get_variable_for_slot()
def get_variable_for_slot(self, slot: int) -> Optional[LayoutVariable]:
    for var in self.variables:
        if var.storage_type == "mapping":
            continue  # PROBLEM: Skips all mappings!
        # ...
```

For SHA3 preimage resolution, we need to find mappings by their base slot:

```python
# domain.py - get_mapping_by_base_slot()
def get_mapping_by_base_slot(self, slot: int) -> Optional[LayoutVariable]:
    for var in self.variables:
        if var.slot == slot and var.storage_type == "mapping":
            return var
    return None
```

**Fix applied at tracer.py:633**:
```python
# Before (wrong)
variable = layout.get_variable_for_slot(base_slot)

# After (correct)
variable = layout.get_mapping_by_base_slot(base_slot)
```

### Fix 2: Handle Struct Member Offsets from Preimage Lookup

The original code only checked if the exact slot was in the preimage lookup. For struct members, the slot is `base + offset`, but only the base slot is in the preimage lookup.

**Problem**: `0x55bd702e64d2b1d4...8` (the slot) was not in preimage lookup, but `0x55bd702e64d2b1d4...4` (base - 4) was.

**Fix applied at tracer.py:1245-1272**:
```python
# Handle struct offsets: if slot is not in preimage_lookup but slot-N is,
# this is a struct member access (e.g., accountData[addr].field)
if not variable and slot_hex not in preimage_lookup:
    for struct_offset in range(1, 10):  # Check offsets 1-9 for struct members
        base_slot_int = slot_int - struct_offset
        base_slot_hex = self._normalize_slot(hex(base_slot_int))
        if base_slot_hex in preimage_lookup:
            base_preimage = preimage_lookup[base_slot_hex]
            base_match = self._try_match_slot_from_preimage(
                base_slot_hex, base_preimage, layout, preimage_lookup
            )
            if base_match:
                base_var = base_match.get("variable")
                if base_var:
                    variable = base_var
                    # Update path to indicate struct member offset
                    base_path = base_match.get("path", "")
                    variable_path = f"{base_path}[+{struct_offset}]"
                    break
```

## Test Case: GovStaker Stake Transaction

Transaction: `0xe42fc6acb03f43c32a920c6521b2594a0a3c66252929364f1caaff6f81e40fbd`
Contract: GovStaker at `0x22222222E9fE38F6f1FC8C61b25228adB4D8B953`

### Before Fixes (4/8 named):
```
0x55bd702e64d2b1d4... var=None
0x55bd702e64d2b1d4... var=None
0x6f45a6348dada5a1... var=None
0x707063001b5a0697... var=None
0xb6cf7bd187478bf9... var=accountWeightAt
0x0000000000000000... var=totalPending
0x3627122f4e48d6c1... var=accountData
0x0000000000000000... var=_totalSupply
```

### After Fixes (8/8 named):
```
0x55bd702e64d2b1d4... var=rewardData      path=rewardData[0x57ab1e...][+5]
0x55bd702e64d2b1d4... var=rewardData      path=rewardData[0x57ab1e...][+4]
0x6f45a6348dada5a1... var=rewards         path=rewards[0xc69adc...][0x57ab1e...]
0x707063001b5a0697... var=userRewardPer.. path=userRewardPerTokenPaid[0xc69adc...][0x57ab1e...]
0xb6cf7bd187478bf9... var=accountWeightAt path=accountWeightAt[0xC69aD...][38]
0x0000000000000000... var=totalPending    path=totalPending
0x3627122f4e48d6c1... var=accountData     path=accountData[0xC69aD...]
0x0000000000000000... var=_totalSupply    path=_totalSupply
```

## Memory Extraction from structLogs

EVM memory in structLogs is provided as an array of 32-byte hex strings:

```python
def extract_memory_slice(memory: list[str], offset: int, size: int) -> str:
    if not memory:
        return None

    # Concatenate all memory into one continuous hex string
    full_memory = "".join(memory)

    # Each char is a nibble (4 bits), so multiply offsets by 2
    start_nibble = offset * 2
    end_nibble = (offset + size) * 2

    # Pad if needed
    if end_nibble > len(full_memory):
        full_memory = full_memory + "0" * (end_nibble - len(full_memory))

    slice_hex = full_memory[start_nibble:end_nibble]
    return "0x" + slice_hex if slice_hex else None
```

## Stack Format Notes

In Reth's structLogs, the stack is returned as an array where:
- `stack[-1]` = top of stack (most recently pushed)
- `stack[-2]` = second from top

For SHA3/KECCAK256 opcode:
- `stack[-1]` = memory offset
- `stack[-2]` = size

After the opcode executes (in the NEXT step):
- `stack[-1]` = the resulting hash

## Phase 2: Decoding Packed Storage and Struct Field Names

After achieving 8/8 variable name resolution, the next challenge was decoding the actual values, particularly for:
1. **Tightly packed storage slots** - multiple variables sharing one 32-byte slot
2. **Struct field names** - showing `.lockStart` instead of `[+4]`

### The Problem

**Packed Storage Example (slot 9):**
```
Raw: 0x00000000000000000000000000000000002600000000117706bede428580717d
Current: decoded as uint112 = 323595887420...
Desired: { totalPending: 323595887420..., weekStart: 38 }
```

**Struct Member Access:**
```
Current:  variable_path = "rewardData[0x57ab1e...][+4]"
Desired:  variable_path = "rewardData[0x57ab1e...].lockStart"
```

### EVM Packed Storage Layout

Solidity packs multiple small values into a single 32-byte slot when possible:

```solidity
contract Example {
    uint112 public totalPending;       // slot 9, offset 0, 14 bytes
    uint16 public totalLastUpdateEpoch; // slot 9, offset 14, 2 bytes
}
```

Storage is **right-aligned**, meaning smaller values sit at the rightmost bytes:
```
Slot 9: [... unused (16 bytes) ...][totalLastUpdateEpoch (2)][totalPending (14)]
        <---- higher bytes ------>                           <--- lower bytes -->
```

To extract a packed value:
```python
# Storage is right-aligned, offset specifies position from right
size = type_info.num_bytes  # e.g., 14 for uint112
start = 32 - offset - size   # position from left
end = 32 - offset
relevant_bytes = raw_value[start:end]
```

### Solution: Packed Field Decoding

**Step 1: Get All Variables in a Slot**

Added method to `domain.py`:
```python
def get_all_variables_in_slot(self, slot: int) -> list[StorageVariable]:
    """Get ALL variables that share this slot (for packed storage)."""
    result = []
    for var in self.variables:
        if var.slot == slot:
            result.append(var)
    return sorted(result, key=lambda v: v.offset)
```

**Step 2: Decode All Packed Fields**

Added method to `decoder.py`:
```python
def decode_packed_slot(
    self,
    raw_value: bytes,
    variables: list[StorageVariable],
    types: dict[str, StorageType],
) -> dict[str, DecodedValue]:
    """Decode all packed variables from a single slot."""
    result = {}
    for var in variables:
        type_info = types.get(var.type_id)
        if type_info:
            # decode() uses var's offset for byte extraction
            decoded = self.decode(raw_value, type_info, offset=var.offset)
            result[var.name] = decoded
    return result
```

**Step 3: API Response Structure**

Added `PackedFieldResponse` to API:
```python
class PackedFieldResponse(BaseModel):
    name: str
    type_label: str
    offset: int
    size: int
    initial_decoded: Optional[Any] = None
    initial_display: Optional[str] = None
    final_decoded: Optional[Any] = None
    final_display: Optional[str] = None
```

### Solution: Struct Field Name Resolution

Instead of showing `[+4]`, resolve the actual field name from the storage layout.

**Added method to `tracer.py`:**
```python
def _resolve_struct_field(
    self,
    base_variable: StorageVariable,
    struct_offset: int,
    layout: StorageLayout,
) -> tuple[str | None, StorageType | None]:
    """Resolve struct field name from offset."""
    var_type = layout.get_type(base_variable.type_id)
    if not var_type:
        return None, None

    # For mappings to structs, get the value type
    if var_type.encoding == "mapping" and var_type.value_type:
        value_type = layout.get_type(var_type.value_type)
        if value_type and value_type.members:
            for member in value_type.members:
                # member.slot is the offset within the struct
                if member.slot == struct_offset:
                    member_type = layout.get_type(member.type_id)
                    return member.name, member_type
    return None, None
```

**Updated struct offset detection:**
```python
# Instead of: variable_path = f"{base_path}[+{struct_offset}]"
field_name, field_type = self._resolve_struct_field(variable, struct_offset, layout)
if field_name:
    variable_path = f"{base_path}.{field_name}"
else:
    variable_path = f"{base_path}[+{struct_offset}]"  # Fallback
```

### Test Results

**Before (packed slot showing single value):**
```
totalPending: 82,475,878,823,742,496,862,589
```

**After (both packed values decoded):**
```
totalPending: uint112 (82,475,878,823,742,496,862,589 -> 82,875,878,823,742,496,862,589)
totalLastUpdateEpoch: uint16 (38 -> 38)
```

**Before (struct offset):**
```
path=rewardData[0x57ab1e...][+4]
```

**After (struct field name):**
```
path=rewardData[0x57ab1e...].rewardPerTokenStored
```

### Frontend Display

For packed fields, the UI now shows:
```
totalPending: 82,475... | totalLastUpdateEpoch: 38
```

Implementation in `SlotRow.tsx`:
```typescript
const formatPackedFields = (
  fields: PackedFieldResponse[],
  mode: 'initial' | 'final'
): string => {
  return fields
    .map((f) => {
      const display = mode === 'initial' ? f.initial_display : f.final_display;
      const decoded = mode === 'initial' ? f.initial_decoded : f.final_decoded;
      const value = display ?? formatDecodedValue(decoded);
      return `${f.name}: ${value}`;
    })
    .join(' | ');
};
```

### Files Modified (Phase 2)

| File | Changes |
|------|---------|
| `backend/app/models/domain.py` | Added `get_all_variables_in_slot()` |
| `backend/app/services/decoder.py` | Added `decode_packed_slot()` |
| `backend/app/services/tracer.py` | Added `_resolve_struct_field()`, updated struct offset handling |
| `backend/app/models/api.py` | Added `PackedFieldResponse`, updated `SlotChangeResponse` |
| `backend/app/api/routes/transactions.py` | Updated `_group_changes_by_slot()` |
| `frontend/src/lib/types.ts` | Added `PackedFieldResponse` interface |
| `frontend/src/components/diff/SlotRow.tsx` | Added packed field display |

### Key Learnings (Phase 2)

1. **Storage is right-aligned**: To extract bytes, calculate `start = 32 - offset - size`
2. **Struct members use `slot` as offset**: In `StorageType.members`, each member's `slot` field is actually its offset within the struct
3. **Packed detection is slot-based**: Check `get_all_variables_in_slot(slot_int)` and if `len > 1`, decode all

## Future Improvements

1. ~~**Struct field names**: Instead of `[+4]`, show the actual struct field name from the storage layout~~ **DONE**
2. ~~**Packed storage**: Decode all values when multiple variables share a slot~~ **DONE**
3. **Dynamic array slots**: Handle `keccak256(slot) + index` for dynamic arrays
4. **String/bytes storage**: Handle the complex storage layout for strings > 31 bytes
5. **Proxy contracts**: Resolve storage layout through delegate calls

## Files Modified

- `backend/app/services/tracer.py` - SHA3 preimage capture, struct offset detection, struct field resolution
- `backend/app/models/domain.py` - `get_mapping_by_base_slot()`, `get_all_variables_in_slot()`
- `backend/app/services/decoder.py` - `decode_packed_slot()`
- `backend/app/models/api.py` - `PackedFieldResponse`
- `backend/app/api/routes/transactions.py` - Packed field detection in `_group_changes_by_slot()`
- `frontend/src/lib/types.ts` - `PackedFieldResponse` interface
- `frontend/src/components/diff/SlotRow.tsx` - Packed field display formatting

## Phase 3: Struct Definition Display in UI

After resolving struct field names, the next improvement was showing the full struct shape in the UI, highlighting which member was modified.

### The Problem

When viewing a storage change like `rewardData[0x57ab1e...].lockStart`, users couldn't see the full struct shape to understand context - what other fields exist, their types, and their positions.

### Solution: Struct Definition API Response

Added `StructDefinitionResponse` to the API that includes all struct members:

```python
class StructMemberResponse(BaseModel):
    name: str              # Field name (e.g., "lockStart")
    type_label: str        # Type (e.g., "uint128")
    slot_offset: int       # Offset within struct (e.g., 4)
    byte_offset: int       # Byte offset within the slot
    size: int              # Size in bytes

class StructDefinitionResponse(BaseModel):
    name: str                           # Struct name (e.g., "RewardData")
    members: list[StructMemberResponse] # All struct members
```

**Backend implementation** (`transactions.py`):
```python
def _get_struct_definition(
    variable: StorageVariable,
    layout: StorageLayout,
) -> Optional[StructDefinitionResponse]:
    """Get the struct definition for a mapping that points to a struct."""
    var_type = layout.get_type(variable.type_id)
    if not var_type:
        return None

    # Traverse through nested mappings to find the struct type
    value_type_id = var_type.value_type
    while value_type_id:
        value_type = layout.get_type(value_type_id)
        if not value_type:
            break

        # If this is a struct with members, return the definition
        if value_type.members:
            struct_name = value_type.label
            # Clean up name: "struct GovStaker.RewardData" -> "RewardData"
            if "." in struct_name:
                struct_name = struct_name.rsplit(".", 1)[1]
            if struct_name.startswith("struct "):
                struct_name = struct_name[7:]

            members = []
            for member in value_type.members:
                member_type = layout.get_type(member.type_id)
                members.append(StructMemberResponse(
                    name=member.name,
                    type_label=member_type.label if member_type else member.type_id,
                    slot_offset=member.slot,
                    byte_offset=member.offset,
                    size=member.size,
                ))
            return StructDefinitionResponse(name=struct_name, members=members)

        # Check nested mappings
        if value_type.encoding == "mapping" and value_type.value_type:
            value_type_id = value_type.value_type
        else:
            break

    return None
```

### Frontend Display

The UI tooltip now shows the full struct definition with the modified field highlighted:

```typescript
const renderStructDefinition = (
  structDef: StructDefinitionResponse,
  modifiedField: string | null
) => (
  <div className="space-y-1">
    <div className="font-medium text-gray-200">struct {structDef.name}</div>
    <div className="pl-2 space-y-0.5 font-mono text-[10px]">
      {structDef.members.map((member, idx) => {
        const isModified = member.name === modifiedField;
        return (
          <div key={idx} className={isModified ? 'text-yellow-300' : 'text-gray-400'}>
            <span className="text-gray-500">[{member.slot_offset}]</span>
            <span>{member.type_label}</span>
            <span>{member.name}</span>
            {isModified && <span className="text-yellow-400 ml-1">*</span>}
          </div>
        );
      })}
    </div>
  </div>
);
```

### Example Output

When hovering over `rewardData[0x57ab1e...].lockStart`:

```
struct RewardData
  [0] uint256 integral
  [1] uint256 rewardRate
  [2] uint256 lastUpdate
  [3] uint256 balance
  [4] uint128 lockStart  *   <- highlighted (modified)
  [5] uint128 lockEnd
```

### Files Modified (Phase 3)

| File | Changes |
|------|---------|
| `backend/app/models/api.py` | Added `StructMemberResponse`, `StructDefinitionResponse` |
| `backend/app/api/routes/transactions.py` | Added `_get_struct_definition()` helper |
| `frontend/src/lib/types.ts` | Added TypeScript interfaces |
| `frontend/src/components/diff/SlotRow.tsx` | Added struct definition tooltip display |

## Key Learnings

1. **Mapping slots are computed, not assigned**: You can't know a mapping slot without knowing the key
2. **Preimage capture is essential**: Without seeing what data was hashed, reverse-engineering is impossible
3. **Struct offsets are arithmetic**: Once you have the base hash, struct members are just `base + N`
4. **Different clients, different APIs**: Geth supports custom JS tracers, Reth needs structLogs parsing
5. **Storage is right-aligned**: Packed values sit at the right side of a 32-byte slot
6. **Struct field info lives in type definitions**: `StorageType.members` contains field names and their offsets
7. **Nested mappings require traversal**: For `mapping(addr => mapping(addr => Struct))`, traverse `value_type` chain to find the struct
