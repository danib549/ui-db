---
skill: Frontend Development Patterns for DB Visualizer
---

# Frontend Development Patterns for DB Visualizer

## 1. Architecture Pattern

- Python backend serves API + static files
- Frontend: vanilla JS or lightweight framework (no heavy frameworks)
- Communication via REST API (JSON)
- WebSocket optional for real-time collaboration

## 2. Module Structure

- `/static/js/app.js` - Main entry, render pipeline, event wiring, interactions
- `/static/js/state.js` - Central state management (getStateRef for reads, mutations emit events)
- `/static/js/events.js` - Publish/subscribe event bus
- `/static/js/constants.js` - Shared constants (dimensions, colors, helpers)
- `/static/js/utils.js` - Shared utilities (escapeHtml)
- `/static/js/canvas.js` - Canvas rendering engine, viewport, grid background
- `/static/js/blocks.js` - Table block rendering
- `/static/js/connections.js` - Line drawing, bezier curves, cardinality, trace animation
- `/static/js/csv-import.js` - CSV upload and drag-and-drop
- `/static/js/layout.js` - Auto-sort/layout algorithms (LR, TB, force-directed, grid)
- `/static/js/search.js` - Cross-table value search UI
- `/static/js/trace.js` - Value tracing across FK relationships
- `/static/js/filters.js` - Filter panel (key type, relationship type, table)
- `/static/js/export.js` - PNG and JSON export
- `/static/css/styles.css` - All styles
- `/templates/index.html` - Main page template

## 3. State Management Pattern

- Single state object (tables, positions, connections, filters, viewport)
- State mutations via functions that trigger re-renders
- Event bus for cross-module communication
- Every state change fires a "stateChanged" event with changed keys

Example pattern:

```javascript
const AppState = {
  tables: [],
  positions: {},
  connections: [],
  filters: {},
  viewport: { x: 0, y: 0, zoom: 1 },

  update(key, value) {
    this[key] = value;
    EventBus.emit("stateChanged", { key, value });
  }
};
```

## 4. Event Handling

- Canvas mouse events (drag, click, scroll for zoom)
- Keyboard shortcuts (delete, ctrl+A select all, escape deselect)
- Filter input events with debounce
- Window resize handler

Key patterns:

```javascript
// Debounce for filter inputs
function debounce(fn, delay = 300) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

// Canvas zoom via scroll
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  const zoomDelta = e.deltaY > 0 ? -0.1 : 0.1;
  AppState.update("viewport", {
    ...AppState.viewport,
    zoom: Math.max(0.1, Math.min(3, AppState.viewport.zoom + zoomDelta))
  });
});
```

## 5. CSV Import Flow

1. Upload CSV via file input
2. Parse headers as column names
3. Detect data types from values
4. Auto-detect potential keys (unique columns, naming conventions like `*_id`)
5. Create table block from parsed data

Frontend handles file selection and preview; backend handles analysis:

```javascript
async function uploadCSV(file) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch("/upload-csv", { method: "POST", body: formData });
  const tableData = await response.json();
  AppState.update("tables", [...AppState.tables, tableData]);
}
```

## 6. Python Backend Patterns

- Flask/FastAPI serving templates and static files
- API endpoints:
  - `POST /upload-csv` - Upload and parse a CSV file
  - `GET /tables` - Retrieve all table definitions
  - `POST /relationships` - Define or auto-detect relationships
- Data processing in Python (pandas for CSV analysis)
- Key detection algorithms server-side

Flask example:

```python
@app.route("/upload-csv", methods=["POST"])
def upload_csv():
    file = request.files["file"]
    df = pd.read_csv(file)
    columns = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        is_unique = df[col].nunique() == len(df)
        is_potential_key = col.endswith("_id") or is_unique
        columns.append({
            "name": col,
            "type": dtype,
            "is_key": is_potential_key
        })
    return jsonify({"name": file.filename, "columns": columns})
```
