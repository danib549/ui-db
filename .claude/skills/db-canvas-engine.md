# Skill: DB Canvas Rendering Engine

## When to Use
Apply this skill when working on the rendering pipeline, coordinate transforms, viewport management, redraw orchestration, or performance tuning of the diagram canvas. This covers the engine layer — how things get drawn, not what they look like.

---

## 1. Rendering Pipeline

### Layer System (bottom to top)

The canvas renders in four ordered layers. Each layer is conceptually independent and can redraw without affecting others, though connection lines and blocks often redraw together.

| Layer | Z-Order | Contents | Redraw Trigger |
|-------|---------|----------|----------------|
| Background | 0 | Dot grid, canvas fill | Viewport change (pan/zoom) |
| Connections | 1 | All relationship lines, cardinality markers | ANY state change (the Iron Rule) |
| Blocks | 2 | Table cards with headers and column rows | Position, visibility, or content change |
| Overlay | 3 | Selection marquee, hover tooltips, drag ghost | User interaction |

### Event-Driven Redraw Pattern

The engine uses event-driven rendering, not a continuous animation loop. Redraws happen in response to state changes, routed through the event bus.

```javascript
// In the render orchestrator — subscribe to state changes
import { EventBus } from './events.js';
import { getState } from './state.js';
import { redrawAll as redrawConnections } from './connections.js';
import { redrawAll as redrawBlocks } from './blocks.js';

EventBus.on('stateChanged', (changes) => {
  // Connections layer redraws on ANY state change that could affect lines
  if (changes.affects('positions', 'visibility', 'filters', 'viewport', 'connections', 'collapsed')) {
    redrawConnections();
  }

  // Blocks layer redraws on position/visibility/content changes
  if (changes.affects('positions', 'visibility', 'viewport', 'tables', 'collapsed')) {
    redrawBlocks();
  }
});
```

### Render Sequence for a Full Frame

```
1. Clear the relevant canvas layer(s)
2. Apply viewport transform (translate for pan, scale for zoom)
3. Draw background grid (aligned to viewport)
4. Draw connection lines (from current state)
5. Draw table blocks (from current state)
6. Draw overlay elements (selection, hover)
7. Restore canvas transform
```

---

## 2. The Iron Rule

**Connection lines MUST be fully recalculated and redrawn on EVERY state change. No exceptions. No caching.**

### Trigger Events (exhaustive list)

- Table block dragged/moved
- Table block added to the canvas
- Table block removed from the canvas
- Filter applied, changed, or cleared
- Auto-sort/layout triggered
- Viewport zoomed or panned
- Browser window resized
- Connection/relationship added or removed
- Table block collapsed or expanded

### Why No Caching

Block positions change during drag. Filters change visibility. Collapse changes anchor points. Zoom changes pixel positions. There is no reliable way to know which cached line is still valid — so we never cache. The cost of a full recalc is lower than the cost of a stale line bug.

### Enforcement Pattern

Every state mutation function must either:
1. Call `connections.redrawAll()` directly, OR
2. Emit a `stateChanged` event that a listener routes to `redrawAll()`

Both paths are acceptable. What is NOT acceptable is a state change that silently skips redraw.

```javascript
// In state.js — every mutation emits
export function moveBlock(tableId, newPos) {
  state.positions[tableId] = newPos;
  EventBus.emit('stateChanged', { affects: () => true }); // always triggers redraw
}
```

---

## 3. Coordinate System

### Canvas Coordinates

All positions are stored as `{x, y}` objects in canvas space (the logical coordinate system, independent of zoom/pan).

```javascript
// A block position in state — always canvas coordinates
{ x: 400, y: 250 }

// An anchor point for a connection line — canvas coordinates
{ x: 600, y: 275 }
```

### Viewport Transform

The viewport is defined by a pan offset and a zoom level. These transform canvas coordinates into screen (pixel) coordinates.

```javascript
// Viewport state
const viewport = {
  panX: 0,    // horizontal offset in screen pixels
  panY: 0,    // vertical offset in screen pixels
  zoom: 1.0   // scale factor (1.0 = 100%)
};
```

### Screen-to-Canvas Conversion

Use this when handling mouse events — the mouse gives screen coordinates, but state stores canvas coordinates.

```javascript
function screenToCanvas(screenX, screenY, viewport) {
  return {
    x: (screenX - viewport.panX) / viewport.zoom,
    y: (screenY - viewport.panY) / viewport.zoom
  };
}
```

### Canvas-to-Screen Conversion

Use this when drawing — state gives canvas coordinates, but the canvas API needs screen pixel positions.

```javascript
function canvasToScreen(canvasX, canvasY, viewport) {
  return {
    x: canvasX * viewport.zoom + viewport.panX,
    y: canvasY * viewport.zoom + viewport.panY
  };
}
```

### Applying the Transform to the Canvas Context

Instead of converting every point manually, apply the transform once at the start of each frame.

```javascript
function applyViewportTransform(ctx, viewport) {
  ctx.setTransform(viewport.zoom, 0, 0, viewport.zoom, viewport.panX, viewport.panY);
}

function resetTransform(ctx) {
  ctx.setTransform(1, 0, 0, 1, 0, 0);
}

// Usage in render loop
applyViewportTransform(ctx, viewport);
// ... draw everything in canvas coordinates ...
resetTransform(ctx);
```

---

## 4. Performance

### Trailing-Edge Debounce

During rapid events (drag, scroll-zoom), debounce the redraw — but ALWAYS execute the final one. Use trailing-edge exclusively.

```javascript
function trailingDebounce(fn, delay = 16) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

// Ensures the last drag position always triggers a full redraw
const debouncedRedraw = trailingDebounce(connections.redrawAll, 16);
```

**16ms = one frame at 60fps.** This means at most one redraw per frame during continuous drag, and the final position is always drawn.

### requestAnimationFrame Batching

When multiple state changes fire in the same synchronous block, batch them into a single rAF.

```javascript
let redrawScheduled = false;

function scheduleRedraw() {
  if (redrawScheduled) return;
  redrawScheduled = true;
  requestAnimationFrame(() => {
    connections.redrawAll();
    blocks.redrawAll();
    redrawScheduled = false;
  });
}
```

### Spatial Indexing for Hit Detection

For click and hover detection, avoid checking every block and every line. Use a grid-based spatial index.

```javascript
// Divide canvas into cells (e.g., 200x200px each)
// Each cell stores references to blocks/connections that overlap it
// On click: convert screen coords to canvas coords, find the cell, check only its contents

function getCellKey(x, y, cellSize = 200) {
  return `${Math.floor(x / cellSize)},${Math.floor(y / cellSize)}`;
}

function getBlockCells(block, cellSize = 200) {
  const cells = [];
  const startCol = Math.floor(block.x / cellSize);
  const endCol = Math.floor((block.x + block.width) / cellSize);
  const startRow = Math.floor(block.y / cellSize);
  const endRow = Math.floor((block.y + block.height) / cellSize);
  for (let col = startCol; col <= endCol; col++) {
    for (let row = startRow; row <= endRow; row++) {
      cells.push(`${col},${row}`);
    }
  }
  return cells;
}
```

Rebuild the spatial index after layout changes. Do NOT use it during drag (positions change too fast).

### Frustum Culling

Skip drawing elements entirely outside the visible viewport. Compute the visible rect in canvas coordinates and test each element against it.

```javascript
function getVisibleRect(canvas, viewport) {
  return {
    left: -viewport.panX / viewport.zoom,
    top: -viewport.panY / viewport.zoom,
    right: (canvas.width - viewport.panX) / viewport.zoom,
    bottom: (canvas.height - viewport.panY) / viewport.zoom
  };
}

function isBlockVisible(block, visibleRect) {
  return !(block.x + block.width < visibleRect.left ||
           block.x > visibleRect.right ||
           block.y + block.height < visibleRect.top ||
           block.y > visibleRect.bottom);
}

// For connection lines: check if EITHER endpoint's block is visible,
// or if the line's bounding box intersects the viewport
```

---

## 5. The redrawAll() Contract

`connections.redrawAll()` is the most important function in the rendering engine. It must follow this exact sequence:

```javascript
// In connections.js
export function redrawAll() {
  const { positions, connections, filters, collapsed, viewport } = getState();

  // 1. Clear all existing lines
  clearConnectionLayer();

  // 2. For each connection in state:
  for (const conn of connections) {
    const sourceBlock = positions[conn.source.table];
    const targetBlock = positions[conn.target.table];

    // 3. Check visibility — skip if either block is hidden (not dimmed, HIDDEN)
    if (!isVisible(conn.source.table, filters) || !isVisible(conn.target.table, filters)) {
      continue;
    }

    // 4. Calculate anchor points from CURRENT block positions
    const sourceAnchor = calculateAnchor(sourceBlock, conn.source.column, collapsed[conn.source.table]);
    const targetAnchor = calculateAnchor(targetBlock, conn.target.column, collapsed[conn.target.table]);

    // 5. Compute bezier control points
    const controlPoints = computeBezierControls(sourceAnchor, targetAnchor);

    // 6. Determine style (solid vs dashed, color, opacity)
    const style = getLineStyle(conn, filters);

    // 7. Draw the line
    drawBezierLine(ctx, sourceAnchor, targetAnchor, controlPoints, style);

    // 8. Draw cardinality indicators at endpoints
    drawCardinalityMarkers(ctx, sourceAnchor, targetAnchor, conn.type);
  }
}
```

### Contract Rules

- **Idempotent** — calling it 1 time or 100 times in a row produces the same visual result.
- **No arguments** — it reads everything from state. No caller needs to tell it what changed.
- **No return value** — it draws to the canvas as a side effect.
- **No caching** — every call recomputes from scratch. Previous anchor points are never reused.
- **Safe to call at any time** — during drag, after delete, on resize, on startup.

### Anchor Point Calculation

```javascript
function calculateAnchor(blockPos, columnName, isCollapsed) {
  if (isCollapsed) {
    // Collapsed: anchor at the block's vertical center, left or right edge
    return {
      x: blockPos.x + blockPos.width / 2,
      y: blockPos.y + HEADER_HEIGHT / 2
    };
  }

  // Expanded: anchor at the column row's vertical center
  const rowIndex = getColumnRowIndex(blockPos.tableId, columnName);
  const rowY = blockPos.y + HEADER_HEIGHT + rowIndex * ROW_HEIGHT + ROW_HEIGHT / 2;

  // Choose left or right edge based on which side the other block is on
  // (determined by caller comparing source/target x positions)
  return { x: blockPos.x, y: rowY }; // or { x: blockPos.x + blockPos.width, y: rowY }
}
```

### Bezier Control Points

```javascript
function computeBezierControls(source, target) {
  const distance = Math.abs(target.x - source.x);
  const offset = Math.min(100, distance * 0.4);

  return {
    cp1: { x: source.x + offset, y: source.y },
    cp2: { x: target.x - offset, y: target.y }
  };
}
```

---

## 6. State Integration

### Position Registry

Block positions live in `state.js`. The rendering engine reads them — never writes them directly.

```javascript
// state.js
const state = {
  positions: {
    'users':    { x: 100, y: 50,  width: 240, height: 180, tableId: 'users' },
    'orders':   { x: 450, y: 50,  width: 260, height: 220, tableId: 'orders' },
    'products': { x: 450, y: 320, width: 240, height: 160, tableId: 'products' }
  }
};
```

### Connection Registry

Connections are data from the backend (key detection + relationship analysis). They describe what is connected, not how to draw it.

```javascript
// state.js
const state = {
  connections: [
    {
      source: { table: 'orders', column: 'user_id' },
      target: { table: 'users', column: 'id' },
      type: 'many-to-one'
    },
    {
      source: { table: 'orders', column: 'product_id' },
      target: { table: 'products', column: 'id' },
      type: 'many-to-one'
    }
  ]
};
```

### Every Mutation Triggers Redraw

The state module guarantees this. No mutation function returns without emitting a `stateChanged` event.

| Mutation | State Keys Changed | Redraw? |
|----------|-------------------|---------|
| `moveBlock(id, pos)` | `positions` | Yes |
| `addTable(table)` | `tables`, `positions` | Yes |
| `removeTable(id)` | `tables`, `positions`, `connections` | Yes |
| `applyFilter(filter)` | `filters` | Yes |
| `applyLayout(algo)` | `positions` (all blocks) | Yes |
| `toggleCollapse(id)` | `collapsed` | Yes |
| `setViewport(pan, zoom)` | `viewport` | Yes |
| `addConnection(conn)` | `connections` | Yes |
| `removeConnection(conn)` | `connections` | Yes |

### Single Source of Truth

The rendering engine never maintains its own copy of positions, connections, or filters. It reads from `getState()` on every redraw. If state is stale, the bug is in the mutation — never in the renderer.

---

## 7. Anti-Patterns

### Never cache line positions between redraws
Line paths are derived data. Storing them means they can become stale. Recompute on every `redrawAll()`.

### Never skip redraw without a trailing-edge guarantee
Debouncing is fine. Throttling is fine. But the LAST event in a burst MUST produce a redraw. Use trailing-edge debounce exclusively.

```javascript
// WRONG: leading-edge throttle can skip the final position
let lastCall = 0;
function throttledRedraw() {
  if (Date.now() - lastCall < 16) return; // skips final!
  lastCall = Date.now();
  redrawAll();
}

// RIGHT: trailing-edge debounce always fires the last one
const debouncedRedraw = trailingDebounce(redrawAll, 16);
```

### Never draw lines outside connections.js
All line rendering logic lives in `connections.js`. Other modules (blocks, overlay, interaction handlers) must not draw lines, even "temporary" ones.

### Never store computed paths in state
Bezier control points, anchor positions, and line bounding boxes are computed fresh each frame. They do not belong in `state.js`.

### Never use setInterval for rendering
The engine is event-driven. Rendering happens in response to state changes, not on a timer. A `setInterval` loop wastes frames when nothing changes and may miss frames when things do.

### Never assume previous anchor points are still valid
After ANY state change — even one that seems unrelated — anchor points may have shifted. A filter change can collapse a block; a layout change moves everything. Always recalculate.
