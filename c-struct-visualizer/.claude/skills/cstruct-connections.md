# Skill: Connection Line Rendering

## When to Use
Apply this skill when working on dependency lines between blocks: Bezier curves, anchor point calculation, side selection, arrow drawing, connection type styling, subgraph highlighting, dimming behavior, and visibility filtering. Connection rendering spans two files: `cstruct-connections.js` (pure drawing helpers) and `cstruct-app.js` (`drawAllConnections()` which orchestrates them).

---

## 1. Architecture

**`cstruct-connections.js`** — Pure stateless drawing functions:
- `chooseSides(srcBox, tgtBox)` — which edge to connect from
- `calculateAnchor(box, side, yOffset)` — anchor point on box edge
- `drawBezierConnection(ctx, src, tgt, color, lineWidth)` — draw the curve
- `drawArrow(ctx, anchor, color)` — arrowhead at target

**`cstruct-app.js`** — `drawAllConnections(colors, traceGraph, visibleSet)`:
- Iterates all connections from state
- Skips connections where either endpoint is filtered out (via `visibleSet`)
- Computes anchor positions based on current block positions
- Applies dimming and highlighting
- Calls the drawing functions from `cstruct-connections.js`

This separation keeps connections.js testable and stateless, while app.js handles the state integration.

## 2. Visibility Filtering

Before drawing any connection, the render pipeline checks if both endpoints are visible:

```javascript
if (visibleSet && (!visibleSet.has(conn.source) || !visibleSet.has(conn.target))) continue;
```

`visibleSet` comes from `getVisibleEntities()` in `cstruct-search.js`. It accounts for:
- Type filters (struct/union/function)
- File filters (show only specific source files)
- Search query matches
- Focus mode (entity + connected subgraph)
- Per-entity hidden toggles (sidebar checkboxes)
- Stdlib filter (hide standard C library items)

## 3. Side Selection

Determines which edge (left or right) each block connects from, based on relative positions:

```javascript
function chooseSides(srcBox, tgtBox) {
  const srcCx = srcBox.x + srcBox.width / 2;
  const tgtCx = tgtBox.x + tgtBox.width / 2;
  return srcCx <= tgtCx
    ? { srcSide: 'right', tgtSide: 'left' }
    : { srcSide: 'left', tgtSide: 'right' };
}
```

Source connects from the side facing the target. This means lines always flow outward (never cross through a block).

## 4. Anchor Points

An anchor is a point on a block's edge at a specific Y offset:

```javascript
function calculateAnchor(box, side, yOffset) {
  const x = side === 'left' ? box.x : box.x + box.width;
  const y = box.y + yOffset;
  return { x, y, side };
}
```

### Source Anchor Y Position
The source anchor Y is at the specific field row that references the target:

```javascript
const fieldIdx = srcEntity.fields
  ? srcEntity.fields.findIndex(f => f.name === conn.field)
  : -1;
const srcYOffset = fieldIdx >= 0
  ? BLOCK.headerHeight + fieldIdx * BLOCK.fieldRowHeight + BLOCK.fieldRowHeight / 2
  : BLOCK.headerHeight / 2;  // Fallback: center of header
```

### Target Anchor Y Position
Always at the center of the header:
```javascript
const tgtYOffset = BLOCK.headerHeight / 2;  // Always 18px from top
```

## 5. Bezier Curves

Cubic Bezier with horizontal control points for smooth S-curves:

```javascript
function drawBezierConnection(ctx, src, tgt, color, lineWidth) {
  const offset = LINE.controlPointOffset;  // 80px
  const dirSrc = src.side === 'right' ? 1 : -1;
  const dirTgt = tgt.side === 'right' ? 1 : -1;

  ctx.beginPath();
  ctx.moveTo(src.x, src.y);
  ctx.bezierCurveTo(
    src.x + offset * dirSrc, src.y,    // CP1: horizontal from source
    tgt.x + offset * dirTgt, tgt.y,    // CP2: horizontal from target
    tgt.x, tgt.y,                       // End point
  );
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.stroke();
}
```

Control points extend horizontally from each anchor by 80px in the direction of the connected side. This creates smooth curves that avoid sharp angles.

## 6. Arrows

Small filled triangle at the target anchor:

```javascript
function drawArrow(ctx, anchor, color) {
  const size = LINE.arrowSize;  // 6px
  const dir = anchor.side === 'left' ? -1 : 1;
  // Triangle pointing inward toward the block
  ctx.moveTo(anchor.x, anchor.y);
  ctx.lineTo(anchor.x + size * dir, anchor.y - size / 2);
  ctx.lineTo(anchor.x + size * dir, anchor.y + size / 2);
  ctx.fill();
}
```

Arrow points inward (toward the block it connects to).

## 7. Connection Type Styling

| Type | Color | Line Style | Meaning |
|------|-------|-----------|---------|
| `nested` | `connectionLine` (blue) | Solid | Struct field is another struct |
| `param` | `connectionLine` (blue) | Solid | Function parameter is a struct |
| `return` | `connectionReturn` (green) | Solid | Function returns a struct |
| `uses` | `connectionUses` (gray) | Dashed (4,4) | Function uses struct as local var |

```javascript
// In drawAllConnections():
if (conn.type === 'uses') {
  ctx.setLineDash([4, 4]);  // Dashed line
}
// ... draw ...
ctx.setLineDash([]);  // Reset after drawing
```

## 8. Line Width

| State | Width |
|-------|-------|
| Normal | `LINE.strokeWidth` (1.5px) |
| Hovered (either endpoint is hovered entity) | `LINE.strokeWidthHover` (2.5px) |

```javascript
const isHighlighted = hovered === conn.source || hovered === conn.target;
const lineWidth = isHighlighted ? LINE.strokeWidthHover : LINE.strokeWidth;
```

## 9. Dimming and Highlighting

### Hover Dimming
When a block is hovered, non-connected lines dim:
```javascript
ctx.globalAlpha = isHighlighted ? 1.0 : (hovered ? 0.2 : 0.6);
```

| Scenario | Alpha |
|----------|-------|
| No hover active | 0.6 |
| Hover active, this line connects to hovered block | 1.0 |
| Hover active, this line doesn't connect to hovered block | 0.2 |

### Trace/Selection Dimming
When a block is selected, BFS finds the connected subgraph. Non-subgraph connections are nearly invisible:
```javascript
if (traceGraph && !isInTrace) {
  ctx.globalAlpha = 0.05;  // Nearly invisible
}
```

## 10. Line Constants (`cstruct-constants.js`)

```javascript
export const LINE = {
  strokeWidth: 1.5,
  strokeWidthHover: 2.5,
  controlPointOffset: 80,
  arrowSize: 6,
};
```

## 11. Anti-Patterns

- **Never draw connections outside cstruct-connections.js helpers** — all line rendering goes through the exported functions
- **Never cache anchor positions** — always compute from current block positions
- **Never store line paths in state** — they are derived data, recomputed every frame
- **Never subscribe to events in connections.js** — app.js calls drawing functions as part of the render pipeline
- **Never forget to reset `globalAlpha` and `setLineDash`** — always restore after drawing each connection
- **Never skip visibleSet filtering** — connections to filtered-out entities must not be drawn
