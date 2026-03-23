# DB Search & Value Trace System

Skill for implementing cross-table value search and data flow tracing in the DB Diagram Visualizer.

---

## 1. Search Architecture

### Overview

The user enters a value in the search bar. The backend searches all loaded CSV data across every table and column, returning structured match results. The frontend highlights matching tables and columns on the diagram canvas.

### Backend: Search Endpoint

```python
# search.py

import pandas as pd
from typing import Optional

def search_all_tables(
    tables: dict[str, pd.DataFrame],
    query: str,
    mode: str = "contains",
    scope: Optional[dict] = None,
) -> list[dict]:
    """
    Search all loaded tables for a value.

    Args:
        tables: {table_name: DataFrame} of all loaded CSVs
        query: the search string
        mode: "exact", "contains", "starts_with", "regex"
        scope: optional filter — {"tables": [...], "column_type": "id"}

    Returns:
        List of match dicts:
        [
            {
                "table": "users",
                "column": "email",
                "row_index": 7,
                "value": "john@email.com",
                "context_row": {"id": 42, "email": "john@email.com", "name": "John"}
            },
            ...
        ]
    """
    results = []
    max_per_table = 100

    for table_name, df in tables.items():
        if scope and "tables" in scope and table_name not in scope["tables"]:
            continue

        columns = _resolve_columns(df, scope)
        table_hits = 0

        for col in columns:
            if table_hits >= max_per_table:
                break

            mask = _apply_search_mode(df[col], query, mode)
            matching_indices = df.index[mask].tolist()

            for idx in matching_indices:
                if table_hits >= max_per_table:
                    break
                results.append({
                    "table": table_name,
                    "column": col,
                    "row_index": idx,
                    "value": str(df.at[idx, col]),
                    "context_row": df.iloc[idx].to_dict(),
                })
                table_hits += 1

    return results


def _apply_search_mode(
    series: pd.Series, query: str, mode: str
) -> pd.Series:
    """Return a boolean mask for the given search mode."""
    s = series.astype(str)
    if mode == "exact":
        return s.eq(query)
    if mode == "contains":
        return s.str.contains(query, case=False, na=False)
    if mode == "starts_with":
        return s.str.startswith(query, na=False)
    if mode == "regex":
        return s.str.contains(query, regex=True, case=False, na=False)
    return s.str.contains(query, case=False, na=False)


def _resolve_columns(
    df: pd.DataFrame, scope: Optional[dict]
) -> list[str]:
    """Determine which columns to search based on scope."""
    if scope and "column_type" in scope:
        # Filter to columns matching a type hint (e.g., only ID columns)
        # This relies on key_detector metadata if available
        return [c for c in df.columns if _matches_column_type(c, scope["column_type"])]
    return list(df.columns)


def _matches_column_type(column_name: str, column_type: str) -> bool:
    """Check if a column name matches the requested type filter."""
    type_patterns = {
        "id": ["id", "_id", "Id", "ID"],
        "email": ["email", "mail"],
        "date": ["date", "created", "updated", "timestamp"],
    }
    patterns = type_patterns.get(column_type, [])
    return any(p in column_name for p in patterns)
```

### Backend: Route

```python
# In app.py

@app.post("/search")
def search_values():
    body = request.get_json()
    query = body["query"]
    mode = body.get("mode", "contains")
    scope = body.get("scope", None)

    results = search_all_tables(loaded_tables, query, mode, scope)
    return {"query": query, "mode": mode, "total": len(results), "matches": results}
```

### Frontend: Dispatching Search

```javascript
// search.js

import { getState, setSearchResults, clearSearchResults } from './state.js';
import { emit } from './events.js';

let activeController = null;

const searchAllTables = async (query, mode = 'contains', scope = null) => {
    // Cancel any in-flight search
    if (activeController) {
        activeController.abort();
    }
    activeController = new AbortController();

    if (!query || query.trim() === '') {
        clearSearchResults();
        emit('searchCleared');
        return;
    }

    emit('searchStarted', { query });

    try {
        const response = await fetch('/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, mode, scope }),
            signal: activeController.signal,
        });
        const data = await response.json();

        setSearchResults({
            query: data.query,
            mode: data.mode,
            total: data.total,
            matches: data.matches,
        });

        emit('searchResultsReady', { total: data.total });
    } catch (err) {
        if (err.name !== 'AbortError') {
            console.error('Search failed:', err);
        }
    } finally {
        activeController = null;
    }
};

export { searchAllTables };
```

---

## 2. Value Tracing

### Overview

After search returns matches, the trace system follows foreign key relationships to build a "data flow graph." For example, value `42` found in `users.id` traces to `orders.user_id = 42`, then to `order_items` for those orders, then to `products` referenced by those items.

### Backend: Trace Endpoint

```python
# trace.py

import pandas as pd

def trace_value(
    tables: dict[str, pd.DataFrame],
    relationships: list[dict],
    start_table: str,
    start_column: str,
    value: str,
    max_depth: int = 3,
) -> dict:
    """
    Follow FK chains from a starting match to build a flow graph.

    Args:
        tables: all loaded DataFrames
        relationships: list of {"from_table", "from_column", "to_table", "to_column"}
        start_table: table where the value was found
        start_column: column where the value was found
        value: the matched value (as string)
        max_depth: how many hops to follow (default 3)

    Returns:
        {
            "nodes": [{"table": "users", "column": "id", "match_count": 1}, ...],
            "edges": [{"from_table": "users", "from_column": "id",
                        "to_table": "orders", "to_column": "user_id",
                        "matched_rows": 5}, ...],
            "depth_reached": 2
        }
    """
    visited = set()
    nodes = []
    edges = []
    queue = [(start_table, start_column, value, 0)]

    while queue:
        table, column, val, depth = queue.pop(0)
        visit_key = f"{table}.{column}.{val}"

        if visit_key in visited or depth > max_depth:
            continue
        visited.add(visit_key)

        if table not in tables:
            continue

        df = tables[table]
        mask = df[column].astype(str).eq(str(val))
        match_count = int(mask.sum())

        if match_count == 0:
            continue

        nodes.append({
            "table": table,
            "column": column,
            "match_count": match_count,
            "depth": depth,
        })

        # Find outgoing relationships from this table
        for rel in relationships:
            next_table = None
            next_column = None
            edge_from_col = None
            edge_to_col = None

            if rel["from_table"] == table:
                # Forward: get values from this table's FK column, search in target
                next_table = rel["to_table"]
                next_column = rel["to_column"]
                edge_from_col = rel["from_column"]
                edge_to_col = rel["to_column"]
                # Collect values from matching rows in the FK column
                fk_values = df.loc[mask, rel["from_column"]].dropna().unique()
            elif rel["to_table"] == table:
                # Reverse: this table is the target, find referencing rows
                next_table = rel["from_table"]
                next_column = rel["from_column"]
                edge_from_col = rel["to_column"]
                edge_to_col = rel["from_column"]
                fk_values = df.loc[mask, rel["to_column"]].dropna().unique()
            else:
                continue

            for fk_val in fk_values:
                fk_str = str(fk_val)
                next_key = f"{next_table}.{next_column}.{fk_str}"
                if next_key not in visited:
                    next_df = tables.get(next_table)
                    if next_df is not None:
                        next_mask = next_df[next_column].astype(str).eq(fk_str)
                        matched_rows = int(next_mask.sum())
                        if matched_rows > 0:
                            edges.append({
                                "from_table": table,
                                "from_column": edge_from_col,
                                "to_table": next_table,
                                "to_column": edge_to_col,
                                "value": fk_str,
                                "matched_rows": matched_rows,
                            })
                            queue.append((next_table, next_column, fk_str, depth + 1))

    return {
        "nodes": nodes,
        "edges": edges,
        "depth_reached": max(n["depth"] for n in nodes) if nodes else 0,
    }
```

### Backend: Route

```python
@app.post("/trace")
def trace_value_route():
    body = request.get_json()
    result = trace_value(
        tables=loaded_tables,
        relationships=detected_relationships,
        start_table=body["table"],
        start_column=body["column"],
        value=body["value"],
        max_depth=body.get("depth", 3),
    )
    return result
```

### Frontend: Requesting a Trace

```javascript
// trace.js

import { setTraceResults } from './state.js';
import { emit } from './events.js';

const traceValue = async (table, column, value, depth = 3) => {
    emit('traceStarted', { table, column, value });

    const response = await fetch('/trace', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ table, column, value, depth }),
    });
    const data = await response.json();

    setTraceResults(data);
    emit('traceResultsReady', { nodes: data.nodes.length, edges: data.edges.length });
};

export { traceValue };
```

---

## 3. Visual Highlighting

### Highlight Rules

| Element               | Normal state        | Search match state                          |
|-----------------------|---------------------|---------------------------------------------|
| Matching table border | default border      | 2px solid #F59E0B (gold glow)              |
| Matching column bg    | transparent         | #FEF3C7 (light yellow)                     |
| Trace path lines      | default stroke      | Bold (3px) + dash-animate                   |
| Non-matching tables   | full opacity        | opacity 0.15                                |
| Non-matching lines    | full opacity        | opacity 0.15                                |
| Match count badge     | hidden              | Numbered circle on table top-right corner   |

### Highlight Constants

```javascript
// Add to theme/constants

const SEARCH_HIGHLIGHT = {
    tableBorderColor: '#F59E0B',
    tableBorderWidth: 2,
    columnHighlightBg: '#FEF3C7',
    traceLineColor: '#F59E0B',
    traceLineWidth: 3,
    dimOpacity: 0.15,
    badgeBg: '#F59E0B',
    badgeTextColor: '#FFFFFF',
    badgeRadius: 10,
};
```

### Applying Highlights During Render

```javascript
// In the table block rendering module

const renderTableBlock = (ctx, table, searchState) => {
    const matches = searchState?.matches?.filter((m) => m.table === table.name) ?? [];
    const isMatch = matches.length > 0;
    const isTraceNode = searchState?.trace?.nodes?.some((n) => n.table === table.name) ?? false;
    const hasActiveSearch = searchState?.query != null;

    // Dim non-matching tables when search is active
    if (hasActiveSearch && !isMatch && !isTraceNode) {
        ctx.globalAlpha = SEARCH_HIGHLIGHT.dimOpacity;
    }

    // Draw table block (existing logic)
    drawTableBody(ctx, table);

    // Highlight border for matching tables
    if (isMatch || isTraceNode) {
        ctx.strokeStyle = SEARCH_HIGHLIGHT.tableBorderColor;
        ctx.lineWidth = SEARCH_HIGHLIGHT.tableBorderWidth;
        ctx.strokeRect(table.x, table.y, table.width, table.height);
    }

    // Highlight matching columns
    const matchedColumns = new Set(matches.map((m) => m.column));
    table.columns.forEach((col, index) => {
        if (matchedColumns.has(col.name)) {
            const colY = table.y + headerHeight + index * rowHeight;
            ctx.fillStyle = SEARCH_HIGHLIGHT.columnHighlightBg;
            ctx.fillRect(table.x, colY, table.width, rowHeight);
        }
    });

    // Draw match count badge
    if (isMatch) {
        drawMatchBadge(ctx, table, matches.length);
    }

    // Reset alpha
    ctx.globalAlpha = 1.0;
};

const drawMatchBadge = (ctx, table, count) => {
    const badgeX = table.x + table.width - 5;
    const badgeY = table.y - 5;
    const radius = SEARCH_HIGHLIGHT.badgeRadius;

    ctx.beginPath();
    ctx.arc(badgeX, badgeY, radius, 0, Math.PI * 2);
    ctx.fillStyle = SEARCH_HIGHLIGHT.badgeBg;
    ctx.fill();

    ctx.fillStyle = SEARCH_HIGHLIGHT.badgeTextColor;
    ctx.font = 'bold 11px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(String(count), badgeX, badgeY);
};
```

### Trace Path Line Rendering

```javascript
// In connections.js — within redrawAll()

const drawConnectionLine = (ctx, connection, traceEdges) => {
    const isTracePath = traceEdges?.some(
        (e) =>
            e.from_table === connection.fromTable &&
            e.to_table === connection.toTable
    ) ?? false;

    if (isTracePath) {
        ctx.strokeStyle = SEARCH_HIGHLIGHT.traceLineColor;
        ctx.lineWidth = SEARCH_HIGHLIGHT.traceLineWidth;
        ctx.setLineDash([8, 4]);
        // Animate: offset the dash over time
        ctx.lineDashOffset = -performance.now() / 50;
    } else if (hasActiveSearch) {
        ctx.globalAlpha = SEARCH_HIGHLIGHT.dimOpacity;
    }

    // Draw the line (existing anchor point logic)
    drawLine(ctx, connection.startPoint, connection.endPoint);

    // Reset
    ctx.setLineDash([]);
    ctx.globalAlpha = 1.0;
};
```

For animated dashes, request animation frames while a trace is active:

```javascript
let traceAnimationId = null;

const startTraceAnimation = () => {
    const animate = () => {
        redrawAll();
        traceAnimationId = requestAnimationFrame(animate);
    };
    traceAnimationId = requestAnimationFrame(animate);
};

const stopTraceAnimation = () => {
    if (traceAnimationId) {
        cancelAnimationFrame(traceAnimationId);
        traceAnimationId = null;
    }
};
```

---

## 4. Data Table Panel

### Panel Structure

The results panel is a collapsible sidebar or bottom drawer that appears when search results exist. It displays matching data rows grouped by table.

```html
<!-- Search results panel -->
<div class="search-results-panel search-results-panel--hidden" id="searchResultsPanel">
    <div class="search-results-panel__header">
        <span class="search-results-panel__title">Search Results</span>
        <span class="search-results-panel__count" id="searchResultCount">0</span>
        <button class="search-results-panel__close" id="searchResultsClose">X</button>
    </div>
    <div class="search-results-panel__filters">
        <select id="searchResultsGroupBy">
            <option value="table">Group by table</option>
            <option value="column">Group by column</option>
        </select>
        <input type="text" id="searchResultsFilter" placeholder="Filter results..." />
    </div>
    <div class="search-results-panel__body" id="searchResultsBody">
        <!-- Populated dynamically -->
    </div>
</div>
```

### Rendering Results

```javascript
// searchResultsPanel.js

import { getState } from './state.js';
import { subscribe } from './events.js';

const panelEl = document.getElementById('searchResultsPanel');
const bodyEl = document.getElementById('searchResultsBody');
const countEl = document.getElementById('searchResultCount');

const renderResults = () => {
    const { searchResults } = getState();
    if (!searchResults || searchResults.total === 0) {
        panelEl.classList.add('search-results-panel--hidden');
        return;
    }

    panelEl.classList.remove('search-results-panel--hidden');
    countEl.textContent = String(searchResults.total);

    // Group matches by table
    const grouped = groupByTable(searchResults.matches);

    bodyEl.innerHTML = '';
    for (const [tableName, matches] of Object.entries(grouped)) {
        const section = createTableSection(tableName, matches);
        bodyEl.appendChild(section);
    }
};

const groupByTable = (matches) => {
    const groups = {};
    for (const match of matches) {
        if (!groups[match.table]) {
            groups[match.table] = [];
        }
        groups[match.table].push(match);
    }
    return groups;
};

const createTableSection = (tableName, matches) => {
    const section = document.createElement('div');
    section.className = 'search-results-panel__table-group';

    const header = document.createElement('div');
    header.className = 'search-results-panel__table-header';
    header.textContent = `${tableName} (${matches.length})`;
    section.appendChild(header);

    for (const match of matches) {
        const row = document.createElement('div');
        row.className = 'search-results-panel__row';
        row.innerHTML = `
            <span class="search-results-panel__column-name">${match.column}</span>
            <span class="search-results-panel__value">${match.value}</span>
        `;
        row.addEventListener('click', () => {
            panToTable(match.table);
        });
        section.appendChild(row);
    }

    return section;
};

const panToTable = (tableName) => {
    // Emit event so the canvas module pans to the target table
    emit('panToTable', { table: tableName });
};

// Subscribe to search events
subscribe('searchResultsReady', renderResults);
subscribe('searchCleared', () => {
    panelEl.classList.add('search-results-panel--hidden');
    bodyEl.innerHTML = '';
});

export { renderResults };
```

### Pagination

For large result sets, paginate within each table group:

```javascript
const PAGE_SIZE = 20;

const createTableSection = (tableName, matches, page = 0) => {
    const start = page * PAGE_SIZE;
    const end = start + PAGE_SIZE;
    const pageMatches = matches.slice(start, end);
    const totalPages = Math.ceil(matches.length / PAGE_SIZE);

    // ... render pageMatches ...

    if (totalPages > 1) {
        const pager = document.createElement('div');
        pager.className = 'search-results-panel__pager';
        pager.innerHTML = `Page ${page + 1} of ${totalPages}`;

        const prevBtn = document.createElement('button');
        prevBtn.textContent = 'Prev';
        prevBtn.disabled = page === 0;
        prevBtn.addEventListener('click', () => {
            section.replaceWith(createTableSection(tableName, matches, page - 1));
        });

        const nextBtn = document.createElement('button');
        nextBtn.textContent = 'Next';
        nextBtn.disabled = page >= totalPages - 1;
        nextBtn.addEventListener('click', () => {
            section.replaceWith(createTableSection(tableName, matches, page + 1));
        });

        pager.prepend(prevBtn);
        pager.appendChild(nextBtn);
        section.appendChild(pager);
    }

    return section;
};
```

---

## 5. Search UI

### Search Bar Component

The search bar lives in the top toolbar, always visible.

```html
<div class="search-bar" id="searchBar">
    <input
        type="text"
        class="search-bar__input"
        id="searchInput"
        placeholder="Search for a value across all tables..."
    />
    <select class="search-bar__mode" id="searchMode">
        <option value="contains">Contains</option>
        <option value="exact">Exact match</option>
        <option value="starts_with">Starts with</option>
        <option value="regex">Regex</option>
    </select>
    <select class="search-bar__scope" id="searchScope">
        <option value="all">All tables</option>
        <option value="selected">Selected tables</option>
        <option value="id">ID columns only</option>
        <option value="email">Email columns only</option>
        <option value="date">Date columns only</option>
    </select>
    <span class="search-bar__badge search-bar__badge--hidden" id="searchBadge">0</span>
    <button class="search-bar__clear search-bar__clear--hidden" id="searchClear">Clear</button>
</div>
```

### Search Bar Logic

```javascript
// searchBar.js

import { searchAllTables } from './search.js';
import { clearSearchResults } from './state.js';
import { subscribe, emit } from './events.js';

const DEBOUNCE_MS = 300;

const inputEl = document.getElementById('searchInput');
const modeEl = document.getElementById('searchMode');
const scopeEl = document.getElementById('searchScope');
const badgeEl = document.getElementById('searchBadge');
const clearBtn = document.getElementById('searchClear');

let debounceTimer = null;

const buildScope = () => {
    const scopeValue = scopeEl.value;
    if (scopeValue === 'all') return null;
    if (scopeValue === 'selected') {
        // Read selected tables from state
        const { selectedTables } = getState();
        return { tables: selectedTables };
    }
    // Column type filters
    return { column_type: scopeValue };
};

const onInputChange = () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
        const query = inputEl.value.trim();
        const mode = modeEl.value;
        const scope = buildScope();
        searchAllTables(query, mode, scope);
    }, DEBOUNCE_MS);
};

const onClear = () => {
    inputEl.value = '';
    clearSearchResults();
    emit('searchCleared');
    badgeEl.classList.add('search-bar__badge--hidden');
    clearBtn.classList.add('search-bar__clear--hidden');
};

// Update badge when results arrive
subscribe('searchResultsReady', ({ total }) => {
    badgeEl.textContent = String(total);
    badgeEl.classList.remove('search-bar__badge--hidden');
    clearBtn.classList.remove('search-bar__clear--hidden');
});

subscribe('searchCleared', () => {
    badgeEl.classList.add('search-bar__badge--hidden');
    clearBtn.classList.add('search-bar__clear--hidden');
});

inputEl.addEventListener('input', onInputChange);
modeEl.addEventListener('change', onInputChange);
scopeEl.addEventListener('change', onInputChange);
clearBtn.addEventListener('click', onClear);
```

### CSS

```css
.search-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    background: var(--toolbar-bg);
    border-bottom: 1px solid var(--border-color);
}

.search-bar__input {
    flex: 1;
    min-width: 240px;
    padding: 6px 10px;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    font-size: 14px;
}

.search-bar__input:focus {
    outline: none;
    border-color: var(--primary-color);
    box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.2);
}

.search-bar__mode,
.search-bar__scope {
    padding: 6px 8px;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    font-size: 13px;
}

.search-bar__badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 22px;
    height: 22px;
    padding: 0 6px;
    background: #F59E0B;
    color: #FFFFFF;
    border-radius: 11px;
    font-size: 12px;
    font-weight: bold;
}

.search-bar__badge--hidden {
    display: none;
}

.search-bar__clear {
    padding: 4px 10px;
    background: transparent;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    cursor: pointer;
    font-size: 13px;
}

.search-bar__clear--hidden {
    display: none;
}
```

---

## 6. Flow Visualization

### Sequential Hop Animation

After trace results load, the "Show data flow" button triggers an animated sequence that highlights each hop in the trace path one at a time.

```javascript
// flowAnimation.js

import { getState } from './state.js';
import { emit } from './events.js';

const HOP_DELAY_MS = 200;

const animateDataFlow = () => {
    const { traceResults } = getState();
    if (!traceResults || traceResults.edges.length === 0) return;

    // Sort edges by depth (source depth)
    const sortedEdges = [...traceResults.edges];
    const nodeDepthMap = {};
    for (const node of traceResults.nodes) {
        nodeDepthMap[node.table] = node.depth;
    }
    sortedEdges.sort(
        (a, b) => (nodeDepthMap[a.from_table] ?? 0) - (nodeDepthMap[b.from_table] ?? 0)
    );

    let currentStep = 0;

    const step = () => {
        if (currentStep >= sortedEdges.length) {
            emit('flowAnimationComplete');
            return;
        }

        const edge = sortedEdges[currentStep];
        emit('flowAnimationStep', {
            step: currentStep,
            edge,
            totalSteps: sortedEdges.length,
        });

        currentStep++;
        setTimeout(step, HOP_DELAY_MS);
    };

    emit('flowAnimationStarted', { totalSteps: sortedEdges.length });
    step();
};

export { animateDataFlow };
```

### Rendering Animated Hops

```javascript
// In connections.js — listen for animation steps

subscribe('flowAnimationStep', ({ step, edge }) => {
    // Mark this edge as "active" in a transient render set
    activeFlowEdges.add(`${edge.from_table}->${edge.to_table}`);
    redrawAll();
});

subscribe('flowAnimationComplete', () => {
    // Keep all edges highlighted; they clear on search clear
});

subscribe('searchCleared', () => {
    activeFlowEdges.clear();
    stopTraceAnimation();
    redrawAll();
});
```

### Tooltip on Hover (Optional)

When hovering over a traced connection line, show a mini data table:

```javascript
// In canvas event handler

const onCanvasMouseMove = (e) => {
    const { traceResults } = getState();
    if (!traceResults) return;

    const hoveredEdge = findEdgeAtPoint(e.offsetX, e.offsetY, traceResults.edges);
    if (hoveredEdge) {
        showEdgeTooltip(e.offsetX, e.offsetY, hoveredEdge);
    } else {
        hideEdgeTooltip();
    }
};
```

---

## 7. Backend API Summary

| Endpoint        | Method | Body                                        | Response                                     |
|-----------------|--------|---------------------------------------------|----------------------------------------------|
| `/search`       | POST   | `{query, mode, scope}`                      | `{query, mode, total, matches: [...]}`       |
| `/trace`        | POST   | `{table, column, value, depth}`             | `{nodes: [...], edges: [...], depth_reached}` |

### Data Caching

```python
# In app.py or a dedicated cache module

# Tables are loaded once on upload and kept in memory
loaded_tables: dict[str, pd.DataFrame] = {}
detected_relationships: list[dict] = []

@app.post("/upload")
def upload_csv():
    # ... parse CSV, detect keys, detect relationships ...
    loaded_tables[table_name] = df
    detected_relationships.extend(new_relationships)
    return {"status": "ok", "table": table_name, "rows": len(df)}
```

---

## 8. Performance Considerations

### Result Limits

- Default max 100 matches per table (configurable via query param)
- Total result cap: 1000 matches across all tables
- Trace depth default: 3 hops (user-configurable, hard cap at 6)

### Debounce and Cancellation

```javascript
// Search input: 300ms trailing-edge debounce
// Each new search aborts the previous fetch via AbortController
// Trace requests are not debounced (explicit button click)
```

### Large Dataset Handling

```python
def search_all_tables(tables, query, mode, scope, max_per_table=100, max_total=1000):
    results = []
    for table_name, df in tables.items():
        if len(results) >= max_total:
            break
        # ... search logic with early termination ...
    return results
```

### Frontend Rendering Performance

- Redraw only on final debounced search result (not on every keystroke)
- Trace animation uses `requestAnimationFrame` for smooth dash animation
- Stop animation loop when trace is cleared
- Badge and panel updates are DOM-only (no canvas redraw needed)

---

## 9. Integration with Diagram

### State Shape

```javascript
// In state.js — add these keys

const initialState = {
    // ... existing state ...

    // Search state
    searchQuery: null,          // current search string or null
    searchMode: 'contains',     // 'exact' | 'contains' | 'starts_with' | 'regex'
    searchResults: null,        // {query, mode, total, matches: [...]} or null
    traceResults: null,         // {nodes: [...], edges: [...], depth_reached} or null
};

const setSearchResults = (results) => {
    state.searchResults = results;
    state.searchQuery = results.query;
    state.searchMode = results.mode;
    emit('stateChanged', { key: 'searchResults' });
};

const clearSearchResults = () => {
    state.searchQuery = null;
    state.searchResults = null;
    state.traceResults = null;
    emit('stateChanged', { key: 'searchResults' });
};

const setTraceResults = (trace) => {
    state.traceResults = trace;
    emit('stateChanged', { key: 'traceResults' });
};
```

### Event Flow

```
User types in search bar
  → (300ms debounce)
  → searchAllTables() called
  → POST /search
  → setSearchResults() updates state
  → emit('searchResultsReady')
  → connections.redrawAll()        ← IRON RULE
  → searchResultsPanel.renderResults()
  → search bar badge updates

User clicks "Show data flow"
  → traceValue() called
  → POST /trace
  → setTraceResults() updates state
  → emit('traceResultsReady')
  → connections.redrawAll()        ← IRON RULE
  → startTraceAnimation()

User clicks "Clear"
  → clearSearchResults()
  → emit('searchCleared')
  → connections.redrawAll()        ← IRON RULE
  → stopTraceAnimation()
  → panel hides, badges hide, all highlights removed
```

### Canvas Redraw Contract

The search system is a consumer of the existing redraw pipeline. During `redrawAll()`:

1. Read `state.searchResults` and `state.traceResults`
2. Pass them into table block rendering (for highlights, badges, dimming)
3. Pass them into connection line rendering (for bold/animate trace lines, dim others)
4. No new redraw trigger needed — search state changes emit `stateChanged`, which already triggers `redrawAll()`

### Search as a Special Filter

Search results integrate with the existing filter system:

- An active search acts like a filter: non-matching items are dimmed
- If both a search and a filter are active, apply both (intersection)
- Clearing search does not clear user-set filters, and vice versa
- The filter system reads `searchResults` from state alongside its own filter criteria
