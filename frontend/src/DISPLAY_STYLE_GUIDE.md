# Storage Diff Display Style Guide

This document defines the display rules for rendering storage changes in the DiffTable.

## Column Layout

| VARIABLE | VALUE | SLOT | STEP |
|----------|-------|------|------|
| Names/types only | Values only | Slot number | Execution order |

## Core Rules

### Rule 1: VARIABLE Column Contains Names Only
- Variable names
- Type labels
- Struct field names with tree connectors
- **NEVER** show values in this column

### Rule 2: VALUE Column Contains Values Only
- Before → After values
- No type labels
- No variable names
- **NEVER** show `type name = value` format

### Rule 3: Struct Fields Use Tree-Style Hierarchy

For structs with multiple fields (packed or otherwise):

```
VARIABLE                      VALUE
────────────────────────────  ──────────────────────
StructType variableName
├ type fieldOne               0 →
│                             1,234
├ type fieldTwo               false →
│                             true
└ type fieldThree             0x000... →
                              0xabc...
```

### Rule 4: Single-Field Structs Follow Same Pattern

Even structs with only 1 field use tree connectors:

```
VARIABLE                      VALUE
────────────────────────────  ──────────────────────
ExchangeRateInfo info
└ uint256 exchangeRate        0 →
                              1,000,000,000,000
```

**NOT** this (wrong - shows name in VALUE column):
```
VARIABLE                      VALUE
────────────────────────────  ──────────────────────
ExchangeRateInfo info         uint256 exchangeRate = 0 →
                              uint256 exchangeRate = 1000
```

## Implementation Details

### hasPacked Condition
```tsx
// Use packed display for 1+ fields, not just 2+
const hasPacked = slot.packed_fields && slot.packed_fields.length >= 1;
```

### PackedFieldsVariableDisplay
Shows field names with tree glyphs (├, │, └) in VARIABLE column.

### PackedFieldsValueDisplay
Shows only before→after values in VALUE column.

### formatDecodedValue
Used for simple values. Should NOT be used for struct objects.
If a decoded value is an object, use packed_fields instead.

## Slot Types

### Simple Variables
```
VARIABLE                      VALUE
────────────────────────────  ──────────────────────
uint256 totalSupply           0 → 1,000,000
```

### Mappings
```
VARIABLE                      VALUE
────────────────────────────  ──────────────────────
balances
└ uint256                     0 → 500
```
HoverCard shows: mapping key (address/uint)

### Dynamic Arrays - Length Slot
```
VARIABLE                      VALUE
────────────────────────────  ──────────────────────
uint256 rewards (array len)   0 → 4
```

### Dynamic Arrays - Element Slots
```
VARIABLE                      VALUE
────────────────────────────  ──────────────────────
RewardType rewards[0]
├ address reward_token        0x000... → 0xabc...
│
└ bool is_non_claimable       false → true
```
HoverCard shows: array index

### Static Structs
```
VARIABLE                      VALUE
────────────────────────────  ──────────────────────
ExchangeRateInfo exchangeRate
├ address oracle              0x000... → 0xcb7...
│
└ uint96 lastTimestamp        0 → 1,741,832,327
```

## HoverCard Context

The HoverCard (on hover) provides additional context:
- Full slot hex value
- Struct definition with all members
- Mapping keys with types
- Array indices
- Type information

This keeps the main table clean while providing detail on demand.
