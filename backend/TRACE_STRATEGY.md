# StorageScan Trace Strategy

This document describes how StorageScan traces Ethereum transactions to extract storage changes, including the RPC calls made, their purposes, and how results are merged.

## Overview

StorageScan uses a multi-pass tracing strategy to extract complete, decoded storage changes from transactions. The approach combines:

1. **prestateTracer** - Reliable source of truth for which slots changed
2. **Custom JS/structLogs tracer** - Execution order and mapping key resolution
3. **Transaction receipt** - Candidate address collection

## RPC Calls

### Call 1: eth_getTransactionReceipt

**Purpose:** Collect transaction metadata and candidate addresses for mapping key inference.

```python
receipt = await web3.eth.get_transaction_receipt(tx_hash)
```

**Extracts:**
- `blockNumber` - When the transaction was included
- `from` / `to` - Transaction participants (candidate addresses)
- `logs` - Event logs containing:
  - Log-emitting contract addresses
  - Address-like values in topics (e.g., ERC20 Transfer from/to)
  - Address-like values in log data

**Used for:** Building candidate address list for brute-force mapping key inference.

---

### Call 2: debug_traceTransaction (prestateTracer)

**Purpose:** Get the definitive pre/post storage state diff for all contracts.

```python
tracer_config = {
    "tracer": "prestateTracer",
    "tracerConfig": {"diffMode": True},
}
result = await web3.provider.make_request(
    "debug_traceTransaction", [tx_hash, tracer_config]
)
```

**Returns:** For each contract touched:
```json
{
  "pre": {
    "0xContractAddress": {
      "storage": {
        "0xslot1": "0xoldValue1",
        "0xslot2": "0xoldValue2"
      }
    }
  },
  "post": {
    "0xContractAddress": {
      "storage": {
        "0xslot1": "0xnewValue1",
        "0xslot2": "0xnewValue2"
      }
    }
  }
}
```

**Used for:**
- **Ground truth for slot changes** - Defines exactly which slots changed in which contract
- **Old/new value pairs** - The actual storage values before and after
- **Address validation** - Filters out SSTORE operations that don't belong to our contract

**Why this is reliable:** The prestateTracer is implemented at the node level and accurately tracks which contract owns each storage slot, even during complex cross-contract calls.

---

### Call 3: debug_traceTransaction (SSTORE/SHA3 trace)

**Purpose:** Capture execution order (step) and mapping key preimages.

The system tries two methods:

#### Method A: Custom JS Tracer (Geth-compatible)

```javascript
{
    sstores: [],
    sha3s: [],
    stepCounter: 0,
    pendingSha3: null,
    step: function(log, db) {
        var currentStep = this.stepCounter++;
        var op = log.op.toString();

        // Capture SHA3 result from previous step
        if (this.pendingSha3 !== null) {
            this.pendingSha3.hash = toHex(log.stack.peek(0));
            this.sha3s.push(this.pendingSha3);
            this.pendingSha3 = null;
        }

        if (op === "SSTORE") {
            this.sstores.push({
                address: toHex(log.contract.getAddress()),
                pc: log.getPC(),
                slot: toHex(log.stack.peek(0)),
                value: toHex(log.stack.peek(1)),
                depth: log.getDepth(),
                index: currentStep
            });
        } else if (op === "SHA3" || op === "KECCAK256") {
            // Capture preimage for mapping key resolution
            var offset = log.stack.peek(0).valueOf();
            var size = log.stack.peek(1).valueOf();
            if (size >= 64 && size <= 128) {
                var preimage = toHex(log.memory.slice(offset, offset + size));
                this.pendingSha3 = {
                    address: toHex(log.contract.getAddress()),
                    preimage: preimage,
                    size: size,
                    depth: log.getDepth()
                };
            }
        }
    },
    result: function(ctx, db) {
        return {sstores: this.sstores, sha3s: this.sha3s};
    }
}
```

#### Method B: structLogs Tracer (Reth-compatible fallback)

```python
result = await web3.provider.make_request(
    "debug_traceTransaction",
    [tx_hash, {"enableMemory": True, "enableReturnData": True}]
)
```

Then parses the structLogs array to extract SSTORE and SHA3 operations manually.

**Captures:**
- **SSTORE operations:**
  - `slot` - Storage slot being written
  - `value` - New value being written
  - `pc` - Program counter (bytecode position)
  - `index` - Step number (execution order)
  - `depth` - Call depth
  - `address` - Contract address (when available)

- **SHA3 operations:**
  - `preimage` - Data being hashed (64-128 bytes for mappings)
  - `hash` - Resulting hash (captured from next step's stack)
  - `address` - Contract address

**Used for:**
- **Execution order** - The `index` (step) field shows when each SSTORE happened
- **Mapping key resolution** - SHA3 preimages reveal the actual keys used

---

## Result Merging Strategy

### Step 1: Establish Ground Truth

Extract valid slots from prestateTracer:

```python
valid_slots: set[str] = set()
for addr, state in pre_state.get("pre", {}).items():
    if addr.lower() == contract_address_lower:
        for slot in state.get("storage", {}).keys():
            valid_slots.add(normalize_slot(slot))
for addr, state in pre_state.get("post", {}).items():
    if addr.lower() == contract_address_lower:
        for slot in state.get("storage", {}).keys():
            valid_slots.add(normalize_slot(slot))
```

### Step 2: Filter SSTORE Operations by Slot (not Address)

**Key insight:** Instead of filtering by address (unreliable with structLogs), filter by slot value:

```python
for op in sstore_trace:
    slot = normalize_slot(op.get("slot"))
    # Only include SSTOREs for slots we know changed in our contract
    if slot not in valid_slots:
        continue
    # ... process the SSTORE
```

**Why filter by slot?**
- structLogs doesn't always reliably track which contract is executing
- Address tracking fails during DELEGATECALL and complex call patterns
- The prestateTracer already told us exactly which slots belong to our contract
- A slot hash is globally unique - if it's in our valid set, the SSTORE is ours

### Step 3: Build Changes with Execution Order

Track the current value for each slot and record all changes:

```python
slot_current_value: dict[str, str] = dict(pre_storage)
changes: list = []

for op in sorted(sstore_trace, key=lambda x: x.get("index", 0)):
    slot = normalize_slot(op.get("slot"))
    if slot not in valid_slots:
        continue

    new_value = normalize_value(op.get("value"))
    old_value = slot_current_value.get(slot, ZERO_VALUE)

    if old_value != new_value:
        changes.append((slot, old_value, new_value, op.get("pc"), op.get("index")))

    slot_current_value[slot] = new_value
```

### Step 4: Build Preimage Lookup for Mapping Keys

The SHA3 trace captures the data that was hashed to produce each storage slot:

```python
preimage_lookup: dict[str, str] = {}  # hash -> preimage

for op in sha3_trace:
    hash_value = op.get("hash")
    preimage = op.get("preimage")
    if hash_value and preimage:
        preimage_lookup[normalize_slot(hash_value)] = preimage
```

For a mapping `mapping(address => uint256)` at slot 5, accessing `map[0xABC]`:
- **Preimage:** `0x000000000000000000000000ABC...` (key, 32 bytes) + `0x0000...05` (slot, 32 bytes)
- **Hash:** The actual storage slot where the value is stored

### Step 5: Decode Changes

For each storage change:

1. **Try static slot match** - Check if slot directly maps to a declared variable
2. **Try mapping brute-force** - Compute mapping slots for candidate keys
3. **Try preimage lookup** - Use captured SHA3 preimages for exact key resolution
4. **Try dynamic array match** - Check if slot is within a dynamic array's data region
5. **Try struct offset** - Check if slot is base + N for struct member access
6. **Fallback heuristic** - Decode as address, uint, or hex based on value pattern

---

## Fallback Behavior

### When JS Tracer Fails

If the custom JS tracer returns an error or empty results, fall back to structLogs:

```python
try:
    result = await web3.provider.make_request(
        "debug_traceTransaction", [tx_hash, {"tracer": self.STORAGE_TRACER}]
    )
    if "error" not in result:
        # Use JS tracer results
        return sstores, sha3s
except Exception:
    pass

# Fallback to structLogs
return await self._execute_structlogs_trace(chain_id, tx_hash)
```

### When SSTORE Trace is Incomplete

If the SSTORE trace has fewer slots than the prestateTracer diff, fall back to prestateTracer ordering:

```python
if had_unknown_sstores or sstore_slot_count < prestate_slot_count:
    # Use prestateTracer diff (loses execution order and intermediate writes)
    raw_changes = [
        (slot, old, new, None, i)
        for i, (slot, old, new) in enumerate(prestate_changes)
    ]
    execution_order_available = False
```

### When Trace is Too Large

For very complex transactions, structLogs may exceed response limits:

```python
if "too big" in error_msg.lower() or "exceeded" in error_msg.lower():
    # Retry without memory - lose SHA3 preimages but keep PC values
    result = await web3.provider.make_request(
        "debug_traceTransaction",
        [tx_hash, {"disableMemory": True, "disableStorage": True}]
    )
```

---

## Data Flow Summary

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Transaction Hash                                │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  eth_getReceipt │  │  prestateTracer │  │  SSTORE/SHA3    │
│                 │  │                 │  │  Tracer         │
│  • block number │  │  • valid slots  │  │  • pc/step      │
│  • from/to      │  │  • old values   │  │  • preimages    │
│  • logs         │  │  • new values   │  │  • all writes   │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        MERGE RESULTS                                 │
│                                                                      │
│  1. valid_slots = prestateTracer slots for contract                 │
│  2. filter SSTORE ops where slot ∈ valid_slots                      │
│  3. build preimage_lookup from SHA3 ops                             │
│  4. track intermediate values for repeated writes                   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        DECODE CHANGES                                │
│                                                                      │
│  For each (slot, old_value, new_value, pc, step):                   │
│    • Try static slot → variable lookup                              │
│    • Try mapping key brute-force with candidates                    │
│    • Try preimage lookup for exact key                              │
│    • Try dynamic array element matching                             │
│    • Try struct offset detection                                    │
│    • Fallback to heuristic decoding                                 │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      TransactionDiff                                 │
│                                                                      │
│  {                                                                   │
│    chain_id, contract_address, tx_hash, block_number,               │
│    execution_order_available: bool,                                 │
│    changes: [                                                       │
│      { slot, old_value, new_value, pc, step,                        │
│        variable, variable_path, mapping_key, ... }                  │
│    ]                                                                │
│  }                                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## RPC Call Count Summary

| Scenario | Calls | Description |
|----------|-------|-------------|
| Normal (JS tracer works) | 3 | receipt + prestateTracer + JS tracer |
| JS tracer fails | 3 | receipt + prestateTracer + structLogs |
| structLogs too large | 4 | receipt + prestateTracer + structLogs (fail) + structLogs (no memory) |
| Trace unavailable | 2 | receipt + prestateTracer (returns degraded response) |

---

## Key Design Decisions

### Why filter by slot instead of address?

Address tracking in structLogs is unreliable:
- DELEGATECALL executes code in caller's context
- structLogs doesn't always report contract address
- Complex call chains can confuse address tracking

Slot hashes are globally unique. If prestateTracer says slot X changed in contract Y, any SSTORE to slot X must belong to contract Y.

### Why capture all writes, not just final state?

The prestateTracer only shows first→last value per slot. But transactions can:
- Write to the same slot multiple times
- Overwrite intermediate values

The SSTORE trace captures every write, showing the complete history.

### Why capture SHA3 preimages?

Mapping slots are computed as `keccak256(key || baseSlot)`. Without the preimage:
- We must brute-force guess the key from candidates
- Some keys (large integers, non-standard types) are unrecoverable

With preimages, we can decode any mapping key exactly.
