# Backend Decoding & Storage Mapping – Findings (Do Not Implement Yet)

## Summary
- Variable names and decoded values are often missing because the current pipeline rarely produces a usable `StorageLayout` and cannot map hashed/mapping slots to variables. Even when a layout exists, mapping slots are not matched, so UI shows raw hex.
- Layout compilation is brittle: we ignore the full compiler metadata, recompile with partial settings, and don’t consume Sourcify’s already-normalized layouts. Wrong compiler settings or contract target → missing/invalid layout.
- Mapping resolution logic is insufficient: `get_variable_by_slot` only matches exact base slots, so hashed mapping slots never map to variables; transaction diffs therefore show raw slots/hex.
- Caching was disabled for testing, so fresh data is fetched, but the root issues are in layout acquisition and slot→variable mapping.

## Detailed Issues

### Layout acquisition/parsing
1) **Sourcify layouts ignored**: Sourcify metadata already contains `storageLayout`, but we always recompile and don’t parse the provided layout. Any mismatch in settings fails silently, leaving `storage_layout=None`.
2) **Partial compiler settings**: For Etherscan, we only capture optimizer/runs; we skip `evmVersion`, `metadata` settings, `libraries`, and the exact `sources` JSON structure. This can produce a different layout than on-chain.
3) **Contract target ambiguity**: LayoutParser uses `contract_name` from metadata but doesn’t guarantee the fully qualified name; multi-file projects with multiple contracts may return the wrong contract or none.
4) **No ABI use for decoding**: We don’t use ABI to render values (e.g., units/decimals), so even when layout exists, display is raw ints/hex.
5) **No layout persisted on resolve**: ContractResolver never stores a layout; API routes re-parse each time (when not cached). If parsing fails, `storage_layout` stays None and decoding is hex-only.

### Slot-to-variable mapping
1) **Mapping slots never matched**: `StorageLayout.get_variable_by_slot` only matches exact `slot` numbers; hashed mapping slots (keccak(key, base_slot)) will never map, so TransactionTracer returns `variable=None` and UI shows raw slot/hex.
2) **No mapping key discovery used for diffs**: We don’t store or reuse mapping keys; even when a tx touches a mapping slot, we don’t reverse it to a variable unless we enrich the mapping lookup with base slot info.
3) **Packed/offset logic naive**: `get_variable_by_slot` ignores packed offsets for structs/packed vars; for many small fields in one slot, only the first may match.

### Storage reading & decoding
1) **Verified reads only cover static slots**: We only read mapping entries if `mapping_keys` are provided. No automatic key discovery, so mappings are often absent and display as raw/empty.
2) **Heuristic decoding priority**: Previously we guessed “address” before small ints, leading to address-like displays for counters. Fixed ordering helps but doesn’t solve missing layout.
3) **No unit/context formatting**: Numbers lack context (decimals, roles), making them hard to read even when decoded.

### Persistence/caching
1) **No layout persisted in DB**: Layouts parsed in API routes aren’t saved (fixed recently in routes), so earlier runs had no layout stored.
2) **Cache disabled for testing**: Fresh reads are fine, but the root cause is missing/invalid layouts and mapping resolution.

## Hypotheses on current behavior
- The UI shows raw hex + hashed slots because:
  - Layout is None (failed/absent), so tracer can’t map slots → raw slot hash, raw hex.
  - Mapping slots can’t be matched by `get_variable_by_slot`, even with a layout.
  - Mapping entries weren’t read/decoded because no mapping_keys were supplied or discovered.

## Recommendations (design, not implemented)
1) **Use Sourcify layout directly**: If metadata contains `storageLayout`, parse that without recompiling. Keep the solc fallback only when layout missing.
2) **Compile with full metadata**: For Etherscan, reconstruct the exact standard JSON (sources + full `settings`, including `evmVersion`, `libraries`, `metadata`, `remappings`). Use fully qualified contract names.
3) **Persist layouts**: After parsing, store `storage_layout` in `contracts` so subsequent requests decode immediately.
4) **Mapping-aware lookup**: Build a map of `base_slot -> variable` and allow `get_variable_by_hashed_slot(slot_hex)` to return the mapping variable (and include base slot) for tracer/reader.
5) **Key discovery for diffs**: When tracing, record mapping base slot and key (if inferrable) so we can render `balances[0x…]` instead of raw slot hash.
6) **ABI/metadata formatting**: Use ABI to add type context (decimals, units) for common ERC20/721/4626 patterns; show decoded + raw in UI.
7) **Structured errors**: Surface when layout is missing/failed to parse so UI can show “layout unavailable” instead of raw hex.

## Progress
- Added richer compiler settings parsing (Etherscan: include optimizer/evmVersion/settings when present; Sourcify: preserve metadata settings) and pass metadata settings to LayoutParser.
- Persist parsed layouts back into the contracts table from API routes (contracts/storage/transactions) so future requests can decode immediately.
- Heuristic decode now prefers small integers before address-like patterns.
- Mapping inference in tracer uses base-slot context and candidate addresses to tag hashed slots.

## Current Problem: Variable names still missing (e.g., ERC20 GovToken)
- UI still shows raw hashed slots/hex for simple ERC20 changes.
- Likely causes:
  1) Layout missing at tracer time: compilation may fail or target the wrong contract (multi-contract metadata). Disabling Sourcify layouts removes a reliable layout source.
  2) Contract target ambiguity: without fully qualified names, compiled layout may be for the wrong contract.
  3) Mapping slots: balances/allowances are hashed; if layout is absent or mapping base slots aren’t indexed, we fall back to raw slots.
  4) Cached contracts without layouts: resolver returns cached DB rows when `is_verified` is true, even if `storage_layout` is null. Existing rows (saved before layout support) short-circuit resolution, so layout stays missing for tracer/UI.

## Revised Plan (to restore names)
- Re-enable Sourcify `storageLayout` as primary: when available, parse and use it directly; persist it. Compile with solc only when layout is missing.
- Resolve contract target explicitly: use `compilationTarget` (fully qualified name) when compiling; if missing, fail loudly.
- Ensure layout availability in tracer: on tx requests, if layout absent, try Sourcify layout, then compile; if still absent, return `layout_available=false` so UI can indicate “layout unavailable.”
- Mapping resolution: keep base-slot index and candidate-address matching; with a valid layout, render `mappingName[key]` or `mappingName[?]` instead of raw slots.
- Surface status/errors: API should tell the UI when layout is unavailable (versus showing hex silently).

## Plan for mapping source → storage (variable names) and tool choice

### Goal
Get consistent `StorageLayout` with variable names/types so we can map slot hashes to variables and decode values. Minimize custom parsing by using proven tooling.

### Tooling Options (pros/cons)
1) **Sourcify storageLayout (preferred when available)**
   - Pros: Already compiled with exact metadata; includes `storageLayout` and sources; zero local compilation.
   - Cons: Missing for some contracts; needs robust parsing of the returned JSON (multiple files, partial matches).

2) **Solc standard JSON (current approach, improved)**
   - Pros: Works everywhere with exact metadata; no extra dependencies.
   - Cons: Sensitive to incomplete metadata; contract target disambiguation needed.

3) **Foundry/Forge**
   - Capabilities: `forge build --force` with a standard JSON input and `--ast` can emit `storageLayout` via solc; Foundry mainly wraps solc. Forge also offers `forge inspect <contract>:storage` when a project is configured.
   - Pros: Good developer ergonomics, caching, version management; `forge inspect` yields storage layout with variable names/types.
   - Cons: Assumes a Foundry project structure; to use it ad-hoc we still must generate a Foundry project with sources + remappings + exact compiler version/settings. This is similar complexity to driving solc directly, and adds a dependency (foundryup, forge binaries).
   - Conclusion: Forge can produce storage layouts, but for ad-hoc verified contracts it doesn’t reduce integration work versus direct solc; it mainly wraps solc using the same metadata we already have to reconstruct.

### Recommended approach (revised)
- Primary: Use Sourcify layouts when available (already compiled with exact metadata); parse and persist `storageLayout` directly. Fall back to solc compilation only when layout is missing.
- When compiling with solc, reconstruct the exact standard JSON from metadata (sources + full `settings` including optimizer, runs, evmVersion, remappings, libraries, metadata) and target the fully qualified contract name from `compilationTarget`.
- Why not Forge for verified contracts: Forge ultimately wraps solc; to decode arbitrary verified contracts we would still need to generate a Foundry project with exact sources/remappings/settings. That adds a binary dependency and setup cost without reducing complexity versus invoking solc directly with the provided metadata.

### Mapping variable names to slots (hashes)
- Build a mapping index: `base_slot -> StorageVariable` for mappings; `slot -> StorageVariable` for static slots; include packed offsets.
- For transaction diffs: when encountering a hashed slot, try to reverse-map using `slot.startswith(keccak(base_slot,...))` by computing keccak(key, base_slot) for known key types if the layout provides `key_type`. If key unknown, still attach the base slot and variable name; display “mapping[?]” with base slot hint.
- For storage reads: if mapping keys are provided or discovered (from traces), compute slots and map to variables; otherwise show mapping variable name with “unknown key” and raw slot.

### Action items before implementation
- Parse and use Sourcify `storageLayout` directly when available.
- Improve solc compilation input to match metadata exactly (fully qualified contract target, full settings).
- Add base-slot mapping index and hashed-slot lookup for mappings; surface variable names even when key is unknown.

## Next steps
- Decide whether to consume Sourcify layouts directly vs. recompiling with Forge/solc using full metadata.
- Implement mapping-aware slot resolution and enrich tracer outputs with base slot and inferred key where possible.
- Persist layouts on resolve/parse and backfill contracts already stored without layouts.
