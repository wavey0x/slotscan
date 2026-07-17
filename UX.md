# SlotScan UX Architecture

## Purpose

SlotScan is a research and forensic tool for understanding EVM storage. Its interface should help a user answer, in order:

1. Which contracts and storage slots were written?
2. Which variables or keyed paths do those slots represent?
3. What values were written, and in what execution order?
4. Which writes were temporary, repeated, no-op, or reverted?
5. How confident is SlotScan in the available trace and layout evidence?

The interface should expose evidence without inventing a story for the user. It should feel like one coherent instrument, not a collection of related debugging screens.

## Executive decision

There should be one canonical transaction experience:

```text
/{chain}/tx/{transactionHash}
```

The contract-scoped transaction experience at `/{chain}/{address}?tx={hash}` should stop being a separate product surface.

A transaction is the unit of causal activity. It can write storage owned by many contracts through calls, proxies, and delegate calls. Presenting a transaction as if it belongs to one contract is both conceptually misleading and easy to confuse with a complete transaction report.

The current backend confirms this distinction is artificial: the contract-scoped endpoint is explicitly implemented as a compatibility projection of transaction-wide analysis. The frontend then wraps that projection in different metadata, controls, defaults, and navigation.

Legacy contract-scoped URLs should redirect to the canonical transaction route with a non-filtering focus hint:

```text
/{chain}/{address}?tx={hash}
    → /{chain}/tx/{hash}?focus={address}

/{chain}/{address}/tx/{hash}
    → /{chain}/tx/{hash}?focus={address}
```

`focus` must never hide other storage owners. It should expand and scroll to the requested owner while leaving the complete transaction visible. This preserves the useful contract context without preserving a second transaction UI.

## Product model

SlotScan has three primary surfaces:

| Surface | User question | Canonical route |
|---|---|---|
| Lookup | “What do I want to inspect?” | `/` |
| Contract | “What is this contract's storage layout and current value?” | `/{chain}/{address}` |
| Transaction | “What storage activity occurred in this transaction?” | `/{chain}/tx/{hash}` |

The contract is the unit of layout. The transaction is the unit of history. The interface should not use tabs to imply that transaction history is a property of one contract.

## Current-state diagnosis

### 1. Two transaction shells create two mental models

The contract page contains `TransactionPrompt` and `TransactionDiffView`, while the transaction route uses `TransactionStorageExplorer`.

The contract-scoped experience has:

- a centered contract identity and `Layout / Transaction` tabs;
- a “State Changes” heading;
- `Txn Hash / Block / Slots` metadata;
- a HEX toggle;
- no transaction sender, recipient, contract-owner summary, Grouped view, Timeline view, search, or trace-quality summary.

The transaction-wide experience has:

- a left-aligned transaction header;
- `Transaction / Block / From / To` metadata;
- owner, write, and slot counts;
- Grouped and Timeline views;
- optional search;
- transaction capabilities and trace-quality warnings.

Even when both surfaces eventually render `SlotHistoryTable`, they do not feel like the same report.

### 2. The default view changes with the data

`TransactionStorageExplorer` defaults single-owner transactions to Timeline and multi-owner transactions to Grouped. The same action—opening a transaction hash—therefore produces a different information architecture depending on the result.

The default should always be Grouped. Timeline is a deliberate alternate lens, not a fallback for a small owner count. View state should be shareable in the URL as `?view=timeline`.

### 3. Grouped and Timeline speak different table dialects

Grouped uses a semantic HTML table through `SlotHistoryTable`. Timeline uses a bespoke CSS grid. Their column order, included fields, header implementation, spacing, and truncation behavior differ.

The views should remain semantically distinct:

- Grouped: one row per storage slot, showing initial-to-final value with expandable write history.
- Timeline: one row per storage write event, preserving execution sequence and reverted attempts.

They should not remain visually or structurally unrelated. Both should use the same table frame, column grammar, variable identity, value diff, slot reference, contract identity, and row-density tokens.

### 4. Page width and alignment are accidental

`Header` and `Container` independently hard-code `max-w-4xl` and `px-8`. Form content, contract layout tables, and forensic transaction tables all inherit the same reading width even though they have very different density needs.

Contract navigation is centered while nearly all research data is left-aligned. Page titles, metadata, summaries, toolbars, and tables do not share a common left edge or vertical rhythm.

### 5. The component system contains multiple generations

Examples:

- `Tooltip` and `HoverCard` implement overlapping disclosure behavior with different positioning and styling.
- `TransactionStorageExplorer`, the contract page, and layout views each build metadata blocks directly.
- table headers use 9px, 10px, and `text-xs` labels with different padding and border rules;
- `MappingKeyInput` and `ArrayIndexInput` duplicate value formatting and lookup-result tables;
- the 848-line `SlotRow` combines data interpretation, tooltip composition, packed-field projection, expansion state, and several row layouts;
- several components are no longer referenced outside their own files: `ContractHeader`, `StorageTree`, `ValueDisplay`, `BlockSelector`, `BackLink`, and `Select`;
- `Badge` becomes unused when the dead `ContractHeader` is removed.

The two existing style guides also disagree with the current product and with each other. For example, one prescribes outer table borders and gray header backgrounds while the current transaction tables use row rules and white headers. Mapping display rules in `DISPLAY_STYLE_GUIDE.md` predate the canonical keyed-path renderer.

### 6. Important interactions depend on hover

Some copy actions appear only on hover. The tooltip and hover-card triggers do not provide one consistent keyboard, focus, touch, or Escape behavior. A forensic tool should not hide essential access to full hashes, paths, or raw values behind a mouse-only interaction.

### 7. Loading and warning language is noisy

The loading component rotates through synthetic stages every 600ms. Those messages do not represent authoritative backend progress and create motion without adding certainty.

Capability warnings are concatenated into a single amber paragraph. Contract resolution errors can surface internal exception text directly in the primary UI. Both patterns increase anxiety and visual noise.

## Target information architecture

### Global shell

Create one `AppShell` used by every route:

- one shared horizontal frame for the header and page content;
- a compact brand link on the left;
- a persistent address/transaction lookup on result pages at desktop widths;
- a single “Search” action on narrow screens;
- no route-specific header width.

Create `PageFrame` with only two intentional widths:

- `form`: constrained width for lookup and empty states;
- `data`: wide width for layouts and storage history, with a sensible maximum around 1280–1440px.

The content should use 20–24px horizontal padding on ordinary screens and 12–16px on narrow screens. Research tables should not be forced into a reading-column width.

### Lookup page

The home page should lead with the task, not repeat the brand already shown in the header.

```text
Inspect Ethereum storage
[ Contract address or transaction hash                         ]
[ Analyze ]

Recent
…
```

Use one recent-items store for both contracts and transactions. The current home search does not save transaction searches, while the contract transaction tab maintains a second contract-specific recent list. Consolidate these or remove recent history until it is coherent.

### Contract page

The contract page becomes one left-aligned reference page rather than a tabbed workspace.

```text
Yearn V3 Vault
0xbe53…6204  [copy]       Proxy · Verified

Storage layout
Block 25,485,350         42 variables       Values: Decoded | Hex

NAME              TYPE                  SLOT       VALUE
…
```

Decisions:

- remove `ContractNav` and the `Layout / Transaction` tabs;
- remove the contract-scoped transaction prompt and diff view;
- keep address, proxy, verification, and implementation context in one reusable entity header;
- keep mapping and array lookup as inline expansion within the layout table;
- keep a decoded/hex control for contract snapshots, where it represents a real display mode;
- do not add a HEX toggle to transaction history: raw encoded values belong in the row detail disclosure and remain copyable.

The global lookup accepts a transaction hash from anywhere, so the contract page does not need a second transaction-search product.

### Transaction page

The transaction page becomes the only storage-history report.

```text
0x8e37…22f82 [copy]                                           SUCCESS

BLOCK                       FROM           TO
25,233,936                  0x1b5f…d271    0xfeb4…ff52

CONTRACTS 8        WRITES 71        SLOTS 52

[ Grouped ] [ Timeline ]                         [ Search… ]

…report…
```

Decisions:

- always default to Grouped;
- persist an explicitly selected mode as `?view=grouped|timeline`;
- keep contract sections collapsed by default;
- search expands matching contract sections;
- `?focus={address}` expands and scrolls to one owner but does not filter or hide the rest;
- keep only Contracts, Writes, and Slots as primary summary metrics;
- show “raw slots” only where layout resolution is unavailable;
- place incomplete trace information behind a compact “Data quality” disclosure, visible only when needed;
- translate known backend errors into concise user language, with technical detail available in the disclosure rather than printed inline.

## Unified storage table grammar

All storage-history tables should share this column order:

```text
CONTRACT | VARIABLE | VALUE DIFF | SLOT | STEP
```

Columns disappear only when the surrounding context already provides the value or the capability is unavailable:

- Grouped inside a contract section omits Contract.
- Step is omitted only when execution order is genuinely unavailable.
- Timeline includes Slot; it is forensic evidence and should not disappear merely because the view is chronological.

The invariant core is always:

```text
VARIABLE | VALUE DIFF | SLOT
```

### Row semantics

| Mode | One row represents | Value shown | Expansion |
|---|---|---|---|
| Grouped | One storage slot | Initial value → final value | All writes to that slot |
| Timeline | One SSTORE/TSTORE event | Event before → event after | Optional technical detail, not another write list |

Do not merge the semantics. Reuse the presentation system.

### Table visual rules

- one semantic HTML table primitive, including Timeline;
- 10px uppercase column labels with one tracking token;
- 6px vertical and 8px horizontal cell padding for the compact density;
- one subtle row divider and a stronger header divider;
- no outer card border around ordinary data tables;
- no gray header fill unless a future contrast test proves it necessary;
- top-align multi-line cells;
- left-align decoded and raw values;
- columns carry a priority: identity and value columns (contract, variable, value) are essential; reference columns (slot, step) are secondary;
- below the `sm` breakpoint, secondary columns are dropped and the table fits the viewport with no horizontal panning; the contract folds into the variable cell in Timeline view;
- dropping a secondary column must not orphan its data: the full slot stays reachable through the variable's evidence disclosure, which opens on tap as well as hover;
- at `sm` and above, tables keep a minimum readable width; horizontal scrolling engages only when the table exceeds its container, signaled by edge fades on the scrollable side;
- when a table fits its container, column headers stick to the viewport top during vertical scroll;
- abbreviate hashes, keys, and addresses in display (`0xa346...4150`), preserve the full value in copy and detail actions;
- integers above 15 digits display compactly (`1e27`, `1.2345e21`); tooltips and copy actions carry full precision;
- one-key mappings remain inline; multi-key mappings use one key per continuation line;
- the before value and arrow occupy the first line; the after value begins at the same left edge on the second line;
- a write whose value did not change shows the value once with the unchanged indicator (`↺`) instead of a before → after arrow, at every disclosure level (net row, timeline event, interim write, packed field).

### Canonical row building blocks

The table should compose small domain-aware cells rather than branch repeatedly inside one row component:

- `ContractIdentity`: name, abbreviated linked address, copy.
- `StorageVariableIdentity`: leaf-first canonical path, abbreviated keys, type, full-path copy.
- `StorageValueDiff`: aligned before/after values and zero-value treatment.
- `SlotReference`: compact slot plus full raw slot detail and copy.
- `StepReference`: exact execution step or unavailable marker.
- `WriteOutcome`: only renders meaningful forensic qualifiers such as `reverted`.

## Target component architecture

```text
AppShell
├── GlobalHeader
│   └── GlobalLookup
└── PageFrame (form | data)
    ├── ContractPage
    │   ├── EntityHeader
    │   ├── PageSectionHeader
    │   └── StorageLayoutTable
    │       └── SlotLookupPanel
    └── TransactionPage
        ├── TransactionHeader
        │   ├── MetadataGrid
        │   └── MetricList
        ├── TransactionToolbar
        │   ├── ViewSwitch
        │   └── SearchField
        ├── GroupedStorageView
        │   └── StorageDiffTable (summary rows)
        └── TimelineStorageView
            └── StorageDiffTable (event rows)
```

### Shared primitives

Create or consolidate:

- `PageFrame`
- `EntityHeader`
- `MetadataGrid` and `MetadataItem`
- `MetricList`
- `ViewSwitch`
- `DataTable`, `DataTableHeader`, `DataTableRow`, and `DataTableCell`
- `ReferenceValue` for link + abbreviation + copy + full value
- `DetailPopover` as the single replacement for `Tooltip` and `HoverCard`
- `Notice` with `info`, `warning`, and `error` variants
- `EmptyState`
- `LoadingState`

`DetailPopover` must support hover, keyboard focus, click/touch, Escape, viewport-aware positioning, and focus return. Its visual treatment should follow SlotScan's square, border-led language instead of the current rounded shadow card.

### Domain components

Refactor `SlotRow` by responsibility:

- a pure adapter derives a display model from `SlotChangeResponse`;
- `StorageSummaryRow` renders one grouped slot;
- `StorageEventRow` renders one write event;
- `PackedFieldRows` renders decoded packed fields;
- `WriteHistoryRows` renders expanded event history;
- detail content is produced by `StorageEvidenceDetail`.

The adapter should be testable without rendering React. Formatting, classification, and type selection should not be recomputed in several JSX branches.

Split `TransactionStorageExplorer` into a data/controller component plus the header, toolbar, grouped, and timeline views. The controller should own search, view state, focus state, and derived event order; presentation components should receive prepared data.

## Interaction and disclosure rules

### Copy and links

- use the shared `CopyButton` everywhere;
- transaction hashes and addresses themselves are explorer links;
- the copy icon copies the full underlying value, never the abbreviation;
- canonical variable-path copy stays visible because it is a primary research action;
- hover-only actions must also appear on keyboard focus and remain usable on touch.

### Detail disclosure

The main table shows the resolved conclusion. Detail disclosure shows the evidence:

- full canonical path;
- full slot;
- raw encoded before/after values;
- mapping keys and types;
- array index;
- struct definition and packed offsets;
- provenance and confidence;
- frame, depth, opcode, storage address, and code address where available.

Do not repeat information in the detail panel merely because it exists in the API.

### Status and color

Use color sparingly and semantically:

- default text and structure remain grayscale;
- amber is reserved for incomplete or reverted evidence;
- red is reserved for failure;
- green is reserved for successful copy feedback or an affirmative status that needs attention.

Do not color ordinary “net” or “restored” labels. Do not show those labels in every row. Temporary and reverted activity is visible through the write history itself and through concise outcome markers where necessary.

### Loading

Replace synthetic rotating messages with a stable state:

```text
Analyzing transaction…
Large traces may take up to two minutes.
```

If authoritative backend progress becomes available later, expose actual stages. Do not simulate progress in the UI.

## Responsive and accessibility requirements

- All controls are reachable and operable by keyboard.
- Icon-only buttons have specific accessible names: “Copy transaction hash,” “Copy storage path,” and similar.
- Expand/collapse controls expose `aria-expanded` and identify their target.
- View switches expose a selected state and are represented in the URL.
- Tooltips are supplemental; no required content is hover-only. Detail disclosures open on tap and focus as well as hover.
- Tables keep semantic headers and associations.
- Data tables horizontally scroll below their minimum readable width at `sm` and above; below `sm` they shed secondary columns instead and fit the viewport.
- Small icon controls (copy, expand) use the `.touch-hitbox` recipe: an invisible hit area grown to a comfortable tap size on coarse pointers, exact on fine pointers.
- The global header keeps an in-place search at every width; on narrow screens it expands from an icon into a full-width row.
- The page itself should not acquire horizontal overflow.
- Focus indicators remain visible against white and gray backgrounds.
- Motion respects `prefers-reduced-motion`.
- Loading and copy feedback use appropriate polite live regions.

## Design tokens and documentation

Keep the monochrome, square, monospace identity. Tighten it into explicit tokens:

| Token | Target |
|---|---|
| Page label | 10px, uppercase, tracked, gray-500 |
| Data text | 12px, regular, gray-900 |
| Secondary data | 10–11px, gray-500 |
| Page title | 18px, medium |
| Compact row padding | 6px vertical, 8px horizontal |
| Section gap | 24px |
| Page gap | 32px |
| Rule | gray-200 ordinary, gray-300 structural |
| Interaction target | at least 24px inside dense tables; 36px for form controls |

Avoid arbitrary 9px/10px/11px decisions inside individual components. Avoid `gray-50/30`, `gray-100/80`, and one-off opacity mixtures unless they become named semantic recipes.

After implementation, replace `frontend/STYLE_GUIDE.md` and `frontend/src/DISPLAY_STYLE_GUIDE.md` with this document plus a short component recipe reference. Maintaining three partially contradictory design documents is worse than maintaining one.

## Migration plan

### Phase 1: Canonicalize transaction navigation

1. Make `/{chain}/tx/{hash}` the only transaction report.
2. Add `view` and non-filtering `focus` query-state handling.
3. Redirect both legacy contract transaction URL forms.
4. Remove `TransactionPrompt`, `TransactionDiffView`, and transaction tabs from the contract page.
5. Remove frontend use of `useTxDiff`, `fetchTxDiff`, and `TransactionDiffResponse`.
6. Keep the backend contract-scoped endpoint temporarily as a documented compatibility API; remove it only in a separate API deprecation change.

This phase immediately removes the most visible inconsistency without requiring a table rewrite.

### Phase 2: Establish the shared shell and headers

1. Add `AppShell` and width-aware `PageFrame`.
2. Make `Header` and page content consume the same frame.
3. Build `EntityHeader`, `MetadataGrid`, `MetricList`, and `TransactionToolbar`.
4. Refactor the contract and transaction headers onto those components.
5. Replace duplicated recent-search state with one model.

### Phase 3: Unify storage-history tables

1. Build semantic `DataTable` primitives and shared column tokens.
2. Move Timeline from a CSS grid to `StorageDiffTable` event rows.
3. Keep Grouped on the same table with summary rows.
4. Add Slot to Timeline and use the canonical column order.
5. Extract the variable, value, slot, step, and contract cells.
6. Add horizontal-scroll containment and narrow-width tests.

### Phase 4: Decompose storage interpretation

1. Extract a pure slot-to-display-model adapter from `SlotRow`.
2. Split summary, packed-field, event-history, and evidence-detail renderers.
3. Replace `Tooltip` and `HoverCard` with `DetailPopover`.
4. Add fixture tests for static slots, mappings, nested mappings, arrays, packed structs, raw slots, no-op writes, restored writes, and reverted frames.

### Phase 5: Tighten the contract layout experience

1. Move the contract page to the shared entity header and table frame.
2. Refactor layout rows onto shared table primitives.
3. Extract shared lookup form and result-table code from mapping and array inputs.
4. Make the decoded/hex display control explicit and local to the layout table.

### Phase 6: Remove drift

1. Delete confirmed dead components: `ContractHeader`, `StorageTree`, `ValueDisplay`, `BlockSelector`, `BackLink`, and `Select`.
2. Delete `Badge` if no remaining surface needs it.
3. Remove stale frontend transaction types and hooks.
4. Consolidate the style documents.
5. Search for direct table, metadata-label, copy, tooltip, and notice implementations that bypass the shared components.

Do not perform this as a single visual rewrite. Each phase should be independently deployable and should leave route compatibility intact.

## Acceptance criteria

### Information architecture

- A transaction hash always renders the same canonical transaction header and report.
- Legacy contract transaction URLs redirect to the canonical route.
- A focused contract is expanded without hiding other storage owners.
- The contract page contains no transaction tab or alternate transaction renderer.

### Data integrity

- Transaction-wide storage owners, all SSTORE/TSTORE events, no-op writes, restored writes, and reverted writes remain available.
- Grouped rows remain one slot summary; Timeline rows remain one write event.
- Timeline includes slot and execution step when available.
- No display refactor changes canonical copied paths or raw values.

### Consistency

- Grouped and Timeline use the same table primitives and column grammar.
- Contract layout and lookup-result tables use the same header, row, and spacing recipes.
- There is one transaction metadata header implementation.
- There is one reference-value implementation for abbreviation, explorer linking, full-value disclosure, and copy.
- There is one detail-popover implementation.
- There is one notice system and one loading system.

### Behavior

- Grouped is the stable default for every transaction.
- View state is shareable in the URL.
- Search behavior and focus behavior are covered by end-to-end tests.
- Multi-key paths stack without colliding with value columns.
- Single-key paths remain compact.
- Tables do not visually overlap at supported viewport widths.

### Accessibility

- The entire report is usable by keyboard.
- Copy, disclosure, expansion, and view controls have specific accessible names and visible focus.
- Full forensic values are available without hover.
- Table headers remain semantically associated with cells.

### Code health

- No frontend import or call remains for the contract-scoped transaction endpoint.
- `TransactionStorageExplorer` is a controller rather than a 400-line page renderer.
- `SlotRow` no longer owns every storage display mode in one component.
- Confirmed dead components and contradictory style documents are removed.
- Production fixtures cover both the transaction-wide and legacy-redirect entry paths.

## What not to add

- No dashboard cards for every metric.
- No interpretation-heavy labels such as “final changes” versus “temporary round-trips.”
- No default filtering that hides writes.
- No separate mobile information hierarchy that omits evidence.
- No compiler execution in the browser.
- No new color system, shadows, gradients, or decorative containers.
- No wholesale component-library dependency solely to obtain table or tooltip primitives.

The goal is not to make SlotScan look more designed. The goal is to make every screen feel like the same precise research instrument.
