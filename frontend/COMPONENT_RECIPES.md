# Frontend component recipes

The product and interaction architecture lives in [`../UX.md`](../UX.md). This file is the short implementation reference.

- Use `PageFrame` with `form` for lookup states and `data` for layouts and transaction evidence.
- Use `EntityHeader`, `MetadataGrid`, and `MetricList` for labeled identity and summary data.
- Use `DataTable` for semantic data tables. Storage history additionally uses the domain-specific `StorageTable` column grammar.
- Derive transaction storage identity with `deriveStorageIdentity` and render it with `StorageVariableCell`; never assemble variable/type/qualifier order per surface. `KeyedVariablePath` remains the keyed-path renderer inside that cell, and eligible keys copy individually rather than as one structural path.
- Format every physical slot, range, root, and byte extent with `formatStorageLocation`, then render ordinary location cells with `StorageLocationCell`. Keep the full canonical slot reachable through its disclosure, and never couple location notation to the Decoded/Hex value mode.
- Render before/after values with `ValueDiff` so both lines keep the same left edge.
- Use `CopyButton` for reusable values, not variable, field, struct, or type names. Give it a specific label and the complete underlying value.
- Use `DetailPopover` for supplemental full values and evidence. Required information must remain available by focus or click, not hover alone.
- Use `ViewSwitch` for compact mutually exclusive display modes.
- Keep ordinary research data grayscale. Reserve amber for incomplete or reverted evidence and red for failure.
- Preserve primary table evidence on narrow screens. Secondary columns may collapse only when the same evidence remains available through row disclosure; otherwise use table-local horizontal scrolling.
