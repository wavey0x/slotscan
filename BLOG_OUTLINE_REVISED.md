# Building a Storage Slot Inspector: Lessons from the EVM Trenches

> A technical blog post about building SlotScan - an EVM storage visualization tool. Covers interesting findings about compiler optimizations, trace strategies, and the hidden complexity of Ethereum storage.

---

## 1. Introduction: Why Storage Inspection Matters

**Hook**: Every smart contract audit, every debugging session, every protocol analysis eventually hits the same wall: "What's actually in storage?"

**The Problem**:
- `private` doesn't mean invisible - it means "not exposed in the ABI"
- Block explorers show transactions and events, but storage is opaque
- Existing tools like `cast storage` work for simple cases but struggle with mappings and complex types

**What We Built**:
- Full storage layout visualization for any verified contract
- Transaction-level storage diff analysis showing what changed and why
- Support for Solidity and Vyper contracts
- Proxy detection and resolution

**Tone**: Set expectations that this is a story about the unexpected complexity hiding beneath the EVM's surface.

---

## 2. The Storage Layout Problem

### Where Do Storage Layouts Come From?

**Key insight**: Storage layouts are a compile-time artifact, not an on-chain concept.

- The EVM only sees 32-byte slots and 32-byte values
- Variable names, types, and offsets exist only in compiler metadata
- Without verified source code, storage is just hex soup

### The Sourcify vs. Etherscan Divide

**Finding**: Not all "verified" contracts are equal.

- **Sourcify**: Stores full metadata including storage layouts (when available)
- **Etherscan**: Stores source code but rarely storage layouts
- **Result**: Many contracts require local recompilation to get layouts

### The Compiler Metadata Minefield

**What can go wrong**:
- Wrong compiler version = different slot assignments
- Missing optimizer settings = different packing
- Wrong contract target in multi-file projects = wrong layout entirely

**Lesson**: Exact reproduction of compiler settings is critical. Even minor differences produce incompatible layouts.

---

## 3. Tracing Transactions: A Multi-Pass Strategy

### Why Not Just Use One Tracer?

**Discovery**: No single trace method gives complete, reliable data.

**The three-pass approach**:
1. `eth_getTransactionReceipt` - candidate addresses for mapping inference
2. `prestateTracer` (diff mode) - ground truth for what changed
3. Custom JS tracer / structLogs - execution order and SHA3 preimages

### The Address Attribution Problem

**Interesting finding**: structLogs often misattributes SSTORE operations.

- DELEGATECALL executes code in the caller's storage context
- Some clients don't report the contract address during execution
- Complex call chains confuse address tracking

**Solution**: Filter by slot hash, not address. Slot hashes are globally unique - if prestateTracer says slot X belongs to contract Y, trust it.

### Node Compatibility: Geth vs. Reth vs. Others

**Finding**: Different nodes have subtle behavioral differences.

| Feature | Geth | Reth | Others |
|---------|------|------|--------|
| Custom JS tracers | Yes | Yes* | Varies |
| structLogs with memory | Yes | Yes (large) | Varies |
| prestateTracer | Yes | Yes | Usually |

*Reth supports custom JS tracers but the VM implementation has subtle differences that can occasionally produce inconsistent results compared to Geth.

**Approach**: Graceful degradation - try JS tracer first, fall back to structLogs if results seem inconsistent, worst case use prestateTracer only.

---

## 4. The SHA3 Preimage Trick

### How Mapping Slots Work

**Quick primer**:
```
slot = keccak256(key || baseSlot)
```
- For `balances[0xABC...]` at slot 5: hash the address + slot 5
- Result is a 32-byte slot that looks random
- Without the key, you can't reverse the hash

### Capturing Preimages from Traces

**Key insight**: The EVM must compute these hashes at runtime - and we can watch.

**What we capture**:
- SHA3/KECCAK256 opcode executions
- The memory region being hashed (the preimage)
- The resulting hash (from the next step's stack)

**Result**: O(1) mapping key resolution instead of brute-force guessing.

### When SHA3 Isn't Called: Compile-Time Optimization

**Surprising discovery**: Sometimes the compiler pre-computes mapping hashes.

**Pattern observed**:
```solidity
address constant REWARD_TOKEN = 0x...;
mapping(address => uint256) rewards;

// In code:
rewards[REWARD_TOKEN] = 100;
```

**What happens**:
- Compiler knows REWARD_TOKEN at compile time
- Computes `keccak256(REWARD_TOKEN || slot)` during compilation
- Embeds the hash directly in bytecode as a constant
- No runtime SHA3 - just `CODECOPY` then `SSTORE`

**Trace pattern**: `CODECOPY → MLOAD → SWAP → SSTORE` with no preceding `SHA3`

**Why it matters**: ~30 gas savings per access, but breaks naive preimage collection.

**Solution**: Parse source code for constant addresses and pre-compute their hashes.

---

## 5. Decoding Complex Storage Patterns

### Packed Storage: Multiple Variables in One Slot

**How it works**:
- Variables smaller than 32 bytes can share a slot
- `address + bool + uint32` fits in one 32-byte slot
- Extraction requires knowing each variable's offset and size

**Challenge**: Must decode the entire slot, not just the value that changed.

### Dynamic Strings and Bytes

**Encoding quirk**: Short vs. long string storage differs completely.

**Short strings (< 32 bytes)**:
- Content + length stored in same slot
- Lowest byte = length * 2

**Long strings (>= 32 bytes)**:
- Base slot stores length * 2 + 1
- Content at `keccak256(baseSlot)`, spanning multiple slots

**Finding**: Must detect the pattern and decode accordingly.

### Nested Mappings and Struct Arrays

**Complexity explosion**:
```solidity
mapping(address => mapping(uint256 => UserData)) userData;
UserData[] public allUsers;
```

**Nested mapping resolution**:
- Outer: `keccak256(outerKey || baseSlot)` = intermediate slot
- Inner: `keccak256(innerKey || intermediateSlot)` = final slot
- Chain preimage lookups to recover both keys

**Dynamic array of structs**:
- Length at base slot
- Data starts at `keccak256(baseSlot)`
- Element N at: `dataStart + N * elementSlots`
- Struct field offset within element: `slot % elementSlots`

---

## 6. Vyper: Similar But Different

### Storage Layout Differences

**Finding**: Vyper and Solidity use different layout strategies.

**Key differences**:
- Different type naming conventions (`HashMap` vs `mapping`)
- Different packing rules
- No storage layout in standard Vyper compilation output

**Solution**: Custom Vyper compilation with experimental storage layout flag.

### String Encoding in Vyper

**Quirk discovered**: Vyper strings are length-prefixed differently.

- Length stored as raw byte count (not Solidity's `length * 2 + 1` encoding)
- Must detect compiler type and decode accordingly

---

## 7. Proxy Patterns: Following the Implementation

### Detection Strategies

**Three patterns detected**:

1. **EIP-1167 Minimal Proxy**: Bytecode contains embedded implementation address
   - Pattern: `363d3d373d3d3d363d73<address>5af43d82803e903d91602b57fd5bf3`
   - No storage read needed - parse bytecode directly

2. **EIP-1967 Transparent/UUPS**: Standard storage slots
   - Implementation: `0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc`
   - Admin: `0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103`

3. **EIP-1822 UUPS**: Older UUPS slot
   - `0xc5f16f0fcc639fa48a6947836d9850f504798523bf8c9a3a87d5876cf622bcf7`

### The Bytecode Cache Trap

**Finding**: Can't cache layouts by bytecode for all proxy types.

- **EIP-1167**: Same proxy bytecode = same implementation → cacheable
- **EIP-1967/1822**: Same proxy bytecode, different implementations → not cacheable

**Solution**: Only use bytecode cache for non-proxies and EIP-1167 minimal proxies.

---

## 8. Constructor Storage: A Special Case

### The Address Attribution Problem (Again)

**Discovery**: Constructor SSTOREs are often misattributed in traces.

**Why**:
- During `CREATE`, the new contract's address is known to the EVM
- But some trace formats don't expose it until after deployment
- SSTOREs during init code may show parent contract's address

**Implication**: Must handle constructor context specially when analyzing contract creation transactions.

---

## 9. Performance Lessons

### Trace Response Sizes

**Problem**: Full traces can be gigabytes for complex transactions.

**Mitigations**:
- Custom JS tracers filter at the node level
- Disable memory capture when preimages aren't needed
- structLogs with memory can exceed 2GB - handle gracefully

### Type Synthesis Caching

**Finding**: Regex-based type parsing was a hotspot.

- Type IDs like `t_uint256` parsed repeatedly per slot
- 100-300 calls per transaction for `get_type()`
- Pre-compiled patterns + result caching = significant speedup

---

## 10. What We Learned

### Key Takeaways

1. **The compiler is the source of truth** - without exact metadata, storage is guesswork
2. **Traces lie (sometimes)** - cross-reference multiple sources
3. **Optimizations create blind spots** - compile-time hash precomputation breaks naive analysis
4. **Storage is more complex than it looks** - packed variables, dynamic encoding, nested structures
5. **Proxies add another layer** - must resolve implementation before analyzing storage

### For Tool Builders

- Support multiple trace methods with graceful fallback
- Capture SHA3 preimages - they're invaluable for mapping analysis
- Parse source code for constants when runtime analysis fails
- Test against both Solidity and Vyper contracts

### For Smart Contract Developers

- `private` doesn't hide data - anyone with an archive node can read it
- Storage layout changes between compiler versions can break upgrade assumptions
- Complex proxy patterns make debugging harder - simpler is often better

---

## 11. Future Directions

**Ideas we'd like to explore**:

- **State evolution analysis**: Track storage changes across blocks, not just transactions
- **Anomaly detection**: Identify suspicious storage patterns (unexpected admin changes, unusual value spikes)
- **Source-level correlation**: Map storage changes back to specific Solidity/Vyper lines via AST
- **ZK-friendly exports**: Generate storage proofs for cross-chain verification

---

## Appendix: The Tool

**SlotScan** is open source and available at [link].

**Features**:
- Paste any verified contract address to see its full storage layout
- Analyze any transaction to see exactly what storage changed
- Support for Solidity and Vyper on Ethereum mainnet
- Proxy detection and automatic implementation resolution

---

*Total estimated reading time: 12-15 minutes*

*Technical level: Intermediate - assumes familiarity with Ethereum basics but explains EVM internals*
