# Skill: C Struct Visualizer — System Design and Lifecycle

## When to Use
Apply this skill for high-level design decisions, new features, understanding the end-to-end pipeline, or planning changes that span backend and frontend. This is the top-level skill — start here, then drill into specific skills as needed.

---

## 1. System Architecture

```
User uploads .c/.h files
      ↓
[Frontend: cstruct-upload.js]
  Drag-drop / file picker / folder picker
  Recursive directory walking (WebKit API)
  FormData with files[] + target architecture
      ↓
[HTTP POST /api/cstruct/upload]
      ↓
[Backend: cstruct_routes.py]
  Validates files, delegates to c_parser.py
  Attaches fileContents to response (for source preview modal)
      ↓
[Backend: c_parser.py]
  1. Write files to temp directory (preserving structure)
  2. Create __main__.c that #includes all files
  3. Set up libclang args: -target <triple> -std=c11 -I <headers>
  4. Parse with Index.parse() + PARSE_DETAILED_PROCESSING_RECORD
  5. Walk AST: extract structs, unions, enums, functions
  6. Compute: field offsets, sizes, padding, bitfields, packed
  7. Build connection graph: nested, param, return, uses
  8. Track source file + line for each entity (via path_map)
  9. Build reverse typedef map for clean display names
  10. Tag stdlib entities (isStdlib flag) for frontend filtering
  11. Return JSON result
      ↓
[Frontend: cstruct-state.js]
  loadParseResult() → populates state (incl. fileContents) → emits cstructDataLoaded
      ↓
[Frontend: cstruct-search.js]
  buildSearchIndex() → show toolbar → update file filter dropdown
      ↓
[Frontend: cstruct-app.js]
  onDataLoaded() → applyLayout() → autoFit() → scheduleRender()
      ↓
[Canvas Render Pipeline]
  clear → grid → viewport transform → file containers → connections → blocks
      ↓
[Interactive Canvas]
  Drag, pan, zoom, click-select, dbl-click source preview, hover detail
  Collapse/expand via triangle button in header
```

## 2. Module Dependency Graph

```
                 events.js (shared event bus)
                     ↑
        ┌────────────┼────────────────┐
        ↑            ↑                ↑
  cstruct-state.js   ↑          cstruct-upload.js
        ↑            ↑                ↑
        ├────┐       ↑       ┌────────┘
        ↑    ↑       ↑       ↑
        ↑  cstruct-search.js ↑
        ↑    ↑       ↑       ↑
        └────┤       ↑       ↑
             ↑       ↑       ↑
         cstruct-modal.js    ↑
             ↑       ↑       ↑
             └───┐   ↑   ┌───┘
                 ↑   ↑   ↑
             cstruct-app.js (orchestrator)
             ↑       ↑       ↑
        blocks.js  connections.js  constants.js
```

- **events.js** — shared infrastructure, no cstruct imports
- **cstruct-state.js** — imports only events.js
- **cstruct-constants.js** — no imports (pure data)
- **cstruct-connections.js** — imports only constants
- **cstruct-blocks.js** — imports only constants
- **cstruct-upload.js** — imports events.js + state.js
- **cstruct-modal.js** — imports state.js (getEntity, getFileContent)
- **cstruct-search.js** — imports events.js + state.js (filter/search state getters+mutators)
- **cstruct-app.js** — imports everything, orchestrates all

## 3. Adding a New Feature — Checklist

1. **Where does data come from?** Backend (new c_parser.py output)? Frontend only (UI state)?
2. **Does it need new state?** Add to `cstruct-state.js` with getter + mutator + event emit
3. **Does it need new parsing?** Add to `c_parser.py` → update `_walk_cursor()` or specific `_process_*()` function
4. **Does it need new API?** Add endpoint to `cstruct_routes.py`
5. **Does it change rendering?** Update blocks/connections in `cstruct-app.js` render pipeline
6. **Does it need new constants?** Add to `cstruct-constants.js`
7. **Does it need sidebar UI?** Update `cstruct-app.js` sidebar helpers or HTML template
8. **Does it need search/filter?** Update `cstruct-search.js` (search index, filter logic, toolbar DOM)
9. **Iron Rule check:** Does every new state change still trigger `scheduleRender()`?

## 4. JSON Response Shape

The backend returns this JSON from `/api/cstruct/upload`:

```json
{
  "structs": [
    {
      "name": "sensor_data",
      "displayName": "sensor_data_t",
      "sourceFile": "sensors/data.h",
      "sourceLine": 12,
      "totalSize": 24,
      "alignment": 4,
      "packed": false,
      "isUnion": false,
      "isStdlib": false,
      "fields": [
        {
          "name": "id",
          "type": "uint32_t",
          "offset": 0,
          "size": 4,
          "bitOffset": 0,
          "bitSize": null,
          "category": "integer"
        },
        {
          "name": "__pad_1",
          "type": "(padding)",
          "offset": 4,
          "size": 4,
          "bitOffset": null,
          "bitSize": null,
          "category": "padding"
        }
      ]
    }
  ],
  "unions": [],
  "typedefs": { "sensor_data_t": "sensor_data" },
  "enums": [{ "name": "status", "values": [{ "name": "OK", "value": 0 }] }],
  "functions": [
    {
      "name": "read_sensor",
      "displayName": "read_sensor",
      "sourceFile": "sensors/api.c",
      "sourceLine": 45,
      "returnType": "sensor_data_t *",
      "returnStruct": "sensor_data",
      "isPointerReturn": true,
      "isStdlib": false,
      "params": [{ "name": "id", "type": "uint32_t", "refStruct": null, "isPointer": false, "category": "integer" }],
      "bodyStructRefs": []
    }
  ],
  "connections": [
    { "source": "read_sensor", "target": "sensor_data", "type": "return", "field": null }
  ],
  "warnings": ["Missing include: config.h — upload this file for complete parsing"],
  "target_info": {
    "key": "arm",
    "label": "ARM (32-bit)",
    "endianness": "little",
    "pointer_size": 4
  }
}
```

The route handler (`cstruct_routes.py`) also attaches `fileContents: {filename: sourceCodeString}` to the response for the source preview modal.

## 5. Connection Types

| Type | Source | Target | Meaning | Visual |
|------|--------|--------|---------|--------|
| `nested` | struct/union | struct/union | Field type is a struct | Solid blue line |
| `param` | function | struct/union | Parameter type is a struct | Solid blue line |
| `return` | function | struct/union | Return type is a struct | Green line |
| `uses` | function | struct/union | Local variable in function body | Gray dashed line |

## 6. Entity Types on Canvas

| Entity | Header Color | Badge | Meta Info |
|--------|-------------|-------|-----------|
| Struct | Gray (headerBg) | S | `{size}B  {alignment}-al` |
| Union | Purple (unionHeader) | U | `union  {size}B  {alignment}-al` |
| Function | Green (functionHeader) | F | `{paramCount}p  → {returnType}` |

## 7. New Features (Phase 3+)

### Source File Preview Modal (`cstruct-modal.js`)
- Double-click a block → opens source file preview modal
- Shows full file content with line numbers
- Highlights the definition line (`entity.sourceLine`)
- Auto-scrolls to highlighted line
- Closes via Escape, backdrop click, or close button
- Requires `sourceFile` and `sourceLine` on entities + `fileContents` in state

### Search and Filter System (`cstruct-search.js`)
- **Search**: text search across entity names, field names, field types, categories
- **Type filters**: toggle chips for struct/union/function
- **File filters**: dropdown to show/hide entities from specific source files
- **Stdlib filter**: chip/checkbox to show/hide standard C library items
- **Focus mode**: click search result to focus on entity + its connected subgraph
- **Per-entity visibility**: checkboxes in sidebar to hide individual entities
- **Reset**: button to clear all active filters
- `getVisibleEntities()` returns a Set of visible entity names (null = show all)

### By-File Layout
- Groups entities by `sourceFile` into visual containers (dashed border boxes)
- Containers titled with filename, entities arranged in grid inside each container
- Containers arranged in a grid layout
- `drawFileContainer()` in `cstruct-blocks.js` renders the container boxes

### Stdlib Filtering
- Backend tags entities with `isStdlib: true/false` using `STDLIB_NAMES` set
- `getAllEntities()` filters out stdlib entities by default
- Toggle via toolbar chip or sidebar checkbox (`showStdlib` state key)

## 8. Architecture Decisions

- **libclang over regex**: Accurate offsets, padding, alignment. Handles typedefs, nested types, bitfields, packed attributes. Cross-file include resolution works with temp directory approach.
- **Canvas over SVG/DOM**: Better performance for hundreds of blocks. Direct pixel control for padding stripes, badge shapes. Single render pipeline, no DOM thrashing.
- **Single orchestrator (app.js)**: All event subscriptions route through `scheduleRender()` in app.js. Prevents double-rendering. Connections never subscribe to events directly.
- **Stateless drawing functions**: blocks.js and connections.js are pure — they take data and draw. No state, no event subscriptions. Testable, composable.
- **Temp directory for parsing**: Required because libclang needs real file paths for `#include` resolution. Files written to temp, `__main__.c` includes all, temp cleaned up after parse.
- **Search module owns filter logic**: `cstruct-search.js` exports `getVisibleEntities()` which the render pipeline calls. Filter state lives in `cstruct-state.js` but filter computation is in search module.
- **Source preview via fileContents**: Route handler sends raw file contents alongside parsed data. Modal reads from state, no extra HTTP requests needed.
- **Double-click = source preview, not collapse**: Collapse/expand is handled by the triangle button in the header. Double-click opens the source file modal.
