---
description: Guarantee that connection lines always redraw when canvas state changes
globs: ["static/js/**/*.js"]
---

# Canvas Redraw Guarantee

## The Iron Rule

**Connection lines MUST be fully recalculated and redrawn whenever ANY of these events occur:**

- A table block is dragged/moved
- A table block is added to the canvas
- A table block is removed from the canvas
- A filter is applied, changed, or cleared
- The auto-sort/layout button is clicked
- The viewport is zoomed or panned
- The browser window is resized
- A connection/relationship is added or removed
- Table blocks are collapsed or expanded

## Implementation Requirements

1. **connections.js must export a `redrawAll()` function** that:
   - Reads current state via `getStateRef()` (no deep clone)
   - Recalculates ALL anchor points based on current block positions
   - Redraws ALL visible connection lines
   - Is safe to call at any time (idempotent)

2. **app.js owns the render pipeline**: `clear() → drawBackground() → redrawConnections() → redrawBlocks()`. All event subscriptions route through `scheduleRender()` which uses `requestAnimationFrame` batching to coalesce multiple synchronous events into one render frame.

3. **connections.js does NOT subscribe to events directly** — app.js calls `redrawAll()` as part of the `render()` pipeline. This prevents double-rendering.

4. **Never cache line positions** — always compute from current block positions.

5. **On filter change**: `resolveConnectionStyle()` checks `activeFilters` — connections to filtered-out tables return `null` (hidden) or dimmed style. Blocks check filters in `getBlockVisualState()`.

6. **On trace**: `buildTraceEdgeSet()` creates a Set of traced edges for O(1) lookup. Non-traced connections return `null` (not drawn). Traced connections render as animated red dashed lines.

## Anti-Patterns (NEVER DO)

- Never skip redraw for "performance" without a trailing-edge guarantee
- Never assume previous line positions are still valid
- Never draw lines in a module other than connections.js
- Never store computed line paths in state — they are derived data
