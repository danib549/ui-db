# C Struct Visualizer

A web-based interactive tool that parses C/C++ source files and visualizes struct, union, enum, and function definitions on an HTML5 Canvas. Shows memory layouts with field offsets, sizes, padding, alignment, and type dependencies.

## Project Overview
- **Backend**: Python (Flask) + libclang for AST parsing
- **Frontend**: Vanilla JS (ES6 modules) + HTML5 Canvas for interactive visualization
- **Input**: .c/.h files (single or folder upload, drag-and-drop)
- **Output**: Interactive canvas showing struct/union/function blocks with memory layout and dependency connections

## Tech Stack
- `flask` — HTTP server, route layer
- `libclang` (via `clang.cindex`) — C/C++ AST parsing, field offsets, sizes, alignment
- HTML5 Canvas 2D — all rendering
- ES6 modules — frontend architecture, no bundler

## Key Features
- Multi-file parsing with folder upload (recursive directory walking)
- Multi-architecture support: ARM (32-bit), SPARC/LEON3, Linux x86_64, Windows x64
- Memory layout: field offsets, sizes, padding (head/inter-field/tail), bitfields, packed detection
- Dependency graph: nested structs, function params, return types, local variable usage
- 4 layout algorithms: top-down, left-right, force-directed, grid (with animated transitions)
- Interactive: drag blocks, pan, zoom, collapse/expand, click-to-select subgraph
- Field detail on hover in sidebar
- Dark mode with persistent theme
- Live re-parse on architecture change

## Project Structure

```
c-struct-visualizer/
├── app.py                     # Flask entry point, blueprint registration, index route
├── cstruct_routes.py          # /api/cstruct/* endpoints (upload, targets)
├── c_parser.py                # Core libclang parsing (pure functions, no HTTP)
├── cstruct_headers/           # Bundled C headers (stdbool.h, stdint.h, etc.)
├── requirements.txt
├── templates/
│   └── index.html             # Single-page app
└── static/
    ├── css/
    │   ├── styles.css         # Base layout
    │   ├── dark-mode.css      # Dark mode overrides
    │   └── cstruct.css        # Type-specific colors
    └── js/
        ├── events.js          # Pub/sub event bus (shared with parent project)
        ├── utils.js           # Shared utilities
        └── cstruct/           # All visualizer modules
            ├── cstruct-app.js       # Orchestrator: render loop, mouse, layout, sidebar
            ├── cstruct-state.js     # Single source of truth (getters + mutators)
            ├── cstruct-blocks.js    # Canvas drawing: struct/union/function blocks
            ├── cstruct-connections.js  # Bezier connection lines + arrows
            ├── cstruct-constants.js    # Colors, dimensions, badge shapes
            └── cstruct-upload.js       # File/folder upload + drag-drop
```

## Data Flow

```
.c/.h files → cstruct-upload.js → POST /api/cstruct/upload
  → cstruct_routes.py → c_parser.py (libclang AST) → JSON response
  → cstruct-state.js (loadParseResult) → EventBus('cstructDataLoaded')
  → cstruct-app.js (applyLayout + render) → Canvas
```

## Backend Modules

- `c_parser.py` — Pure functions only (no Flask). Writes files to temp dir, creates `__main__.c` that includes all files, parses with libclang. Extracts structs, unions, enums, functions, connections, typedefs. Computes field offsets, padding, bitfields, packed detection. Builds dependency graph (nested, param, return, uses).
- `cstruct_routes.py` — Flask Blueprint at `/api/cstruct`. Two endpoints: `POST /upload` and `GET /targets`.
- `app.py` — Thin: registers blueprint, serves index.html, fixes MIME types.

## Frontend Modules

- `cstruct-app.js` — Orchestrator. Owns canvas, render pipeline (clear → grid → connections → blocks), mouse handlers (drag, pan, zoom, click, double-click), 4 layout algorithms, sidebar DOM updates, animation system. Subscribes to EventBus, calls `scheduleRender()` via rAF.
- `cstruct-state.js` — Single source of truth. Holds structs, unions, functions, typedefs, enums, connections, positions, viewport, collapsed, hovered/selected entity. All mutations emit `cstructStateChanged`. No direct state object access from other modules.
- `cstruct-blocks.js` — Stateless drawing functions. `drawBlock()` renders struct/union/function blocks with header, fields, badges, padding stripes. `hitTestField()` for hover detection.
- `cstruct-connections.js` — Stateless drawing helpers. `chooseSides()`, `calculateAnchor()`, `drawBezierConnection()`, `drawArrow()`. No state imports — called by cstruct-app.js.
- `cstruct-constants.js` — Design tokens. Block dimensions, category colors (light + dark), canvas colors (light + dark), line constants, badge shape mapping.
- `cstruct-upload.js` — File upload. Drag-drop (files or folders), file picker, folder picker. Recursive directory walking via WebKit API. Caches file map for re-parse on arch change.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Serve index.html |
| `/api/cstruct/upload` | POST | Parse uploaded .c/.h files. Accepts `files[]` (multipart) + `target` (arch key). Returns JSON with structs, unions, functions, enums, connections, warnings, target_info. |
| `/api/cstruct/targets` | GET | List available target architectures with metadata. |

## Event Bus Events

| Event | Payload | Trigger |
|-------|---------|---------|
| `cstructDataLoaded` | `{ count }` | Parse result loaded into state |
| `cstructStateChanged` | `{ key }` | Any state mutation |
| `cstructEntitySelected` | `{ name }` | Entity selected/deselected |
| `cstructBlockToggled` | `{ name, collapsed }` | Block collapsed/expanded |
| `cstructArchChanged` | `{ arch }` | Architecture selector changed |

## State Shape

```javascript
{
  structs: [],        // [{name, displayName, totalSize, alignment, packed, isUnion:false, fields:[...]}]
  unions: [],         // [{name, displayName, totalSize, alignment, packed, isUnion:true, fields:[...]}]
  functions: [],      // [{name, displayName, returnType, isFunction:true, params:[...], fields:[...]}]
  typedefs: {},       // {alias: canonical_name}
  enums: [],          // [{name, values:[{name, value}]}]
  connections: [],    // [{source, target, type:'nested'|'param'|'return'|'uses', field}]
  positions: {},      // {entityName: {x, y, width, height}}
  viewport: { panX, panY, zoom },
  collapsed: {},      // {entityName: true}
  hoveredEntity: null,
  hoveredField: null, // {entity, fieldIndex}
  selectedEntity: null,
  targetArch: 'arm',
  endianness: 'little',
  warnings: [],
}
```

## Target Architectures

| Key | Triple | Pointer Size | Endianness |
|-----|--------|-------------|------------|
| `arm` | `arm-none-eabi` | 4 bytes | little |
| `sparc` | `sparc-unknown-elf` | 4 bytes | big |
| `linux_x64` | `x86_64-unknown-linux-gnu` | 8 bytes | little |
| `win_x64` | `x86_64-pc-windows-msvc` | 8 bytes | little |

## Skills

### System-Level
- `.claude/skills/c-struct-visualizer.md` — Full system lifecycle: upload → parse → visualize. End-to-end data flow, architecture decisions, feature planning.

### Backend
- `.claude/skills/c-parser-engine.md` — libclang AST parsing: struct/union/enum/function extraction, field offsets, padding, bitfields, type categorization, multi-file include resolution, target architectures.

### Frontend — Canvas Engine
- `.claude/skills/cstruct-canvas-engine.md` — Render pipeline, viewport transforms, coordinate math, rAF batching, DPR handling, grid drawing, performance.
- `.claude/skills/cstruct-canvas-ui.md` — Block rendering: struct/union/function blocks, headers, field rows, badges, padding visualization, colors, dark mode theming.
- `.claude/skills/cstruct-connections.md` — Connection line rendering: Bezier curves, anchor calculation, side selection, arrows, connection types, subgraph highlighting, dimming.
- `.claude/skills/cstruct-layout-algorithms.md` — Layout: top-down, left-right, force-directed, grid, dependency graph building, animated transitions, auto-fit viewport.

### Frontend — Interaction
- `.claude/skills/cstruct-upload-system.md` — File/folder upload: drag-drop, WebKit directory walking, file picker, re-parse on arch change, status feedback UI.

## Rules
- `.claude/rules/canvas-redraw-guarantee.md` — Connections redraw on every state change. No caching, no skipping.
- `.claude/rules/modular-architecture.md` — Module boundaries, event-driven communication, state-driven UI.
- `.claude/rules/code-style.md` — Naming conventions, file structure, style.

---

## LLM Coding Rules

### Default Mode: Plan First
- **ALWAYS enter plan mode before writing code.** Think, then do.
- For any change touching 2+ files or adding new behavior: outline the plan, list affected files, and get user confirmation before coding.
- For single-line fixes or trivial edits: skip plan, just do it.

### Read Before Write
- NEVER edit a file you haven't read in this conversation.
- Before modifying a function, read it AND its callers.
- Before accessing state, read `cstruct-state.js`. Before emitting events, read `events.js`.
- Grep for a function/variable before assuming it exists.

### One Change, One Purpose
- Each edit does ONE thing. Don't bundle unrelated fixes.
- Change files in dependency order: state → events → logic → UI → connections redraw.
- Never leave the codebase in a half-changed state between edits.

### Keep It Simple and Clean
- Functions do one thing, describable in one sentence without "and".
- Max 40 lines per function. If longer, split by responsibility.
- No dead code, no commented-out blocks, no "for later" params.
- Early returns for guard clauses. No deep nesting.
- Validate at boundaries (user input, API responses). Trust internal code.

### Import/Export Discipline
- Every `import` must match a real `export`. Verify after adding or removing functions.
- After deleting a function, find and update all import sites.

### State Is Sacred
- All mutations go through `cstruct-state.js` functions. Never modify state directly.
- Never store derived data in state (computed line paths, filtered lists).
- Every state change must emit an event. No silent mutations.

---

## Verification Before Done

1. **Syntax check** — no typos, no missing brackets, no broken imports.
2. **Read the diff** — re-read every changed file. Does each edit do what was intended?
3. **Cross-file consistency** — changed a function signature? Update all call sites. Added a state key? Initialize it. Added an event? Something must listen.
4. **The Iron Rule** — does every state change trigger `scheduleRender()` → render → connections redraw?
5. **Edge cases** — 0 entities? 1 entity? No connections? All collapsed?
6. **No dead code** — no unused variables, no orphan imports, no leftover console.logs.
7. **Style match** — naming, indentation, and patterns match the rest of the codebase.
