# SlotScan product requirements

SlotScan is a pre-launch Ethereum storage analysis tool. This document defines
observable behavior and invariants; source code, tests, and
`backend/ARCHITECTURE.md` define the implementation.

## Product surfaces

SlotScan has three canonical user surfaces:

- `/` accepts an Ethereum address or transaction hash.
- `/{chain}/{address}` shows a contract's resolved identity, storage layout,
  and values at a selected block.
- `/{chain}/tx/{hash}` shows transaction-wide persistent storage activity.

There is no contract-scoped transaction route. An optional
`?focus={address}` hint may expand and scroll to one storage owner, but it must
not filter other owners from the transaction.

The public API is rooted at `/api/slotscan`:

- `GET /contracts/{chain_id}/{address}/storage-view`
- `POST /storage/query`
- `GET /tx/{chain_id}/{tx_hash}`

## Contract resolution

- Reject addresses with no code at the selected block.
- Resolve verified source/layout data from Sourcify first and Etherscan when
  needed.
- Detect supported proxy forms and EIP-7702 delegation without changing the
  storage-owner identity.
- Resolve historical transactions against block-specific code and proxy state.
- Cache only current-format metadata. Parser changes invalidate cached layouts
  instead of adding old-payload readers.
- If verified source cannot produce an exact compiler layout, use explicitly
  labelled source inference where supported.
- Provider failures must remain distinguishable from conclusive “no verified
  source” results.

## Layout and decoding

- Preserve compiler-declared slots, byte offsets, type relationships, and
  packed members.
- The contract page initially reads direct scalars, packed scalars, and
  statically located scalar struct leaves.
- Typed contract-page queries support scalar mappings, nested mappings ending
  in scalars, and one top-level fixed- or dynamic-array scalar element.
- Struct traversal, aggregate materialization, and dynamic string/bytes
  payloads are not contract-page query inputs.
- Support Vyper storage allocation across real compiler eras, including
  pre-0.2.13 hashed composites and nonreentrant lock placement.
- Treat compiler and Vyper versions as input semantics, not as SlotScan payload
  generations.
- Never attribute an unmatched slot to a guessed variable.
- Keep raw encoded values available even when decoding fails.
- Preserve integers larger than JavaScript's safe integer range as strings at
  the API boundary.

## Storage reads

- Resolve mutable block selectors to one exact number/hash pair before reading
  code, proxy state, layout, or values.
- Use the single configured RPC client and EIP-1898 block-hash parameters for
  the complete storage-view or typed-query attempt.
- Batch deterministic scalar reads without individual-call fallback.
- Enforce a maximum slot budget before issuing RPC work.
- Never replace a failed storage read with a fabricated zero.
- Mark bounded or incomplete reads explicitly.
- Do not scan unverified storage or eagerly read mappings, arrays, or dynamic
  payloads.
- Derive mapping and array locations on the backend from an exact `layout_id`;
  the browser supplies only raw typed keys or indices.

## Transaction analysis

- Trace once per transaction and derive all contract projections from the same
  raw evidence.
- Retain every observed SSTORE/TSTORE event needed for forensic history,
  including no-op, restored, and reverted writes.
- Keep persistent and transient namespaces separate.
- Preserve execution order, program counter, call-frame outcome, effective code
  address, and storage-owner address when the provider exposes them.
- Use pre/post state to reconcile authoritative transaction-level values.
- Unknown before-values remain unknown; they are never synthesized as zero.
- A transaction response covers every persistent storage owner found in exact
  trace evidence.
- Capability fields truthfully describe missing order, rollback, value,
  address, code-attribution, or reconciliation evidence.
- Event limits may truncate detail but must never change authoritative summary
  values.

## Persistence

PostgreSQL stores:

- current contract metadata/layouts;
- current block-specific contract resolutions;
- one current trace artifact per `(chain_id, tx_hash)`;
- compiler inputs/outputs keyed by deterministic fingerprint.

Trace and layout data are reproducible caches, not user data. During pre-launch
development, incompatible cache changes use destructive invalidation or a
schema reset. Do not add per-row format versions, retained legacy tables, dual
readers/writers, or compatibility migrations.

Raw compiler artifacts retain exact compiler versions and build inputs because
they are evidence needed to reproduce a layout.

## Failure behavior

- Invalid identifiers return HTTP 400.
- Missing transactions/contracts return HTTP 404.
- Upstream RPC failures return HTTP 502.
- Trace unavailability returns a truthful incomplete response rather than an
  invented empty successful trace.
- Missing contract-page layouts return metadata with values unavailable and no
  speculative raw-slot scan.
- Missing transaction layouts keep exact raw writes visible.
- Timeouts and per-contract resolution failures must not discard successfully
  analyzed storage owners.

## Operational invariants

- Request-time compiler installation is disabled by default.
- Compiler processes are concurrency-, time-, input-, CPU-, and memory-bounded.
- RPC calls use the single configured endpoint for each supported chain.
- Readiness requires both database and RPC connectivity.
- The application remains single-chain (Ethereum mainnet) until another chain
  is deliberately configured and tested.

## Verification

Every change must pass the repository checks in `AGENTS.md`. Changes to storage
algebra, compiler behavior, trace semantics, database schema, or API responses
must add focused regression coverage. A schema-baseline change must also prove
that an empty PostgreSQL database can upgrade to Alembic head.
