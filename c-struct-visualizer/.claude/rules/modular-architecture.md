# Modular Architecture

## Module Rules

### 1. Single Responsibility
Each JS module handles ONE concern:
- `cstruct-state.js` — state only (getters + mutators + events)
- `cstruct-blocks.js` — block drawing only (no state, no events)
- `cstruct-connections.js` — connection drawing only (no state, no events)
- `cstruct-constants.js` — design tokens only (no logic)
- `cstruct-upload.js` — file upload only
- `cstruct-app.js` — orchestration (render pipeline, mouse, layout, sidebar)

### 2. Communication: Event Bus Only
Modules communicate through:
- The event bus (`events.js`) — for async notifications
- The state store (`cstruct-state.js`) — for data reads
- Direct function calls — only from app.js to drawing modules (blocks, connections)

Never import one feature module into another directly.

### 3. State Is the Single Source of Truth
- All data lives in `cstruct-state.js`
- UI reads from state via getters, never caches its own copy
- Mutations go through exported functions only
- Every mutation emits `cstructStateChanged`
- Derived data (line paths, filtered lists) is never stored in state

### 4. Stateless Drawing Functions
`cstruct-blocks.js` and `cstruct-connections.js` are pure:
- They receive data as arguments
- They draw to canvas as side effect
- They import only from `cstruct-constants.js`
- They never import state, events, or other modules

### 5. App.js Is the Central Orchestrator
- Subscribes to all events
- Owns the render pipeline: `scheduleRender()` → `render()`
- Calls drawing functions from blocks.js and connections.js
- Manages mouse interaction and layout algorithms
- No other module calls render functions directly

### 6. Backend Is Data-Only
- `c_parser.py` — pure functions, no Flask imports
- `cstruct_routes.py` — thin route layer, delegates to c_parser.py
- `app.py` — registers blueprints, serves pages
- Backend returns JSON, never HTML fragments
- All rendering happens client-side

### 7. Event Naming
All cstruct events are prefixed with `cstruct`:
- `cstructDataLoaded` — parse result loaded
- `cstructStateChanged` — any state mutation
- `cstructEntitySelected` — entity clicked
- `cstructBlockToggled` — block collapsed/expanded
- `cstructArchChanged` — architecture selector changed

### 8. Import Hierarchy (no circular dependencies)
```
events.js        (shared, no imports)
cstruct-constants.js  (no imports)
  ↑
cstruct-blocks.js     (imports: constants)
cstruct-connections.js (imports: constants)
  ↑
cstruct-state.js      (imports: events)
  ↑
cstruct-upload.js     (imports: events, state)
  ↑
cstruct-app.js        (imports: everything above)
```
