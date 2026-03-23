# Ralph Loop: Finish DB Diagram Visualizer

You are completing a DB Diagram Visualizer (dbdiagram.io clone). Read CLAUDE.md for full project rules. Desktop only.

## Current State

**Phase 1 DONE:** events.js, state.js, canvas.js, connections.js, blocks.js, constants.js, styles.css, index.html, app.py, csv_handler.py, key_detector.py, relationship_analyzer.py, search.py, trace.py, requirements.txt

**Phase 2 DONE:** app.js (full wiring), csv-import.js, layout.js — but NOT yet validated end-to-end.

**Phase 3 NOT STARTED:** search.js, trace.js, filters.js, export.js

## Your Task Each Iteration

Work through this checklist TOP TO BOTTOM. Skip steps already completed (check git log and file contents). Do ONE step per iteration, verify it, then output the promise if all steps are done.

### Step 1: Validate Phase 2 Integration
- Run `python app.py` and verify it starts on port 5000
- Open browser at localhost:5000, check the page loads
- Fix any import errors, missing exports, or broken references in JS files
- Ensure all JS imports match real exports (grep for every import, verify the export exists)
- Test: create 2 test CSV files (users.csv, orders.csv with user_id FK), upload via the UI, verify tables render

### Step 2: Fix Integration Bugs
- If upload doesn't work: check csv-import.js fetch calls match app.py routes
- If blocks don't render: check blocks.js reads state correctly (uses getStateRef)
- If connections don't render: check connections.js redrawAll is called from app.js render()
- If drag/zoom/pan broken: check app.js mouse event handlers, screenToCanvas conversion
- Verify the Iron Rule: every state change triggers render() which calls connections.redrawAll()
- Verify toast uses CSS class toggle (.toast--visible) not hidden attribute

### Step 3: Create Phase 3 — search.js
Create `/static/js/search.js`:
- Wire the #search-input element with 300ms debounce
- On input: POST to /api/search with {query, mode: 'contains', scope: 'all'}
- Store results in State.setSearchResults()
- Render results list in sidebar (table name, column, matched value)
- Click result → panToTable (emit 'panToTable' event with table name)
- Clear button resets search
- Import from state.js, events.js, constants.js only

### Step 4: Create Phase 3 — trace.js
Create `/static/js/trace.js`:
- Export initTrace() function
- When search results exist, show "Trace" button per result
- Click trace → POST /api/trace with {table, column, value, depth: 5}
- Store trace in State.setTraceResults()
- In connections.js or via state, trace results cause matching connection lines to render bold/animated (dashed animation)
- Show trace path in sidebar

### Step 5: Create Phase 3 — filters.js
Create `/static/js/filters.js`:
- Export initFilters() function
- Populate #filter-panel with checkbox groups:
  - By key type: PK, FK, UQ (from loaded tables)
  - By relationship type: one-to-one, one-to-many, many-to-many
  - By table: checkbox per loaded table
- Checking/unchecking calls State.applyFilter() or State.clearFilters()
- Filter chips appear above checkboxes for active filters
- "Clear all" button
- Dim vs Hide toggle (controls whether filtered items are opacity 0.25 or hidden)

### Step 6: Create Phase 3 — export.js
Create `/static/js/export.js`:
- Export initExport() function
- Wire #btn-export dropdown with options: PNG, JSON
- PNG: render canvas to blob at 2x resolution, trigger download
- JSON: State.exportState() → download as .json file
- Use standard download pattern (create <a>, set href to blob URL, click, revoke)

### Step 7: Wire Phase 3 into app.js
- Import and call initSearch(), initTrace(), initFilters(), initExport() in DOMContentLoaded
- Verify search/filter state changes trigger render() via existing event subscriptions
- Verify filters affect connections.js rendering (dimmed/hidden lines for filtered tables)

### Step 8: Update index.html if needed
- Add any missing DOM elements for search results panel, filter chips, trace controls
- Ensure all IDs referenced by Phase 3 JS files exist in HTML

### Step 9: End-to-End Validation
Run through the full verification checklist:
1. `python app.py` starts, `GET /` serves page
2. Upload 2+ related CSVs → table blocks with correct keys + connection lines
3. Drag table → lines follow real-time
4. Zoom (Ctrl+scroll) and pan work
5. Layout algorithms produce reasonable results
6. Search finds values, results appear in sidebar
7. Filters dim/hide tables and connections
8. Export PNG and JSON work
9. No external URLs in any file
10. connections.redrawAll() fires on every state change

Fix any failures found.

### Step 10: Run /simplify
Review all changed code for quality. Fix issues.

## Rules
- Read CLAUDE.md and follow ALL rules
- Read files before editing them
- Every state mutation must emit events (the Iron Rule)
- No external CDNs or URLs — everything local
- Desktop only — no mobile/tablet code
- Use shared constants from constants.js (never duplicate ROW_HEIGHT etc.)
- Use getStateRef() for render-path reads, getState() only for snapshots
- Functions under 40 lines
- ES6 modules, const by default, arrow callbacks

## Completion

When ALL 10 steps are verified and working, output:
<promise>PLAN COMPLETE</promise>
