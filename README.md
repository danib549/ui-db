# DB Diagram Visualizer

A local, browser-based tool for visualizing database table relationships from CSV files — similar to [dbdiagram.io](https://dbdiagram.io), but fully offline.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![Flask](https://img.shields.io/badge/Flask-Backend-green) ![Vanilla JS](https://img.shields.io/badge/Vanilla_JS-Frontend-yellow)

## What It Does

1. **Upload CSV files** — each file represents a database table
2. **Auto-detect keys** — primary keys, foreign keys, and unique constraints identified from column names and data patterns
3. **Infer relationships** — FK-to-PK matching across tables with cardinality detection (1:1, 1:N, M:N)
4. **Render interactive diagram** — table blocks on an HTML5 Canvas with bezier curve connection lines and crow's foot notation
5. **Search & trace** — find values across all tables and trace data flow along FK chains
6. **Filter & export** — filter by key type, relationship type, or table; export as PNG or JSON

## Quick Start

```bash
# Install dependencies
pip install flask pandas

# Run the server
python app.py

# Open in browser
# http://localhost:5000
```

Upload CSV files via the sidebar or drag-and-drop onto the canvas.

## Features

### Canvas Interactions
- **Drag** table blocks by their header
- **Pan** by dragging empty canvas space (or middle-mouse anywhere)
- **Zoom** with Ctrl+Scroll (cursor-centered, 25%-200%)
- **Select** with click, Shift+click, or Ctrl+A
- **Collapse** tables with double-click on header
- **Delete** selected tables with Delete key

### Auto-Layout
Four layout algorithms available from the toolbar:
- **Left-to-Right** — dependency flow (roots left, children right)
- **Top-to-Bottom** — vertical dependency flow
- **Force-Directed** — physics simulation minimizing line crossings
- **Grid** — alphabetical grid arrangement

### Search & Trace
- Type in the search bar to find values across all loaded tables
- Click the trace button (arrows icon) on any search result to follow FK relationships
- Traced connections highlight as animated red dashed lines

### Filters
- Filter by key type (PK, FK, UQ)
- Filter by relationship type (one-to-one, one-to-many, many-to-many)
- Filter by table name
- Toggle between dim and hide modes

### Export
- **PNG** — rasterized diagram at 2x resolution
- **JSON** — full state snapshot (tables, positions, connections)

## Project Structure

```
db-diagram-visualizer/
├── app.py                    # Flask routes (thin layer)
├── csv_handler.py            # CSV parsing, type detection
├── key_detector.py           # PK/FK/UQ detection
├── relationship_analyzer.py  # Cross-table relationship inference
├── search.py                 # Cross-table value search
├── trace.py                  # BFS value tracing across FKs
├── requirements.txt          # flask, pandas
├── templates/
│   └── index.html            # Main page
├── static/
│   ├── css/
│   │   └── styles.css        # All styles (BEM, CSS custom properties)
│   └── js/
│       ├── app.js            # Main orchestrator, render pipeline, interactions
│       ├── state.js          # Central state store, mutations emit events
│       ├── events.js         # Pub/sub event bus
│       ├── constants.js      # Shared dimensions, colors, helpers
│       ├── utils.js          # Shared utilities (escapeHtml)
│       ├── canvas.js         # Canvas engine, viewport, grid background
│       ├── blocks.js         # Table block rendering
│       ├── connections.js    # Connection lines, bezier curves, cardinality
│       ├── csv-import.js     # File upload and drag-and-drop
│       ├── layout.js         # Layout algorithms with animation
│       ├── search.js         # Search UI
│       ├── trace.js          # Value tracing UI
│       ├── filters.js        # Filter panel
│       └── export.js         # PNG/JSON export
└── test_data/                # Sample CSVs for testing
    ├── users.csv
    ├── orders.csv
    └── products.csv
```

## Architecture

- **Backend**: Python/Flask — handles CSV parsing, key detection, relationship analysis, search, and trace. Returns JSON only.
- **Frontend**: Vanilla JS with HTML5 Canvas — all rendering and interaction client-side. No frameworks.
- **State**: Central store (`state.js`) with event-driven mutations. Every state change triggers a render via `scheduleRender()` (rAF-batched).
- **The Iron Rule**: Connection lines are fully recalculated on every state change. Never cached.
- **Local only**: No CDNs, no external APIs, no tracking. Everything runs on localhost.

## Key Detection Rules

| Pattern | Detected As |
|---------|-------------|
| Column named `id` with all unique non-null values | Primary Key (PK) |
| Column named `uuid` or `guid` | Primary Key (PK) |
| Column ending in `_id`, `_ref`, `_key` | Foreign Key (FK) |
| All values unique and non-null (not FK) | Unique (UQ) |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serve the main page |
| POST | `/api/upload-csv` | Upload CSV files, returns tables + relationships |
| POST | `/api/detect-relationships` | Re-detect relationships for loaded tables |
| POST | `/api/search` | Search values across tables |
| POST | `/api/trace` | Trace a value across FK chains |

## License

MIT
