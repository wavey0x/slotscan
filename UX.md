# SlotScan UX requirements

SlotScan is an information-dense forensic instrument. The interface should
expose evidence clearly without guessing or hiding uncertainty.

## Canonical navigation

- `/` is the universal address/transaction lookup.
- `/{chain}/{address}` is the contract layout and state surface.
- `/{chain}/tx/{hash}` is the only transaction surface.
- `/{chain}/compare` is the only storage-layout comparison surface.
- `?focus={address}` may open and scroll to one owner while retaining the full
  transaction.
- View and value-mode choices are shareable query parameters.

Do not add legacy redirects or a second contract-scoped transaction UI.

## Layout comparison

- Add a quiet `Compare layout` action beside the contract page’s Storage layout
  heading. It prefills the inspected input address without replacing a proxy or
  EIP-7702 authority with its code address.
- Keep drafts local and put only submitted addresses plus optional exact block
  references in the URL. Submission pushes browser history; back and forward
  restore prior reports.
- Focus To after contract-page prefill and otherwise focus the first empty
  address. Validate addresses and decimal block selectors inline, submit on
  Enter, and resolve only on submission.
- `Swap` is explicit text plus direction and swaps both addresses, visible
  selectors, and still-valid exact hashes. Editing an address or selector drops
  that side’s hidden stale hash.
- Keep optional blocks in one secondary disclosure with Latest placeholders.
- Show resolved From and To subjects as compact columns. Direct contracts show
  one contract address; proxies and EIP-7702 subjects keep Storage and Code
  identities visibly separate.
- Fold total, changed, and conflict counts into the table filters in a neutral
  polite live region. Do not add a separate summary, verdict, or disclaimer.
  Reserve explanatory prose for unavailable data and upstream failures.
- Keep the filters in the shared horizontal toggle pattern directly above the
  full-width table.
- Default the comparison table to All, with Changes and Conflicts views. Search
  appears only at 50 rows or more and covers paths, types, scopes, and slots.
- The table has exactly `Location / From / To`. Location is formatted from both
  structured regions, including packed extents, inclusive ranges, roots,
  moves, additions, removals, and scope-root changes. Do not add a Result,
  Change, Review, or Breaking column.
- Render slot identifiers as the same bare values used elsewhere in the app.
  Put byte ranges, roots, and other location qualifiers on a smaller muted line
  below the identifier.
- Group scopes under Default storage or their proven ERC-7201 identifier. Every
  changed row exposes all backend-owned objective details in one keyboard
  accessible disclosure. Unchanged rows do not show disclosure controls.
- Mark conflicts with text for assistive technology and a restrained visual
  indicator; never rely on color. Stack inputs and subjects on narrow screens
  and preserve dark theme and reduced-motion behavior.
- Distinguish no code, unverified source, unsupported/non-exact/invalid
  layouts, bounded analysis, and upstream failures. Keep a successfully
  resolved side visible when the other side is unavailable.

## Contract page

- Show contract, proxy, or delegate identity and verification state.
- Keep layout and value columns aligned in one scan-friendly table.
- Allow block selection without mixing transaction history into the contract
  page.
- Support explicit mapping-key and array-index lookups.
- Show raw values when layout or decoding evidence is unavailable.

## Transaction page

- Grouped view is the stable default: one row per storage slot with
  transaction-initial and transaction-final values.
- Timeline view is available only when exact execution ordering exists: one row
  per physical write event.
- Display every persistent storage owner; focus never filters owners.
- Make no-op, restored, reverted-only, and net-changed classifications visible.
- Keep packed-field and keyed-variable paths canonical across grouped and
  timeline views.
- Surface capability warnings close to the report controls.
- Provide search when reports are large.

## Evidence presentation

- Encoded values remain copyable in decoded mode.
- Large integers, addresses, hashes, mapping keys, and slots have compact
  display text plus access to full values.
- Copy reusable values, not structural labels. Variable, field, struct, and
  type names do not have copy actions. Keyed paths expose eligible keys
  individually rather than copying the whole path.
- Unknown values say `unknown`; they do not appear as zero.
- Inferred and raw slot attribution remain distinguishable from exact compiler
  layout evidence.
- Reverted and incomplete evidence use text/labels as well as color.

## Layout and density

- Use the shared page frame, entity header, metadata, table, hover detail, copy,
  and value-diff primitives.
- Tables may scroll horizontally on narrow screens without overflowing the page.
- Primary controls remain keyboard accessible and expose meaningful labels.
- Theme selection applies consistently to page chrome, tables, and overlays.
- Avoid decorative cards or duplicated summaries that slow forensic scanning.

## Loading and failure states

- Long trace analysis has a specific loading state and realistic expectation.
- Trace unavailability, RPC errors, missing contracts, missing layouts, and
  partial contract resolution have distinct messages.
- Retrying contract resolution must not retrace a transaction unnecessarily.
- Empty filtered results differ from an empty transaction.

## UX acceptance

Playwright coverage should exercise:

- universal lookup and recent inspections;
- a verified contract layout and keyed lookup;
- a multi-owner transaction in grouped and timeline views;
- focused owner navigation;
- packed values, canonical paths, copy actions, and large integers;
- restored, no-op, and reverted writes;
- incomplete trace/layout warnings;
- keyboard interaction, narrow viewport containment, and theme behavior.
