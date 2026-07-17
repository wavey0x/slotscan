# SlotScan UX requirements

SlotScan is an information-dense forensic instrument. The interface should
expose evidence clearly without guessing or hiding uncertainty.

## Canonical navigation

- `/` is the universal address/transaction lookup.
- `/{chain}/{address}` is the contract layout and state surface.
- `/{chain}/tx/{hash}` is the only transaction surface.
- `?focus={address}` may open and scroll to one owner while retaining the full
  transaction.
- View and value-mode choices are shareable query parameters.

Do not add legacy redirects or a second contract-scoped transaction UI.

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
- Large integers, addresses, hashes, paths, and slots have compact display text
  plus access to full values.
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
