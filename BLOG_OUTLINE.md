# topics to cover in the blog post (summary outline)

## core features of the tool

This section should summarize very concisely the features of the tool. No need for lots of content.

- visualization of full storage layout for any verified contract
- support for both solidity and vyper variable decoding
- visualization of storage writes within a transaction trace
- ability to see all storage values, including `private` / `internal` variables
- proxy detection + support (eip-1167 minimal proxies, eip-1822 uups, eip-1967 slots)

## research findings on evm + compiler

- using call-depth patterns to reconstruct contract creation trees
- solidity optimization for compile-time-known mapping keys (addresses, immutables, constants)
- when the compiler precomputes `keccak256(key || slot)` and embeds the hash directly into bytecode as a gas optimization method
  - resulting trace patterns:
    - `CODECOPY` → `MLOAD` → `SWAP` → `SSTORE`
    - absence of `SHA3` despite a mapping write
  - gas savings (~30 gas per access) and why solc does this
- implications for tooling: mapping slot derivation must account for pre-hashed static keys

## research findings on traces

- different types of traces used for different purposes / tradeoffs
  - debug trace
  - limitations of opcode-level `structLogs` and why they are not full vm snapshots
- special handling needed to map constructor sstores to their real contract addresses
  - differences between evm behavior and client-specific debug trace formats
  - how sstores inside constructor context are frequently misattributed due to trace-layer omissions
  - why many clients omit the contract address during initcode execution despite the evm knowing it
- custom tracers are small JS script you can send to the node as part of the request via the "tracer" param. It is run in the client to perform arbitrary operations on the EVM steps, and can act as a filter to prevent extremely large responses (e.g. 2GB+)
- varying log object sizes depending on trace settings (e.g., memory vs storage vs stack tracking)
- performance tradeoffs in custom tracers (gas cost, memory pressure, verbosity)
- how to design tracers that reliably capture sstore patterns without excessive output

## findings on evm

- obtaining the storage layout must come from the compiler. thus need verified source code from a trusted source or to compile locally (Sourcify reduces our compilation needs). Vyper contracts all require local compile.
- differences between this tool and `cast storage`
- packed storage decoding (multi-variable slots, bit shifts, type widths)

## gaps, edge cases, and related areas worth covering

- differences between this tool and `cast storage`
- constructor return code vs runtime code and how traces differentiate them

- implications for security reviews: detecting suspicious or unexpected storage modifications

## potential future extensions

- diffing storage between blocks for state evolution analysis
- automated detection of anomalous storage writes (e.g., hacks, rug patterns)
- zk-friendly trace export formats for storage proof generation
- correlation of storage changes to specific source-level AST nodes
