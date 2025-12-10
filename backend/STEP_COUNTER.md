# EVM Transaction Tracing: SSTORE Step Counter Research

This document analyzes how Ethereum RPC nodes expose transaction execution traces, specifically for capturing the execution order of SSTORE (storage write) operations.

## 1. Overview of Available Tracing Endpoints

Ethereum nodes expose transaction tracing via the `debug_traceTransaction` RPC method. Different node implementations (Geth, Reth, Erigon, etc.) support different tracer configurations:

### 1.1 Built-in Tracers

| Tracer | Description | Step Info | SSTORE Support |
|--------|-------------|-----------|----------------|
| `prestateTracer` | Shows state before/after transaction | No | Yes (first/last values only) |
| `callTracer` | Traces call hierarchy | No | No |
| `structLogs` | Raw EVM execution steps | Yes (implicit) | Yes (all writes) |

### 1.2 Custom JS Tracers (Geth-only)

Geth allows custom JavaScript tracers that execute within the EVM interpreter. These can capture any opcode with precise execution context.

## 2. Tracer Analysis: What Each Provides

### 2.1 prestateTracer (diffMode: true)

**Request:**
```json
{
  "tracer": "prestateTracer",
  "tracerConfig": {"diffMode": true}
}
```

**Provides:**
- `pre`: Initial storage state before transaction
- `post`: Final storage state after transaction

**Limitations:**
- Only shows the **first** and **last** value for each slot
- Loses all intermediate writes (e.g., A→B→C becomes A→C)
- No execution order information
- No PC (program counter) values

**Use Case:** Understanding net storage changes, but not execution flow.

### 2.2 structLogs (Standard EVM Trace)

**Request:**
```json
{
  "enableMemory": true,
  "enableReturnData": true
}
```

**Response format:**
```json
{
  "structLogs": [
    {
      "pc": 1234,
      "op": "SSTORE",
      "depth": 1,
      "stack": ["0x...", "0x..."],
      "memory": ["..."]
    }
  ]
}
```

**Provides:**
- Every EVM opcode executed
- `pc`: Program counter (bytecode position)
- `depth`: Call depth (1 = top-level contract)
- `stack`: EVM stack contents (for SSTORE: slot and value)
- `memory`: EVM memory (for SHA3 preimages)

**Step Information:**
- **Implicit** via array index - each element is one EVM step
- The array position IS the step number

**Limitations:**
- Response can be very large (10MB+ for complex transactions)
- Memory can be disabled to reduce size, but loses SHA3 preimage data
- No explicit "address" field - must track via CALL opcodes
- Reth compatible, but not all fields guaranteed

### 2.3 Custom JS Tracer (Geth-only)

**Current Implementation (STORAGE_TRACER):**
```javascript
{
  sstores: [],
  sha3s: [],
  stepCounter: 0,
  step: function(log, db) {
    var currentStep = this.stepCounter++;
    if (log.op.toString() === "SSTORE") {
      this.sstores.push({
        address: toHex(log.contract.getAddress()),
        pc: log.getPC(),
        slot: toHex(log.stack.peek(0)),
        value: toHex(log.stack.peek(1)),
        depth: log.getDepth(),
        index: currentStep  // This IS the step number
      });
    }
  }
}
```

**Provides:**
- `index`: Global execution step number (increments with every opcode)
- `pc`: Program counter within contract bytecode
- `address`: Contract address executing the SSTORE
- `depth`: Call depth

**Limitations:**
- Only works on Geth and Geth-compatible nodes
- Reth does NOT support custom JS tracers

## 3. Step Number vs Program Counter (PC)

### 3.1 Understanding the Difference

| Concept | Description | Uniqueness |
|---------|-------------|------------|
| **Step** | Sequential execution index (0, 1, 2, 3...) | Globally unique per transaction |
| **PC** | Position in compiled bytecode | Repeats in loops |

**Example:** A loop executing SSTORE 3 times:
```
Step 50: pc=10749, slot=A, value=1
Step 51: pc=10749, slot=B, value=2
Step 52: pc=10749, slot=C, value=3
```

The same PC (10749) appears multiple times because the same code location is executed repeatedly. Only the step number provides true execution order.

### 3.2 Why PC is Wrong for Sorting

Current problem in SlotScan:
```python
# WRONG - slots with same PC can have different execution order
def get_sort_key(x):
    return (x.changes[0].pc, x.changes[0].step)  # PC first = wrong order
```

Correct approach:
```python
# CORRECT - step is the true execution order
def get_sort_key(x):
    return (x.changes[0].step, x.changes[0].pc or 0)  # Step first = correct order
```

## 4. Current Implementation Analysis

### 4.1 Tracer Priority Order

```
1. Try JS Tracer (STORAGE_TRACER)
   ├─ Success → Use sstores[], sha3s[] with real step numbers
   └─ Fail → Fallback to structLogs

2. Try structLogs (Reth-compatible)
   ├─ Parse raw execution steps
   ├─ Extract SSTORE ops with enumerate index as step
   └─ Track contract addresses via CALL opcode monitoring

3. Safety Check: Compare SSTORE count vs prestateTracer diff
   ├─ If SSTORE count < prestateTracer count
   │   └─ Fall back to prestateTracer (loses execution order)
   └─ Set execution_order_available = False
```

### 4.2 The Address Tracking Problem

The structLogs tracer has a critical issue:

```python
# Problem: structLogs doesn't directly provide contract address
# We must track it from CALL opcodes
depth_to_address = {1: tx_to_address}  # Start with known top-level

for log in struct_logs:
    if op in ("CALL", "STATICCALL"):
        addr = stack[-2]  # Address from stack
        depth_to_address[depth + 1] = addr

    if op == "SSTORE":
        current_address = depth_to_address.get(depth, "")  # Often empty!
```

When `depth_to_address` lookup fails (common for depth-1 when not initialized), the SSTORE gets filtered out because its address doesn't match the target contract.

### 4.3 The Fallback Cascade

```
SSTORE tracer produces 2 changes
prestateTracer diff has 27 changes
→ Safety check triggers
→ Falls back to prestateTracer
→ execution_order_available = False
→ Step column hidden in UI
```

## 5. Recommended Approach for Proper SSTORE Sequencing

### 5.1 Option A: Fix structLogs Address Tracking (Recommended)

Instead of filtering out SSTOREs with unknown addresses, include them if:
1. `depth == 1` (top-level contract execution), OR
2. Address matches the target contract

```python
for op in sstore_trace:
    op_addr = op.get("address", "").lower()
    depth = op.get("depth", 1)

    # Include if address matches OR if depth=1 with unknown address
    address_matches = op_addr == contract_address_lower
    is_top_level_unknown = (not op_addr) and depth == 1

    if address_matches or is_top_level_unknown:
        changes.append(...)
```

**Pros:**
- Works with existing single RPC call
- Captures more SSTOREs correctly
- No additional complexity

**Cons:**
- May include SSTOREs from other contracts at depth=1 (rare edge case)

### 5.2 Option B: Use Transaction "to" Address for Initialization

Ensure `depth_to_address[1]` is always initialized from transaction receipt:

```python
tx_to_address = receipt.get("to")  # Already available
if tx_to_address:
    depth_to_address[1] = tx_to_address.lower()
```

This is already implemented but may not be reaching the SSTORE filtering code.

### 5.3 Option C: Request Both Tracers (Extra RPC Call)

Use JS tracer for step numbers, prestateTracer for completeness validation:

```python
# Call 1: JS tracer for step-accurate SSTORE data
js_result = debug_traceTransaction(tx, {"tracer": STORAGE_TRACER})

# Call 2: prestateTracer for validation
prestate_result = debug_traceTransaction(tx, {"tracer": "prestateTracer"})

# Merge: Use JS tracer data but validate against prestateTracer counts
```

**Pros:**
- Most accurate step numbers from JS tracer
- Validation from prestateTracer

**Cons:**
- Extra RPC call per transaction
- JS tracer not available on Reth

### 5.4 Option D: Parse structLogs Completely (Most Reliable)

Parse the full structLogs response and extract SSTOREs with their array indices:

```python
result = debug_traceTransaction(tx, {"enableMemory": True})
struct_logs = result["structLogs"]

for i, log in enumerate(struct_logs):
    if log["op"] == "SSTORE":
        sstores.append({
            "step": i,  # Array index IS the step number
            "pc": log["pc"],
            "slot": log["stack"][-1],
            "value": log["stack"][-2],
            "depth": log["depth"]
        })
```

**Pros:**
- Works on all nodes (Geth, Reth, Erigon)
- Array index is the definitive step number
- Single RPC call

**Cons:**
- Large response size for complex transactions
- Must filter by contract address post-hoc using depth tracking

## 6. Avoiding Extra RPC Calls

### 6.1 Current RPC Calls Per Transaction

| Call | Purpose | Required |
|------|---------|----------|
| `eth_getTransactionReceipt` | Block number, logs, addresses | Yes |
| `debug_traceTransaction` (prestateTracer) | Storage diff | Yes |
| `debug_traceTransaction` (JS/structLogs) | SSTORE sequence | Optional |

### 6.2 Optimization: Combine Tracers

The JS tracer can be extended to also capture prestateTracer-equivalent data:

```javascript
{
  pre: {},
  post: {},
  sstores: [],
  step: function(log, db) {
    // Capture SSTORE as before
  },
  result: function(ctx, db) {
    // Also capture final state
    return {
      sstores: this.sstores,
      pre: {...},  // Would need access to db.GetState()
      post: {...}
    };
  }
}
```

However, the JS tracer context doesn't easily provide full pre/post state access.

### 6.3 Recommended Minimum: Two Calls

```
1. eth_getTransactionReceipt
   └─ Required for block number, addresses from logs

2. debug_traceTransaction (combined approach)
   ├─ Try JS tracer first
   ├─ Fall back to structLogs
   └─ Use prestateTracer as validation only when SSTORE count mismatch
```

## 7. Summary and Recommendations

### 7.1 Immediate Fix

Modify `_build_changes_from_sstore_trace` to include depth-1 SSTOREs even with unknown addresses:

```python
# In tracer.py, lines ~855-863
address_matches = op_addr == contract_address_lower
is_depth_1_unknown = (not op_addr) and depth == 1
if not (address_matches or is_depth_1_unknown):
    continue
```

### 7.2 Long-term Improvements

1. **Better structLogs parsing**: Track addresses more reliably through all CALL variants
2. **Response size handling**: Implement chunked parsing for large structLogs responses
3. **Node compatibility**: Detect node type and use optimal tracer strategy
4. **Caching**: Cache step numbers separately from decoded data

### 7.3 Key Insight

The step number is definitively available from:
- JS tracer: `stepCounter++` in the step function
- structLogs: Array index (`enumerate(structLogs)`)

The problem isn't getting step numbers - it's ensuring the SSTORE filtering doesn't discard valid writes due to address tracking issues.

## 8. References

- [Geth EVM Tracing](https://geth.ethereum.org/docs/developers/evm-tracing)
- [debug_traceTransaction specification](https://ethereum.github.io/execution-apis/api-documentation/)
- [Reth tracing capabilities](https://paradigmxyz.github.io/reth/rpc/rpc.html)
