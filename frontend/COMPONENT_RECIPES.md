# Frontend component recipes

The product and interaction architecture lives in [`../UX.md`](../UX.md). This file is the short implementation reference.

- Use `PageFrame` with `form` for lookup states and `data` for layouts and transaction evidence.
- Use `EntityHeader`, `MetadataGrid`, and `MetricList` for labeled identity and summary data.
- Use `DataTable` for semantic data tables. Storage history additionally uses the domain-specific `StorageTable` column grammar.
- Render keyed variable paths with `KeyedVariablePath`; never manually concatenate mapping keys in a table view.
- Render before/after values with `ValueDiff` so both lines keep the same left edge.
- Use `CopyButton` with a specific label and the complete underlying value.
- Use `DetailPopover` for supplemental full values and evidence. Required information must remain available by focus or click, not hover alone.
- Use `ViewSwitch` for compact mutually exclusive display modes.
- Keep ordinary research data grayscale. Reserve amber for incomplete or reverted evidence and red for failure.
- Preserve table evidence on narrow screens with horizontal table scrolling; do not hide columns.
