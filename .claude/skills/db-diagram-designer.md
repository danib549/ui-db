# Skill: DB Diagram Designer — System Design and Lifecycle

## When to Use

Apply this skill when working on the end-to-end flow of the DB Diagram Visualizer: from CSV file upload through backend analysis to interactive diagram rendering. This covers the full design lifecycle, table block architecture, schema grouping, layout algorithms, import/export, and multi-table workflows.

---

## Design Lifecycle

The full pipeline from raw CSV data to interactive visual diagram:

```
CSV files  -->  Backend (parse, detect, analyze)  -->  JSON schema  -->  Frontend (render, interact)
```

### Step 1: Upload CSV Files

Each CSV file represents one database table. The file name (minus extension) becomes the table name.

- Single file upload via file input or drag-and-drop
- Batch upload: multiple CSVs at once to build a full schema in one action
- Drag-and-drop zone on the canvas or sidebar

```javascript
// Frontend: upload one or more CSV files
async function uploadCSVFiles(files) {
  const formData = new FormData();
  for (const file of files) {
    formData.append('files', file);
  }
  const response = await fetch('/api/upload-csv', { method: 'POST', body: formData });
  const schema = await response.json();
  // schema = { tables: [...], relationships: [...] }
  return schema;
}
```

### Step 2: Backend Parses Columns and Detects Types

The backend reads each CSV with pandas, inspects every column, and maps pandas dtypes to display-friendly SQL types.

```python
DTYPE_MAP: dict[str, str] = {
    "int64": "INT",
    "float64": "FLOAT",
    "object": "VARCHAR",
    "bool": "BOOLEAN",
    "datetime64[ns]": "TIMESTAMP",
    "timedelta64[ns]": "INTERVAL",
    "category": "ENUM",
}

def parse_csv_columns(df: pd.DataFrame) -> list[dict]:
    columns = []
    for col in df.columns:
        dtype_str = str(df[col].dtype)
        display_type = DTYPE_MAP.get(dtype_str, "VARCHAR")
        nullable = bool(df[col].isnull().any())
        unique_count = df[col].nunique()
        total_count = len(df[col].dropna())

        columns.append({
            "name": col,
            "type": display_type,
            "nullable": nullable,
            "unique_count": unique_count,
            "total_count": total_count,
        })
    return columns
```

### Step 3: Backend Identifies Potential Keys

Key detection uses both naming conventions and data analysis:

| Rule | Detection | Key Type |
|------|-----------|----------|
| Column named exactly `id` | Convention | PK candidate |
| Column named `<table>_id` matching another table | Convention + match | FK candidate |
| Column ending in `_id` | Convention | FK candidate |
| All values unique, non-null | Data analysis | PK or UQ candidate |
| All values unique, some null | Data analysis | UQ candidate |
| Column named `uuid`, `guid`, or similar | Convention | PK candidate |

```python
def detect_keys(table_name: str, columns: list[dict]) -> list[dict]:
    for col in columns:
        name = col["name"]
        is_all_unique = col["unique_count"] == col["total_count"] and not col["nullable"]

        col["key_type"] = None
        if name == "id" and is_all_unique:
            col["key_type"] = "PK"
        elif name.endswith("_id"):
            col["key_type"] = "FK"
        elif is_all_unique and col["total_count"] > 0:
            col["key_type"] = "UQ"

    return columns
```

### Step 4: Backend Analyzes Cross-Table Relationships

After all tables are parsed, the backend compares columns across tables to find FK-to-PK matches.

```python
def detect_relationships(tables: list[dict]) -> list[dict]:
    relationships = []
    pk_index = {}

    # Build index: table_name -> list of PK/UQ column names
    for table in tables:
        for col in table["columns"]:
            if col["key_type"] in ("PK", "UQ"):
                pk_index.setdefault(table["name"], []).append(col["name"])

    # Match FK columns to PK columns in other tables
    for table in tables:
        for col in table["columns"]:
            if not col["name"].endswith("_id"):
                continue
            # e.g., "user_id" -> look for table "users" with PK "id"
            ref_table_name = col["name"].removesuffix("_id") + "s"
            if ref_table_name in pk_index and "id" in pk_index[ref_table_name]:
                relationships.append({
                    "source_table": table["name"],
                    "source_column": col["name"],
                    "target_table": ref_table_name,
                    "target_column": "id",
                    "type": "many-to-one",
                })

    return relationships
```

### Step 5: Frontend Receives JSON and Renders

The backend returns a complete schema definition. The frontend uses this to create table blocks and connection lines on the canvas.

```json
{
  "tables": [
    {
      "name": "users",
      "columns": [
        { "name": "id", "type": "INT", "key_type": "PK", "nullable": false },
        { "name": "email", "type": "VARCHAR", "key_type": "UQ", "nullable": false },
        { "name": "name", "type": "VARCHAR", "key_type": null, "nullable": true }
      ],
      "group": "core"
    },
    {
      "name": "orders",
      "columns": [
        { "name": "id", "type": "INT", "key_type": "PK", "nullable": false },
        { "name": "user_id", "type": "INT", "key_type": "FK", "nullable": false },
        { "name": "total", "type": "FLOAT", "key_type": null, "nullable": true }
      ],
      "group": "transactions"
    }
  ],
  "relationships": [
    {
      "source_table": "orders",
      "source_column": "user_id",
      "target_table": "users",
      "target_column": "id",
      "type": "many-to-one"
    }
  ]
}
```

### Step 6: Auto-Layout and User Arrangement

Blocks are placed on the canvas using an auto-layout algorithm, then the user can drag to rearrange. Every position change triggers `connections.redrawAll()`.

---

## Table Block Architecture

### Data-to-Visual Mapping

| Data Element | Visual Element | Details |
|-------------|---------------|---------|
| Table name | Block header | Semibold, 13px, with table icon |
| Column name | Row label | 12px, left-aligned after key icon |
| Column type | Row badge | 11px monospace, right-aligned, secondary color |
| PK column | Amber key icon | `#F59E0B` fill, left border accent |
| FK column | Blue link icon | `#3B82F6` fill, left border accent |
| UQ column | Violet shield icon | `#8B5CF6` fill, left border accent |
| Nullable | "NULL" badge | Small gray pill |
| Not null | "NN" badge | Small dark pill |

### Key Detection Rules Summary

**Primary Key candidates:**
- Column named `id` with all unique, non-null values
- Column named `<table_name>_id` that is unique (e.g., `user_id` in a `users` table where it is the PK)
- Column named `uuid`, `guid`, or matching UUID format

**Foreign Key candidates:**
- Column ending in `_id` (e.g., `user_id`, `order_id`, `category_id`)
- Column name matches `<other_table>.<pk_column>` pattern
- Values are a subset of another table's PK values (data-level validation)

**Unique Key candidates:**
- All non-null values are distinct, but column is not named like a PK

### Data Type Mapping

| pandas dtype | Display Type | Notes |
|-------------|-------------|-------|
| `int64` | `INT` | Check range for BIGINT vs SMALLINT |
| `float64` | `FLOAT` | Check for DECIMAL patterns |
| `object` | `VARCHAR` | Default for strings |
| `object` (long text) | `TEXT` | If avg length > 255 |
| `bool` | `BOOLEAN` | |
| `datetime64[ns]` | `TIMESTAMP` | |
| `category` | `ENUM` | If fewer than 20 unique values |

---

## Schema Grouping

Tables can be organized into groups (schemas, domains, or user-defined categories) for visual clarity.

### Group Assignment

- Auto-detect by naming prefix: `auth_users`, `auth_roles` -> group `auth`
- Auto-detect by relationship clusters: heavily interconnected tables form a group
- Manual assignment via sidebar UI

### Visual Indicators

- **Header accent color**: 2px bottom border on the block header, color-coded per group
- **Canvas group labels**: faint background region with group name, positioned behind blocks
- **Sidebar group tree**: collapsible tree with group names, each showing member tables

### Group Color Palette

```javascript
const GROUP_COLORS = {
  core:         '#3B82F6', // blue
  auth:         '#8B5CF6', // violet
  transactions: '#22C55E', // green
  analytics:    '#F97316', // orange
  content:      '#EC4899', // pink
  system:       '#6B7280', // gray
  default:      '#9CA3AF', // light gray
};
```

### Filter by Group

- Checkbox per group in the filter sidebar
- Unchecking a group dims or hides all tables in that group
- Connection lines between hidden groups are not drawn
- Connection lines from a visible group to a hidden group render as dashed

---

## Layout Algorithms

### Left-to-Right (LR)

Parent tables (those with PKs referenced by FKs) are placed on the left. Child tables (those with FKs) are placed to the right. Depth is determined by the longest FK chain.

```
[users] ──> [orders] ──> [order_items]
                    └──> [payments]
[products] ────────────> [order_items]
```

- Column 0: root tables (no FKs, or only PKs referenced by others)
- Column N: tables whose FKs point to tables in column N-1
- Vertical spacing within each column: even distribution
- Horizontal spacing: 300px between columns

### Top-to-Bottom (TB)

Same dependency logic as LR, but arranged vertically. Root tables at the top, children below.

### Force-Directed

Physics-based simulation where tables repel each other and connections act as springs.

```javascript
function forceDirectedStep(tables, connections) {
  const REPULSION = 5000;
  const SPRING_LENGTH = 250;
  const SPRING_STRENGTH = 0.02;
  const DAMPING = 0.9;

  // Repulsion between all pairs
  for (let i = 0; i < tables.length; i++) {
    for (let j = i + 1; j < tables.length; j++) {
      const dx = tables[j].x - tables[i].x;
      const dy = tables[j].y - tables[i].y;
      const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      const force = REPULSION / (dist * dist);
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      tables[i].vx -= fx;
      tables[i].vy -= fy;
      tables[j].vx += fx;
      tables[j].vy += fy;
    }
  }

  // Spring attraction along connections
  for (const conn of connections) {
    const src = tables.find(t => t.name === conn.source_table);
    const tgt = tables.find(t => t.name === conn.target_table);
    const dx = tgt.x - src.x;
    const dy = tgt.y - src.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    const force = (dist - SPRING_LENGTH) * SPRING_STRENGTH;
    const fx = (dx / dist) * force;
    const fy = (dy / dist) * force;
    src.vx += fx;
    src.vy += fy;
    tgt.vx -= fx;
    tgt.vy -= fy;
  }

  // Apply velocities with damping
  for (const table of tables) {
    table.vx *= DAMPING;
    table.vy *= DAMPING;
    table.x += table.vx;
    table.y += table.vy;
  }
}
```

### Grid

Alphabetical or group-based placement in a fixed grid. Ignores relationships entirely. Useful as a clean reset.

```javascript
function gridLayout(tables, columns = 4, cellWidth = 320, cellHeight = 400) {
  const sorted = [...tables].sort((a, b) => a.name.localeCompare(b.name));
  return sorted.map((table, i) => ({
    name: table.name,
    x: (i % columns) * cellWidth + 40,
    y: Math.floor(i / columns) * cellHeight + 40,
  }));
}
```

### Transition Animation

All layout changes animate blocks from current position to target position.

```javascript
function animateLayout(currentPositions, targetPositions, duration = 350) {
  const startTime = performance.now();

  function step(now) {
    const t = Math.min((now - startTime) / duration, 1);
    const eased = t < 0.5
      ? 4 * t * t * t
      : 1 - Math.pow(-2 * t + 2, 3) / 2; // ease-in-out cubic

    for (const table of Object.keys(targetPositions)) {
      const from = currentPositions[table];
      const to = targetPositions[table];
      state.setPosition(table, {
        x: from.x + (to.x - from.x) * eased,
        y: from.y + (to.y - from.y) * eased,
      });
    }

    connections.redrawAll();

    if (t < 1) {
      requestAnimationFrame(step);
    }
  }

  requestAnimationFrame(step);
}
```

### Undo Stack

Every layout change pushes the previous positions onto an undo stack. Show a toast notification with an undo action for 5 seconds after any auto-layout operation.

```javascript
const layoutUndoStack = [];

function applyLayoutWithUndo(newPositions) {
  layoutUndoStack.push(structuredClone(state.getPositions()));
  animateLayout(state.getPositions(), newPositions);
  showToast('Layout applied.', {
    action: 'Undo',
    onAction: () => {
      const prev = layoutUndoStack.pop();
      if (prev) animateLayout(state.getPositions(), prev);
    },
    timeout: 5000,
  });
}
```

---

## Import/Export

### Import

| Source | Method | Handler |
|--------|--------|---------|
| Single CSV | File input button | `POST /api/upload-csv` |
| Multiple CSVs | File input with `multiple` | `POST /api/upload-csv` (batch) |
| Drag-and-drop | Drop zone on canvas | Same endpoint, triggered by drop event |
| JSON schema | File input or paste | Client-side parse, load directly into state |

### Export

| Format | Content | Method |
|--------|---------|--------|
| PNG | Rendered diagram as raster image | Canvas `toBlob()` or html2canvas |
| SVG | Rendered diagram as vector | Serialize SVG DOM or build SVG string |
| JSON schema | Table definitions + relationships + positions | `JSON.stringify(state.export())` |

```javascript
function exportDiagramJSON() {
  return {
    version: 1,
    tables: state.getTables(),
    relationships: state.getConnections(),
    positions: state.getPositions(),
    groups: state.getGroups(),
    filters: state.getFilters(),
    viewport: state.getViewport(),
  };
}

function importDiagramJSON(json) {
  const data = typeof json === 'string' ? JSON.parse(json) : json;
  state.reset();
  state.setTables(data.tables);
  state.setConnections(data.relationships);
  state.setPositions(data.positions);
  if (data.groups) state.setGroups(data.groups);
  if (data.filters) state.setFilters(data.filters);
  if (data.viewport) state.setViewport(data.viewport);
  connections.redrawAll();
}
```

### Save/Load Diagram State

- Save to `localStorage` for quick persistence
- Export/import JSON file for sharing or backup
- Positions, filters, groups, and viewport state are all included

---

## Multi-Table Workflow

### Incremental Table Addition

When new CSVs are uploaded to an existing diagram:

1. Parse new CSV files on the backend
2. Re-run relationship detection across ALL tables (existing + new)
3. Add new table blocks to the canvas without disturbing existing block positions
4. Place new blocks in open canvas space (avoid overlapping existing blocks)
5. Draw new connection lines (existing lines remain unchanged)
6. Emit `tableAdded` event for each new table, triggering `connections.redrawAll()`

```javascript
async function addTablesToExistingDiagram(files) {
  const formData = new FormData();
  for (const file of files) {
    formData.append('files', file);
  }
  // Send existing table names so backend can detect cross-table relationships
  formData.append('existing_tables', JSON.stringify(state.getTableNames()));

  const response = await fetch('/api/upload-csv', { method: 'POST', body: formData });
  const { tables: newTables, relationships: allRelationships } = await response.json();

  // Place new blocks in open space
  const openPosition = findOpenCanvasSpace(state.getPositions(), newTables.length);
  for (let i = 0; i < newTables.length; i++) {
    state.addTable(newTables[i]);
    state.setPosition(newTables[i].name, openPosition[i]);
  }

  // Update all relationships (may include new cross-table connections)
  state.setConnections(allRelationships);
  connections.redrawAll();
}
```

### Table Removal

When a table is removed from the diagram:

1. Remove the table block from state
2. Remove all connections where this table is source or target
3. Emit `tableRemoved` event
4. `connections.redrawAll()` cleans up orphan lines automatically

```javascript
function removeTable(tableName) {
  state.removeTable(tableName);
  state.removeConnectionsForTable(tableName);
  state.removePosition(tableName);
  // redrawAll() is triggered by the stateChanged event
}
```

### Relationship Re-Detection

After any table addition or removal, relationships should be re-analyzed:

- Backend endpoint: `POST /api/detect-relationships` with current full table list
- Returns updated relationship array
- Frontend replaces the connection list in state and redraws

---

## Integration: Search System

The diagram integrates with a cross-table search system that allows users to trace data values across related tables.

**Capabilities:**
- Search for a specific value (e.g., user ID `42`) and highlight all tables/rows where it appears
- Trace data flow: given a value in table A, follow FK relationships to find related records in tables B, C, D
- Highlight the connection path on the diagram, showing the chain of joins
- Display matched row counts as badges on table blocks during a search
- Filter the diagram to show only tables involved in a search result

---

## Integration: PostgreSQL Schema Builder

The diagram page serves as a **data source** for the PostgreSQL Schema Builder (`/builder`). Loaded CSV tables and their detected columns/keys are available to the builder for:

- **Source-to-target mapping**: drag columns from source tables (loaded CSVs) to target tables (PG schema being built)
- **Type suggestion**: the builder uses CSV column metadata (dtype, unique count, sample values) to suggest proper PG types
- **Migration generation**: the builder generates INSERT INTO...SELECT scripts that reference the source tables

**Data flow**: Diagram page loads CSVs → backend stores in memory → builder page fetches via `/api/table-data` → user maps columns → builder generates DDL + migration SQL.

See skills: `pg-ddl-engine.md`, `pg-builder-ui.md`, `pg-validation.md`, `pg-migration.md`.
