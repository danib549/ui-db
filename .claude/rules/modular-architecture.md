---
description: Enforce modular architecture for the DB Diagram Visualizer project
globs: ["**/*.py", "**/*.js", "**/*.html", "**/*.css"]
---

## Module Rules

1. **Single Responsibility**: Each JS module handles ONE concern. Never mix rendering logic with data processing.

2. **No Direct Cross-Module Calls**: Modules communicate ONLY through:
   - The event bus (events.js)
   - The state store (state.js)
   - Never import one UI module into another directly.

3. **State is the Single Source of Truth**:
   - All data lives in state.js
   - UI reads from state, never caches its own copy
   - Mutations go through state functions only

4. **Connection Lines MUST Redraw on Every State Change**:
   - app.js owns the render pipeline: `clear() → drawBackground() → redrawConnections() → redrawBlocks()`
   - connections.js does NOT subscribe to events directly — app.js calls it via `render()`
   - All event subscriptions route through `scheduleRender()` (rAF-batched) in app.js
   - The `redrawAll()` function must be idempotent — safe to call multiple times
   - NEVER skip a redraw. NEVER assume lines are still correct.

5. **Python Backend is Data-Only**:
   - Backend returns JSON, never HTML fragments
   - All rendering happens client-side
   - Backend handles: CSV parsing, key detection, relationship analysis
   - Frontend handles: all UI, canvas, interaction

6. **CSS Separation**:
   - No inline styles in JS (use CSS classes)
   - Canvas elements styled via JS (they're not DOM elements) but use constants from a theme object

7. **Event-Driven Architecture**:
   - events.js provides publish/subscribe
   - Events: `tableAdded`, `tableRemoved`, `tableMoved`, `tableDragging`, `filterChanged`, `layoutChanged`, `connectionAdded`, `connectionRemoved`, `viewportChanged`, `stateReset`, `blockCollapsed`, `blockExpanded`, `searchResultsReady`, `searchCleared`, `traceResultsReady`, `traceRequested`, `panToTable`, `stateChanged`
   - app.js is the central render orchestrator — subscribes to events and calls `scheduleRender()`
   - Feature modules (search.js, trace.js, filters.js) subscribe to their own domain events

8. **Shared Constants and Utilities**:
   - constants.js is the single source of truth for layout dimensions (ROW_HEIGHT, HEADER_HEIGHT, etc.), colors (KEY_COLORS, CONNECTION_COLORS, BLOCK_COLORS), and shared helpers (calculateBlockHeight)
   - utils.js holds shared utilities (escapeHtml)
   - NEVER duplicate constants across files — import from constants.js

9. **State Access Patterns**:
   - Use `getStateRef()` for read-only access in render pipeline (no deep clone)
   - Use `getState()` or `exportState()` only when a snapshot/clone is needed (undo stack, export)
   - Use specific getters (`getViewport()`, `getTables()`, `getPositions()`) when only one field is needed

## Backend Module Rules

1. **Each Python file handles one domain**: csv_handler.py does CSV only, key_detector.py does key detection only.
2. **app.py is thin**: Only route definitions, delegates to backend modules.
3. **No frontend logic in Python**: Never generate HTML or JS from Python.

## Testing Rules

1. Each module should be testable in isolation.
2. State changes should be verifiable without rendering.
3. Backend functions should have unit tests.
