# Skill: Canvas Rendering Engine

## When to Use
Apply this skill when working on the rendering pipeline, viewport transforms, coordinate math, DPR handling, render scheduling, grid drawing, or canvas performance. This is the engine layer — how things get drawn on the canvas, not what they look like (see `cstruct-canvas-ui.md` for visual appearance).

---

## 1. Render Pipeline

Located in `cstruct-app.js`. The pipeline runs via `requestAnimationFrame` batching:

```javascript
scheduleRender()       // Coalesces multiple state changes into one frame
  → render()           // Called by rAF
    1. Clear canvas    // fillRect with background color
    2. Draw grid       // Dot grid aligned to viewport
    3. Apply transform // ctx.setTransform(zoom * dpr, 0, 0, zoom * dpr, panX * dpr, panY * dpr)
    4. Compute visibility // getVisibleEntities() from cstruct-search.js
    5. Compute trace   // getConnectedSubgraph() if entity selected
    6. Draw file containers // (by-file layout only) drawFileContainer() for visible groups
    7. Draw connections // All dependency lines (under blocks), filtered by visibleSet
    8. Draw blocks     // All struct/union/function blocks (over connections), filtered
```

### rAF Batching

```javascript
let rafId = null;

function scheduleRender() {
  if (rafId) return;           // Already scheduled — skip
  rafId = requestAnimationFrame(render);
}

function render() {
  rafId = null;                // Allow next schedule
  // ... full render pipeline
}
```

Multiple synchronous state changes (e.g., loadParseResult sets structs, unions, connections, etc.) coalesce into a single render frame.

### Event-Driven, Not Continuous

The canvas does NOT use a continuous animation loop. Rendering happens only in response to state changes:

```javascript
EventBus.on('cstructStateChanged', scheduleRender);
EventBus.on('cstructDataLoaded', onDataLoaded);
```

Exception: layout animation uses its own rAF loop during the 350ms transition, then stops.

### Visibility Filtering

The render pipeline calls `getVisibleEntities()` from `cstruct-search.js` to get a Set of entity names that should be visible (null = show all). Both block drawing and connection drawing skip filtered-out entities:

```javascript
const visibleSet = getVisibleEntities();
// Connections: skip if either endpoint is filtered out
if (visibleSet && (!visibleSet.has(conn.source) || !visibleSet.has(conn.target))) continue;
// Blocks: skip if filtered out
if (visibleSet && !visibleSet.has(entity.name)) continue;
```

## 2. Coordinate System

### Three Spaces

| Space | Used For | Units |
|-------|----------|-------|
| Screen | Mouse events, canvas CSS size | CSS pixels |
| Device | Canvas buffer, actual drawing | Physical pixels (screen × DPR) |
| Canvas | State positions, block coordinates | Logical units (zoom/pan independent) |

### Viewport Transform

```javascript
const viewport = { panX: 0, panY: 0, zoom: 1.0 };
```

Applied to the canvas context for drawing:
```javascript
ctx.setTransform(
  viewport.zoom * dpr, 0, 0, viewport.zoom * dpr,
  viewport.panX * dpr, viewport.panY * dpr,
);
```

### Screen-to-Canvas Conversion

Used for mouse events — convert screen pixel coordinates to canvas logical coordinates:

```javascript
function screenToCanvas(sx, sy) {
  const vp = getViewport();
  return {
    x: (sx - vp.panX) / vp.zoom,
    y: (sy - vp.panY) / vp.zoom,
  };
}
```

### Mouse Position from DOM Event

```javascript
function getMousePos(e) {
  const rect = canvas.getBoundingClientRect();
  return { x: e.clientX - rect.left, y: e.clientY - rect.top };
}
```

Flow: `DOM event → getMousePos() → screenToCanvas() → hit test in canvas space`

## 3. DPR (Device Pixel Ratio) Handling

The canvas buffer is sized at `width × DPR` for crisp rendering on high-DPI displays:

```javascript
function sizeCanvas() {
  const dpr = window.devicePixelRatio || 1;
  const w = parent.clientWidth;
  const h = parent.clientHeight;
  canvas.width = Math.round(w * dpr);    // Buffer size (physical pixels)
  canvas.height = Math.round(h * dpr);
  canvas.style.width = w + 'px';          // CSS size (logical pixels)
  canvas.style.height = h + 'px';
}
```

Every `ctx.setTransform()` call multiplies by `dpr` to map logical coordinates to physical pixels.

### Resize Handling

```javascript
const observer = new ResizeObserver(() => {
  sizeCanvas();
  scheduleRender();
});
observer.observe(canvas.parentElement);
```

## 4. Grid Drawing

Dot grid that scales with zoom. Spacing adapts to prevent dots from becoming too dense at low zoom:

```javascript
function drawGrid(colors, viewport, dpr) {
  const spacing = 20;
  const effectiveSpacing = spacing * Math.ceil(1 / Math.max(viewport.zoom, 0.25));
  // Compute visible rect in canvas coordinates
  // Draw dots only in visible area
}
```

Grid is drawn with the viewport transform applied (same transform as blocks/connections).

## 5. Zoom and Pan

### Zoom (mouse wheel)

Zoom centers on cursor position:

```javascript
function onWheel(e) {
  const factor = e.deltaY < 0 ? 1.1 : 0.9;
  const newZoom = Math.max(0.15, Math.min(5, vp.zoom * factor));
  setViewport({
    zoom: newZoom,
    panX: mouseX - canvasX * newZoom,    // Keep point under cursor fixed
    panY: mouseY - canvasY * newZoom,
  });
}
```

Zoom range: 0.15x to 5x.

### Pan (drag empty space)

```javascript
// On mouse down (no block hit):
isPanning = true;
panStart = screenPos;

// On mouse move:
setViewport({
  panX: vp.panX + (pos.x - panStart.x),
  panY: vp.panY + (pos.y - panStart.y),
});
panStart = pos;
```

### Auto-Fit Viewport

After layout changes, auto-fit zooms and pans to show all entities:

```javascript
function autoFit() {
  // 1. Compute bounding box of all entity positions
  // 2. Calculate zoom to fit content with 60px padding
  // 3. Center content in viewport
  const zoom = Math.min(1.5, Math.min(
    (w - pad * 2) / contentW,
    (h - pad * 2) / contentH
  ));
  setViewport({ zoom, panX, panY });
}
```

Max zoom capped at 1.5x to prevent over-zooming on small diagrams.

## 6. Subgraph Highlighting

When an entity is selected, BFS finds all connected entities:

```javascript
function getConnectedSubgraph(entityName) {
  // BFS through connections (both directions)
  // Returns: { entities: Set<string>, connections: Set<number> }
}
```

During render:
- Blocks not in subgraph: `ctx.globalAlpha = 0.15`
- Connections not in subgraph: `ctx.globalAlpha = 0.05`
- In-subgraph elements: normal or highlighted alpha

## 7. Hit Testing

### Block Hit Test

Linear scan over all entities, checking bounding box:
```javascript
function hitTestBlock(cx, cy) {
  for (const entity of entities) {
    const pos = getPosition(entity.name);
    const h = calculateBlockHeight(entity, isCollapsed(entity.name));
    if (cx >= pos.x && cx <= pos.x + pos.width && cy >= pos.y && cy <= pos.y + h) {
      return entity.name;
    }
  }
  return null;
}
```

### Field Hit Test

After finding the block, determines which field row the cursor is over:
```javascript
// In cstruct-blocks.js
function hitTestField(entity, pos, cx, cy, collapsed) {
  if (collapsed) return -1;
  const startY = pos.y + BLOCK.headerHeight;
  const idx = Math.floor((cy - startY) / BLOCK.fieldRowHeight);
  return (idx >= 0 && idx < entity.fields.length) ? idx : -1;
}
```

### Collapse Button Hit Test

Checks if click is on the triangle button (left 20px of header):
```javascript
function hitTestCollapseButton(pos, cx, cy) {
  const hh = BLOCK.headerHeight;
  return cx >= pos.x && cx <= pos.x + 20 && cy >= pos.y && cy <= pos.y + hh;
}
```

## 8. Mouse Interaction Summary

| Action | Behavior |
|--------|----------|
| Click block (not on triangle) | Select/deselect entity (subgraph highlight) |
| Click collapse triangle | Toggle collapsed state |
| Click empty space | Deselect |
| Double-click block | Open source file preview modal |
| Drag block | Move block position |
| Drag empty space | Pan viewport |
| Mouse wheel | Zoom (centered on cursor) |
| Hover block | Highlight connected lines, show field detail in sidebar |

## 9. Anti-Patterns

- **Never use `setInterval` for rendering** — event-driven only, not a continuous loop
- **Never draw before clearing** — always clear full canvas at start of render()
- **Never forget DPR** — all `setTransform` calls must multiply by `dpr`
- **Never cache viewport-dependent calculations** — recompute on every render
- **Never skip `scheduleRender()` after state change** — this is enforced by the event bus pattern
- **Never skip visibility check** — always check `visibleSet` before drawing blocks or connections
