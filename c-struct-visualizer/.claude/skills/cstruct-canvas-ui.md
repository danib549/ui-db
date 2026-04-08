# Skill: Canvas UI — Block Rendering and Visual Design

## When to Use
Apply this skill when working on the visual appearance of blocks on the canvas: struct/union/function block drawing, headers, field rows, badges, padding visualization, colors, dark mode theming, file containers, collapse buttons. This covers what things look like, not the engine that draws them (see `cstruct-canvas-engine.md` for the pipeline).

---

## 1. Block Structure

All blocks share the same visual structure, differentiated by header color and content:

```
┌─────────────────────────────────────────────┐
│ Header (36px)                               │
│ ▶ displayName        {meta}         [PACKED] │
├─────────────────────────────────────────────┤
│ ⚫ fieldName   type       +offset    size   │  ← Row (24px each)
│ ⚫ fieldName   type       +offset    size   │
│ ░░ (padding)   (padding)  +offset    size   │  ← Striped background
│ ◆ bits:3       type       +offset    3b     │  ← Bitfield
│ ...                                         │
└─────────────────────────────────────────────┘
```

### Block Dimensions (from `cstruct-constants.js`)

| Constant | Value | Use |
|----------|-------|-----|
| `BLOCK.minWidth` | 340 | Block width |
| `BLOCK.headerHeight` | 36 | Header row height |
| `BLOCK.fieldRowHeight` | 24 | Each field row height |
| `BLOCK.padding` | 8 | Bottom padding after last field |
| `BLOCK.cornerRadius` | 6 | Rounded corner radius |
| `BLOCK.badgeSize` | 8 | Category badge diameter |
| `BLOCK.badgeMarginLeft` | 10 | Badge X offset from block left |
| `BLOCK.nameColX` | 28 | Field name column X offset |
| `BLOCK.typeColX` | 150 | Type column X offset |
| `BLOCK.offsetColX` | 260 | Offset column X offset |
| `BLOCK.sizeColX` | 310 | Size column X offset |

### Block Height Calculation

```javascript
function calculateBlockHeight(entity, collapsed) {
  if (collapsed) return BLOCK.headerHeight;  // Header only
  const fieldCount = entity.fields ? entity.fields.length : 0;
  return BLOCK.headerHeight + fieldCount * BLOCK.fieldRowHeight + BLOCK.padding;
}
```

## 2. Block Types and Header Styles

| Type | Header Background | Text Color | Meta Info |
|------|------------------|------------|-----------|
| Struct | `colors.headerBg` (gray) | `colors.headerText` | `{size}B  {alignment}-al` |
| Union | `colors.unionHeader` (purple) | `colors.unionHeaderText` (white) | `union  {size}B  {alignment}-al` |
| Function | `colors.functionHeader` (green) | `colors.functionHeaderText` (white) | `{paramCount}p  → {returnType}` |

### Header Drawing

```javascript
function drawHeader(ctx, entity, x, y, width, r, colors, collapsed) {
  // 1. Fill header with rounded top corners
  // 2. Draw divider line at bottom of header
  // 3. Left: collapse triangle button (at x+8, toggles ▶/▼)
  // 4. Left: entity name (bold 12px, truncated to 45% width, at x+24)
  // 5. Right: meta info (10px, right-aligned)
  // 6. Optional: PACKED badge (top-right corner, amber pill)
}
```

### Collapse Triangle Button

Small triangle in the header (left of entity name) that toggles collapsed state:

```javascript
function drawCollapseButton(ctx, cx, cy, collapsed, color) {
  // collapsed = right-pointing triangle (▶)
  // expanded = down-pointing triangle (▼)
  // alpha 0.7 for subtlety
}
```

Hit test zone: left 20px of header (`hitTestCollapseButton`).

### Anonymous Type Handling
Names starting with `__anon_` or equal to `(anonymous)` are displayed in italic:
```javascript
if (label.startsWith('__anon_') || label === '(anonymous)') {
  label = '(anonymous)';
  ctx.font = 'italic bold 12px system-ui, sans-serif';
}
```

### Function Name Display
Function names get `()` appended: `read_sensor()`

## 3. Field Rows

Each field row is 24px tall and contains:

| Element | Position | Font | Content |
|---------|----------|------|---------|
| Badge | `x + 10` center | — | Category-colored shape |
| Name | `x + 28` | 11px system-ui | Field name (+ `:N` for bitfields) |
| Type | `x + 150` | 11px monospace | Type string |
| Offset | `x + 260` | 10px monospace | `+N` (byte offset) |
| Size | Right-aligned at `x + width - 10` | 10px monospace | `NB` or `Nb` for bitfields |

### Padding Rows
Padding fields (`category === 'padding'`) get special treatment:
- Italic font for the name
- Secondary text color
- Striped background (diagonal lines at 6px intervals)

```javascript
function drawPaddingBackground(ctx, x, y, w, h, colors) {
  ctx.fillStyle = colors.paddingBg;      // Subtle background
  ctx.fillRect(x + 1, y, w - 2, h);
  // Diagonal stripes (clipped to row bounds)
  ctx.strokeStyle = colors.paddingStripe;
  for (let sx = x - h; sx < x + w; sx += 6) {
    ctx.moveTo(sx, y + h);
    ctx.lineTo(sx + h, y);
  }
}
```

## 4. Badge Shapes

Each field category has a colored shape badge:

| Category | Shape | Color (light) | Color (dark) |
|----------|-------|---------------|--------------|
| `integer` | Circle | `#22C55E` green | `#4ADE80` |
| `float` | Circle | `#F97316` orange | `#FB923C` |
| `pointer` | Circle | `#A78BFA` purple | `#C4B5FD` |
| `array` | Circle | `#14B8A6` teal | `#2DD4BF` |
| `struct` | Square | `#3B82F6` blue | `#60A5FA` |
| `bitfield` | Diamond | `#EAB308` yellow | `#FACC15` |
| `padding` | Stripe (horizontal bar) | `#9CA3AF` gray | `#6B7280` |
| `enum` | Circle | `#EC4899` pink | `#F472B6` |

Drawing:
```javascript
function drawBadge(ctx, cx, cy, size, color, shape) {
  if (shape === 'circle')  → ctx.arc(cx, cy, half, 0, 2π)
  if (shape === 'square')  → ctx.fillRect(cx - half, cy - half, size, size)
  if (shape === 'diamond') → 4-point path (top, right, bottom, left)
  if (shape === 'stripe')  → ctx.fillRect(cx - half, cy - 1.5, size, 3)
}
```

## 5. Block States

| State | Shadow | Border | Alpha |
|-------|--------|--------|-------|
| Normal | `shadow` (4px blur) | `boxBorder` (gray, 1px) | 1.0 |
| Hovered | `shadowHover` (10px blur, blue tint) | `boxBorderHover` (blue, 1.5px) | 1.0 |
| Selected | `shadowHover` (10px blur) | `boxBorderSelected` (darker blue, 2px) | 1.0 |
| Dimmed (not in trace) | Normal shadow | Normal border | 0.15 |

### Collapsed State
When the collapse triangle is clicked, a block collapses to show only the header (no fields). Height becomes `BLOCK.headerHeight` (36px). Triangle changes from ▼ to ▶.

## 6. File Containers (By-File Layout)

When `by-file` layout is active, entities are grouped by `sourceFile` inside visual container boxes:

```javascript
function drawFileContainer(ctx, filename, x, y, width, height) {
  // 1. Semi-transparent background (0.35 alpha)
  // 2. Dashed border (6,4 dash pattern, 1.5px)
  // 3. Title bar: filename in bold 11px at top-left (28px title height)
}
```

Colors: `fileContainerBg`, `fileContainerBorder`, `fileContainerTitle` (with dark mode fallbacks).

Containers are drawn BEFORE connections and blocks in the render pipeline (they appear behind everything).

## 7. Dark Mode

Theme is toggled via `document.body.classList.contains('dark')`. Two complete color sets:

```javascript
function getColors() {
  return document.body.classList.contains('dark') ? CANVAS_COLORS_DARK : CANVAS_COLORS;
}
function getCategoryColors() {
  return document.body.classList.contains('dark') ? CATEGORY_COLORS_DARK : CATEGORY_COLORS;
}
```

Key dark mode differences:
- Background: `#1a1b23` (dark) vs `#F9FAFB` (light)
- Box background: `#1F2028` vs `#FFFFFF`
- Grid dots: `#2d2e3a` vs `#E5E7EB`
- All category colors are brighter in dark mode for contrast

### PACKED Badge

Small amber pill in top-right corner of header:
```javascript
function drawPackedBadge(ctx, rightX, topY, colors) {
  // Text: "PACKED" in bold 8px
  // Background: packedBadgeBg (amber in light, dark brown in dark)
  // Text color: packedBadgeText (dark amber in light, light amber in dark)
  // Rounded rect with 3px radius
}
```

## 8. Text Truncation

All text is truncated to fit its column width:
```javascript
function truncateText(ctx, text, maxWidth) {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let t = text;
  while (t.length > 1 && ctx.measureText(t + '…').width > maxWidth) {
    t = t.slice(0, -1);
  }
  return t + '…';
}
```

Entity names truncated to 45% of block width. Field names, types, offsets each truncated to their column widths.

## 9. Rounded Rectangles

Utility used throughout:
```javascript
function roundRect(ctx, x, y, w, h, r) {
  // Uses arcTo for rounded corners
  // Not exported — local to cstruct-blocks.js
}
```

## 10. Exports from `cstruct-blocks.js`

| Function | Purpose |
|----------|---------|
| `drawBlock()` | Draw a complete struct/union/function block |
| `calculateBlockHeight()` | Compute block pixel height |
| `hitTestField()` | Return field index at canvas coordinates |
| `hitTestCollapseButton()` | Check if click is on collapse triangle |
| `drawFileContainer()` | Draw a file grouping container (by-file layout) |

## 11. Anti-Patterns

- **Never hardcode colors** — always read from `getColors()` / `getCategoryColors()` for theme support
- **Never use DOM elements inside the canvas** — everything is drawn with Canvas 2D API
- **Never store visual state in blocks.js** — it's stateless, reads from state on every call
- **Never add inline styles** — canvas elements use constants from `cstruct-constants.js`
