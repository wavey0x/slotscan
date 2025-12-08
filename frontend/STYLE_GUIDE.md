# StorageScan Style Guide

Minimalist, professional aesthetic. Black and white. Sharp edges. Monospace throughout.

---

## Colors

| Token | Value | Usage |
|-------|-------|-------|
| `black` | `#000000` | Primary text, borders, active states |
| `white` | `#FFFFFF` | Backgrounds |
| `gray-900` | `#111111` | Headings, emphasis |
| `gray-700` | `#333333` | Body text |
| `gray-500` | `#666666` | Secondary text, placeholders |
| `gray-300` | `#CCCCCC` | Borders, dividers |
| `gray-100` | `#F5F5F5` | Subtle backgrounds, hover states |
| `red` | `#CC0000` | Errors, destructive actions |
| `green` | `#008800` | Success, additions (diffs) |

No blues, no gradients, no shadows.

---

## Typography

**Font**: `JetBrains Mono` (monospace only, no sans-serif)

| Token | Size | Weight | Usage |
|-------|------|--------|-------|
| `text-xs` | 11px | 400 | Captions, labels |
| `text-sm` | 13px | 400 | Body text, inputs |
| `text-base` | 15px | 400 | Primary content |
| `text-lg` | 17px | 500 | Section headings |
| `text-xl` | 21px | 500 | Page headings |
| `text-2xl` | 28px | 300 | Hero/title |

Line height: 1.5 for body, 1.2 for headings.

---

## Spacing

Use multiples of 4px. Standard scale:

| Token | Value |
|-------|-------|
| `space-1` | 4px |
| `space-2` | 8px |
| `space-3` | 12px |
| `space-4` | 16px |
| `space-6` | 24px |
| `space-8` | 32px |
| `space-12` | 48px |

---

## Borders

- Width: `1px` (always)
- Color: `gray-300` (default), `black` (focus/active)
- Radius: `0` (never rounded)

---

## Components

### Buttons

```
Primary:    bg-black text-white border-black
Secondary:  bg-white text-black border-gray-300
Ghost:      bg-transparent text-gray-700 border-transparent

Hover:      invert colors or bg-gray-100
Disabled:   opacity-50, cursor-not-allowed
Height:     36px (standard), 32px (small)
Padding:    16px horizontal
```

### Inputs

```
Background: white
Border:     1px gray-300
Focus:      border-black
Height:     36px
Padding:    8px 12px
Font:       monospace, text-sm
```

### Tables

```
Header:     bg-gray-100, text-xs uppercase, font-medium
Row:        no borders (clean alignment)
Hover:      bg-gray-100
Cell:       py-2 px-3 (compact)
Border:     outer border only (border border-gray-300 on table container)
```

Compact tables use single-line rows with dedicated columns for each data type.
Dynamic columns appear only when data exists (e.g., Key column only shows when mappings present).

### Toggle Switch

```
Container:  inline-flex items-center gap-2 text-xs
Label:      text-gray-500
Track:      w-8 h-4 border
  Off:      bg-white border-gray-300
  On:       bg-black border-black
Knob:       w-2.5 h-2.5, positioned with transition
  Off:      left-0.5 bg-gray-400
  On:       left-[18px] bg-white
```

No rounded corners. Sharp edges throughout.

### HoverCell (Interactive Values)

For copyable/linkable values (addresses, hashes, slot values):

```
Container:  inline-flex items-center gap-1 px-1 -mx-1
Border:     border border-transparent
Hover:      border-dashed border-gray-400
Actions:    opacity-0, group-hover:opacity-100
```

On hover:
- Shows dotted border outline
- Reveals copy button and optional Etherscan link
- Tooltip shows full untruncated value

Use for any value that may be truncated or has copy/link actions.

### Badges/Tags

```
Background: gray-100
Border:     1px gray-300
Padding:    2px 8px
Font:       text-xs
```

---

## Layout

- Max content width: `960px`
- Page padding: `32px` horizontal, `48px` vertical
- Section spacing: `48px` between major sections
- Element spacing: `16px` between related elements
- Always left-align text
- Use CSS Grid or Flexbox for alignment
- Maintain consistent vertical rhythm

---

## States

| State | Treatment |
|-------|-----------|
| Hover | `bg-gray-100` or invert |
| Focus | `border-black`, `outline: 2px solid black` |
| Active | `bg-black text-white` |
| Disabled | `opacity-50` |
| Loading | Pulsing opacity animation |

---

## Icons

- Style: Line icons only (no filled)
- Size: 16px (inline), 20px (standalone)
- Color: Inherit from text

---

## Struct Value Display

When displaying struct changes (before → after), use a multi-line format with each field on its own line:

```
datatype field_name    BEFORE_VALUE →
                       AFTER_VALUE
```

**Rules:**
- Each struct member on its own line
- Type label in gray, field name in default color
- Before value on first line with arrow
- After value on second line, vertically aligned with before value
- Use consistent left padding for alignment
- Never display as JSON - always use the line-per-field format

**Example:**
```
address reward_token      0x0000...0000 →
                          0x7932...e278
bool    is_non_claimable  false →
                          false
```

---

## Do / Don't

**Do:**
- Use consistent spacing
- Align elements to grid
- Keep UI sparse and clean
- Use whitespace generously
- Display struct fields on separate lines (not JSON)

**Don't:**
- Use colors beyond the palette
- Round corners
- Add shadows or gradients
- Use decorative elements
- Mix font families
- Display structs as JSON objects
