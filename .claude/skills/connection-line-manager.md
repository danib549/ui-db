# Skill: Connection Line Manager

## When to Use

Apply this skill when implementing or modifying connection lines between table blocks on the diagram canvas. This covers the full pipeline: backend relationship detection from CSV data, anchor point calculation, bezier curve rendering, cardinality notation, line styling, hover/highlight behavior, and connection tracing. Use this guide whenever working on `connections.js`, `key_detector.py`, `relationship_analyzer.py`, or any module that touches how tables are linked visually.

---

## 1. Relationship Detection (Backend)

The Python backend analyzes uploaded CSV data to detect relationships between tables. All detection logic lives in dedicated backend modules — never in frontend code.

### Column Name Matching

Match foreign key columns to primary key columns using naming conventions:

```python
from pathlib import Path

# Suffix patterns that indicate a foreign key
FK_SUFFIXES: list[str] = ["_id", "_ref", "_key"]

def find_fk_candidates(column_name: str) -> list[str]:
    """Return possible target table names from a column name.

    'user_id'   -> ['user', 'users']
    'order_ref' -> ['order', 'orders']
    'parent_key' -> ['parent', 'parents']
    """
    for suffix in FK_SUFFIXES:
        if column_name.endswith(suffix):
            base = column_name[: -len(suffix)]
            return [base, base + "s"]
    return []


def match_columns(
    source_table: str,
    source_columns: list[str],
    all_tables: dict[str, list[str]],
) -> list[dict]:
    """Detect FK -> PK relationships by column name matching.

    Returns a list of relationship dicts:
    {
        'source_table': str,
        'source_column': str,
        'target_table': str,
        'target_column': str,
        'confidence': 'high' | 'medium' | 'low',
    }
    """
    relationships: list[dict] = []

    for col in source_columns:
        candidates = find_fk_candidates(col)
        for target_table, target_columns in all_tables.items():
            if target_table == source_table:
                continue
            # High confidence: exact table_id -> table.id pattern
            if target_table in candidates and "id" in target_columns:
                relationships.append({
                    "source_table": source_table,
                    "source_column": col,
                    "target_table": target_table,
                    "target_column": "id",
                    "confidence": "high",
                })
            # Medium confidence: partial name overlap
            elif target_table in candidates:
                pk_candidates = [c for c in target_columns if c.endswith("_id") or c == "id"]
                if pk_candidates:
                    relationships.append({
                        "source_table": source_table,
                        "source_column": col,
                        "target_table": target_table,
                        "target_column": pk_candidates[0],
                        "confidence": "medium",
                    })

    return relationships
```

### Cardinality Inference

Determine 1:1 vs 1:N by checking uniqueness of the FK column values:

```python
import pandas as pd


def infer_cardinality(
    source_df: pd.DataFrame,
    source_column: str,
    target_df: pd.DataFrame,
    target_column: str,
) -> str:
    """Infer cardinality from actual data values.

    Returns: 'one-to-one' | 'one-to-many' | 'many-to-many'
    """
    source_unique = source_df[source_column].nunique() == len(source_df)
    target_unique = target_df[target_column].nunique() == len(target_df)

    if source_unique and target_unique:
        return "one-to-one"
    if target_unique and not source_unique:
        return "one-to-many"
    return "many-to-many"
```

### Many-to-Many Detection (Junction Tables)

A junction table typically has two or more FK columns and few or no non-key columns:

```python
def detect_junction_table(
    table_name: str,
    columns: list[str],
    relationships: list[dict],
) -> bool:
    """Detect if a table is a junction/bridge table for an M:N relationship.

    Heuristics:
    - Table has 2+ FK columns (columns ending in _id, _ref, _key)
    - Non-FK columns are few (0-2) or are only timestamps/metadata
    """
    fk_columns = [c for c in columns if any(c.endswith(s) for s in FK_SUFFIXES)]
    non_fk_columns = [c for c in columns if c not in fk_columns and c != "id"]
    metadata_names = {"created_at", "updated_at", "deleted_at", "id"}

    non_fk_meaningful = [c for c in non_fk_columns if c not in metadata_names]

    return len(fk_columns) >= 2 and len(non_fk_meaningful) <= 1
```

### Self-Referential Relationships

Detect when a FK column points back to the same table:

```python
def detect_self_reference(
    table_name: str,
    columns: list[str],
) -> list[dict]:
    """Detect self-referential FKs like employees.manager_id -> employees.id."""
    self_refs: list[dict] = []
    if "id" not in columns:
        return self_refs

    for col in columns:
        candidates = find_fk_candidates(col)
        if table_name in candidates:
            self_refs.append({
                "source_table": table_name,
                "source_column": col,
                "target_table": table_name,
                "target_column": "id",
                "confidence": "high",
                "self_referential": True,
            })
    return self_refs
```

### Confidence Scoring

Assign confidence levels to each detected relationship:

| Confidence | Criteria | Example |
|------------|----------|---------|
| **High** | Exact `table_id` -> `table.id` pattern, data types match | `orders.user_id` -> `users.id` |
| **Medium** | Partial name match, FK suffix present but target column ambiguous | `orders.customer_ref` -> `customers.customer_id` |
| **Low** | Data type match only, no naming convention match | `orders.status` -> `statuses.id` (type-only) |

```python
def score_relationship(
    source_col: str,
    target_table: str,
    target_col: str,
    source_dtype: str,
    target_dtype: str,
) -> str:
    """Score confidence of a detected relationship."""
    candidates = find_fk_candidates(source_col)

    if target_table in candidates and target_col == "id":
        return "high"
    if target_table in candidates:
        return "medium"
    if source_dtype == target_dtype:
        return "low"
    return "low"
```

---

## 2. Anchor Point Calculation

Each connection attaches to a specific column row in its source and target table blocks. Anchor points determine exactly where the line starts and ends.

### Rules

1. Anchor point = left or right edge of the column row, at vertical center of that row.
2. Choose the edge (left vs right) that produces the shorter horizontal path. Compare block center X positions: if source is left of target, source anchors on right edge and target on left edge, and vice versa.
3. When a block is collapsed, anchor at the block edge vertical center (no specific row).

### Calculation

```javascript
const ROW_HEIGHT = 28;
const HEADER_HEIGHT = 36;
const BLOCK_MIN_WIDTH = 200;

/**
 * Calculate the anchor point for a connection endpoint.
 * @param {Object} block - { x, y, width, height, collapsed }
 * @param {number} columnIndex - Zero-based index of the column row
 * @param {'left'|'right'} side - Which edge to anchor on
 * @returns {{ x: number, y: number }}
 */
function calculateAnchorPoint(block, columnIndex, side) {
  const x = side === 'left' ? block.x : block.x + block.width;

  if (block.collapsed) {
    const y = block.y + HEADER_HEIGHT / 2;
    return { x, y };
  }

  const y = block.y + HEADER_HEIGHT + (columnIndex * ROW_HEIGHT) + (ROW_HEIGHT / 2);
  return { x, y };
}

/**
 * Determine which side (left/right) each block should anchor on
 * to produce the shorter path.
 * @param {Object} sourceBlock - Source block position and dimensions
 * @param {Object} targetBlock - Target block position and dimensions
 * @returns {{ sourceSide: 'left'|'right', targetSide: 'left'|'right' }}
 */
function chooseSides(sourceBlock, targetBlock) {
  const sourceCenterX = sourceBlock.x + sourceBlock.width / 2;
  const targetCenterX = targetBlock.x + targetBlock.width / 2;

  if (sourceCenterX <= targetCenterX) {
    return { sourceSide: 'right', targetSide: 'left' };
  }
  return { sourceSide: 'left', targetSide: 'right' };
}
```

### Column Index Lookup

The column index is the row's position in the table block (zero-based, after the header). Read from state — never cache.

```javascript
/**
 * Get the zero-based row index of a column within its table block.
 * @param {string} tableName
 * @param {string} columnName
 * @returns {number}
 */
function getColumnIndex(tableName, columnName) {
  const table = AppState.tables.find((t) => t.name === tableName);
  if (!table) return 0;
  const index = table.columns.findIndex((c) => c.name === columnName);
  return index >= 0 ? index : 0;
}
```

---

## 3. Bezier Curve Rendering

All connection lines use cubic bezier curves for a smooth, professional appearance. Lines exit horizontally from the block edge and curve toward the target.

### Curve Construction

```
Source anchor (x1, y1)
    -> Control point 1 (x1 + offset, y1)    [extends horizontally from source]
    -> Control point 2 (x2 - offset, y2)    [extends horizontally toward target]
    -> Target anchor (x2, y2)
```

### Control Point Offset

The offset scales with distance but is capped to prevent extreme curves:

```javascript
/**
 * Compute bezier control point offset based on distance between anchors.
 * @param {Object} source - { x, y }
 * @param {Object} target - { x, y }
 * @returns {number}
 */
function computeControlOffset(source, target) {
  const distance = Math.abs(target.x - source.x);
  return Math.min(100, distance * 0.4);
}
```

### Drawing a Connection Line

```javascript
/**
 * Draw a single connection line on the canvas.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Object} source - { x, y } anchor point
 * @param {Object} target - { x, y } anchor point
 * @param {Object} style - { color, width, dash }
 */
function drawConnectionLine(ctx, source, target, style) {
  const offset = computeControlOffset(source, target);
  const cp1 = { x: source.x + offset, y: source.y };
  const cp2 = { x: target.x - offset, y: target.y };

  ctx.beginPath();
  ctx.moveTo(source.x, source.y);
  ctx.bezierCurveTo(cp1.x, cp1.y, cp2.x, cp2.y, target.x, target.y);

  ctx.strokeStyle = style.color;
  ctx.lineWidth = style.width;

  if (style.dash) {
    ctx.setLineDash(style.dash);
  } else {
    ctx.setLineDash([]);
  }

  ctx.stroke();
  ctx.setLineDash([]);
}
```

### Self-Referential Loop Curve

When source and target are the same table, draw a loop that arcs above or below the block:

```javascript
/**
 * Draw a self-referential loop for a table that references itself.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Object} sourceAnchor - { x, y } FK row anchor (right edge)
 * @param {Object} targetAnchor - { x, y } PK row anchor (right edge)
 * @param {Object} style - { color, width, dash }
 */
function drawSelfReferenceLoop(ctx, sourceAnchor, targetAnchor, style) {
  const loopOffset = 60;
  const midY = (sourceAnchor.y + targetAnchor.y) / 2;

  ctx.beginPath();
  ctx.moveTo(sourceAnchor.x, sourceAnchor.y);
  ctx.bezierCurveTo(
    sourceAnchor.x + loopOffset, sourceAnchor.y,
    targetAnchor.x + loopOffset, targetAnchor.y,
    targetAnchor.x, targetAnchor.y
  );

  ctx.strokeStyle = style.color;
  ctx.lineWidth = style.width;

  if (style.dash) {
    ctx.setLineDash(style.dash);
  } else {
    ctx.setLineDash([]);
  }

  ctx.stroke();
  ctx.setLineDash([]);
}
```

---

## 4. Cardinality Notation (Crow's Foot)

Draw cardinality indicators at the anchor points after the bezier curve is drawn.

### Notation Reference

| Symbol | Meaning | Drawing |
|--------|---------|---------|
| `1` (mandatory) | Exactly one | Filled circle (r=4px) + perpendicular tick |
| `N` (mandatory) | Many | Three short lines fanning out (crow's foot) |
| `0..1` (optional one) | Zero or one | Open circle (r=4px) + perpendicular tick |
| `0..N` (optional many) | Zero or many | Open circle (r=4px) + crow's foot |

### Drawing Functions

```javascript
const TICK_LENGTH = 8;
const CIRCLE_RADIUS = 4;
const CROW_FOOT_SPREAD = 8;
const CROW_FOOT_LENGTH = 12;

/**
 * Draw the "one" side indicator: filled circle + perpendicular tick.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Object} anchor - { x, y }
 * @param {'left'|'right'} side - Which edge the anchor is on
 * @param {string} color
 */
function drawOneSide(ctx, anchor, side, color) {
  const dir = side === 'right' ? 1 : -1;

  // Filled circle at anchor
  ctx.beginPath();
  ctx.arc(anchor.x, anchor.y, CIRCLE_RADIUS, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();

  // Perpendicular tick mark
  const tickX = anchor.x + (dir * (CIRCLE_RADIUS + 4));
  ctx.beginPath();
  ctx.moveTo(tickX, anchor.y - TICK_LENGTH / 2);
  ctx.lineTo(tickX, anchor.y + TICK_LENGTH / 2);
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.stroke();
}

/**
 * Draw the "many" side indicator: crow's foot (3 lines fanning out).
 * @param {CanvasRenderingContext2D} ctx
 * @param {Object} anchor - { x, y }
 * @param {'left'|'right'} side - Which edge the anchor is on
 * @param {string} color
 */
function drawManySide(ctx, anchor, side, color) {
  const dir = side === 'left' ? -1 : 1;
  const tipX = anchor.x;
  const baseX = anchor.x + (dir * CROW_FOOT_LENGTH);

  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;

  // Center prong
  ctx.beginPath();
  ctx.moveTo(tipX, anchor.y);
  ctx.lineTo(baseX, anchor.y);
  ctx.stroke();

  // Upper prong
  ctx.beginPath();
  ctx.moveTo(tipX, anchor.y);
  ctx.lineTo(baseX, anchor.y - CROW_FOOT_SPREAD);
  ctx.stroke();

  // Lower prong
  ctx.beginPath();
  ctx.moveTo(tipX, anchor.y);
  ctx.lineTo(baseX, anchor.y + CROW_FOOT_SPREAD);
  ctx.stroke();
}

/**
 * Draw an optional indicator: open circle before the main notation.
 * @param {CanvasRenderingContext2D} ctx
 * @param {Object} anchor - { x, y }
 * @param {'left'|'right'} side
 * @param {string} color
 */
function drawOptionalCircle(ctx, anchor, side, color) {
  const dir = side === 'right' ? 1 : -1;
  const circleX = anchor.x + (dir * (CIRCLE_RADIUS + 2));

  ctx.beginPath();
  ctx.arc(circleX, anchor.y, CIRCLE_RADIUS, 0, Math.PI * 2);
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.stroke();
}
```

---

## 5. Line Coloring and Styling

### Color Constants

```javascript
const CONNECTION_COLORS = {
  'one-to-one':   '#3B82F6',  // Blue
  'one-to-many':  '#22C55E',  // Green
  'many-to-many': '#F97316',  // Orange
  'self':         '#A78BFA',  // Purple
};

const DIMMED_COLOR = '#D1D5DB';  // Gray
```

### Style Resolution

Determine the visual style for a connection based on its type and the current filter/hover state:

```javascript
/**
 * Resolve the drawing style for a connection line.
 * @param {Object} connection - { type, source, target }
 * @param {Object} interactionState - { hoveredTable, hoveredColumn, activeFilters }
 * @returns {{ color: string, width: number, dash: number[], opacity: number }}
 */
function resolveConnectionStyle(connection, interactionState) {
  const isSelfRef = connection.source.table === connection.target.table;
  const baseColor = isSelfRef
    ? CONNECTION_COLORS['self']
    : CONNECTION_COLORS[connection.type];

  // Highlighted: active filter match or hover target
  if (isHighlighted(connection, interactionState)) {
    return { color: baseColor, width: 2.5, dash: [], opacity: 1.0 };
  }

  // Dimmed: filtered out or non-hovered during a hover
  if (isDimmed(connection, interactionState)) {
    return { color: DIMMED_COLOR, width: 1, dash: [4, 4], opacity: 0.15 };
  }

  // Default: normal rendering
  return { color: baseColor, width: 1.5, dash: [], opacity: 1.0 };
}

/**
 * Check if a connection is actively highlighted.
 */
function isHighlighted(connection, interactionState) {
  const { hoveredTable, hoveredColumn, activeFilters } = interactionState;

  if (hoveredColumn) {
    return (
      (connection.source.table === hoveredColumn.table &&
        connection.source.column === hoveredColumn.column) ||
      (connection.target.table === hoveredColumn.table &&
        connection.target.column === hoveredColumn.column)
    );
  }

  if (hoveredTable) {
    return (
      connection.source.table === hoveredTable ||
      connection.target.table === hoveredTable
    );
  }

  if (activeFilters && activeFilters.length > 0) {
    return activeFilters.some((f) => matchesFilter(connection, f));
  }

  return false;
}

/**
 * Check if a connection should be dimmed.
 */
function isDimmed(connection, interactionState) {
  const { hoveredTable, hoveredColumn, activeFilters } = interactionState;
  const hasActiveInteraction = hoveredTable || hoveredColumn ||
    (activeFilters && activeFilters.length > 0);

  if (!hasActiveInteraction) return false;
  return !isHighlighted(connection, interactionState);
}
```

### Stroke Width Summary

| State | Width | Dash | Opacity |
|-------|-------|------|---------|
| Default | 1.5px | Solid | 1.0 |
| Hover (on line) | 3px | Solid | 1.0 |
| Highlighted (filter/hover match) | 2.5px | Solid | 1.0 |
| Dimmed (filtered out) | 1px | `[4, 4]` dashed | 0.15 |

---

## 6. Hover and Highlight Behavior

### Interaction Rules

1. **Hover table block**: Highlight all connection lines attached to that table. Dim all other lines to opacity 0.25.
2. **Hover column row**: Highlight only the connection lines for that specific column. Dim everything else to opacity 0.25.
3. **Hover connection line**: Highlight both endpoint columns and their parent table blocks. Dim all non-related elements to opacity 0.25.
4. **No hover**: All elements render at default opacity.

### Hit Detection for Lines

Use distance-from-curve calculation to detect hover on bezier lines:

```javascript
const LINE_HIT_THRESHOLD = 6;  // pixels

/**
 * Check if a point is close enough to a bezier curve to count as a hover.
 * Sample the curve at intervals and find the minimum distance.
 * @param {Object} point - { x, y } mouse position
 * @param {Object} source - { x, y } curve start
 * @param {Object} cp1 - { x, y } control point 1
 * @param {Object} cp2 - { x, y } control point 2
 * @param {Object} target - { x, y } curve end
 * @returns {boolean}
 */
function isPointNearBezier(point, source, cp1, cp2, target) {
  const steps = 20;
  let minDist = Infinity;

  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const bezierPoint = cubicBezierPoint(t, source, cp1, cp2, target);
    const dist = Math.hypot(point.x - bezierPoint.x, point.y - bezierPoint.y);
    minDist = Math.min(minDist, dist);
  }

  return minDist <= LINE_HIT_THRESHOLD;
}

/**
 * Evaluate a cubic bezier curve at parameter t.
 * @param {number} t - Parameter [0, 1]
 * @param {Object} p0 - Start point
 * @param {Object} p1 - Control point 1
 * @param {Object} p2 - Control point 2
 * @param {Object} p3 - End point
 * @returns {{ x: number, y: number }}
 */
function cubicBezierPoint(t, p0, p1, p2, p3) {
  const mt = 1 - t;
  const mt2 = mt * mt;
  const t2 = t * t;

  return {
    x: mt2 * mt * p0.x + 3 * mt2 * t * p1.x + 3 * mt * t2 * p2.x + t2 * t * p3.x,
    y: mt2 * mt * p0.y + 3 * mt2 * t * p1.y + 3 * mt * t2 * p2.y + t2 * t * p3.y,
  };
}
```

### Applying Opacity

```javascript
/**
 * Apply opacity to a table block based on highlight state.
 * @param {CanvasRenderingContext2D} ctx
 * @param {string} tableName
 * @param {Object} interactionState
 */
function applyBlockOpacity(ctx, tableName, interactionState) {
  const { hoveredTable, hoveredColumn, hoveredConnection } = interactionState;
  const hasActiveHover = hoveredTable || hoveredColumn || hoveredConnection;

  if (!hasActiveHover) {
    ctx.globalAlpha = 1.0;
    return;
  }

  const isRelated =
    tableName === hoveredTable ||
    (hoveredColumn && hoveredColumn.table === tableName) ||
    (hoveredConnection && (
      hoveredConnection.source.table === tableName ||
      hoveredConnection.target.table === tableName
    ));

  ctx.globalAlpha = isRelated ? 1.0 : 0.25;
}
```

---

## 7. The `redrawAll()` Contract

This is the core function in `connections.js`. It is called on every state change without exception.

### Requirements

1. Clear all existing line drawings.
2. Read current state: positions, connections, filters, visibility.
3. For each connection: check visibility, calculate anchors, compute bezier, apply style, draw.
4. Idempotent: safe to call any number of times with identical results.
5. Never cache: always compute from current state.
6. Never reuse previous calculations.

### Implementation Pattern

```javascript
/**
 * Redraw all connection lines from scratch.
 * Called on EVERY state change. No exceptions.
 */
function redrawAll() {
  const ctx = getConnectionLayerContext();
  const { width, height } = ctx.canvas;

  // 1. Clear everything
  ctx.clearRect(0, 0, width, height);

  // 2. Read current state
  const connections = AppState.connections;
  const positions = AppState.positions;
  const filters = AppState.filters;
  const viewport = AppState.viewport;
  const interactionState = {
    hoveredTable: AppState.hoveredTable,
    hoveredColumn: AppState.hoveredColumn,
    hoveredConnection: AppState.hoveredConnection,
    activeFilters: AppState.activeFilters,
  };

  // 3. Apply viewport transform
  ctx.save();
  ctx.translate(viewport.x, viewport.y);
  ctx.scale(viewport.zoom, viewport.zoom);

  // 4. Draw each connection
  for (const connection of connections) {
    // 4a. Check visibility — both blocks must be visible
    const sourceBlock = positions[connection.source.table];
    const targetBlock = positions[connection.target.table];
    if (!sourceBlock || !targetBlock) continue;
    if (isBothHidden(connection, filters)) continue;

    // 4b. Calculate anchors from CURRENT positions
    const { sourceSide, targetSide } = chooseSides(sourceBlock, targetBlock);
    const sourceIndex = getColumnIndex(connection.source.table, connection.source.column);
    const targetIndex = getColumnIndex(connection.target.table, connection.target.column);
    const sourceAnchor = calculateAnchorPoint(sourceBlock, sourceIndex, sourceSide);
    const targetAnchor = calculateAnchorPoint(targetBlock, targetIndex, targetSide);

    // 4c. Resolve style
    const style = resolveConnectionStyle(connection, interactionState);

    // 4d. Apply opacity
    ctx.globalAlpha = style.opacity;

    // 4e. Draw the line
    const isSelfRef = connection.source.table === connection.target.table;
    if (isSelfRef) {
      drawSelfReferenceLoop(ctx, sourceAnchor, targetAnchor, style);
    } else {
      drawConnectionLine(ctx, sourceAnchor, targetAnchor, style);
    }

    // 4f. Draw cardinality indicators
    drawCardinalityIndicators(ctx, connection, sourceAnchor, targetAnchor, sourceSide, targetSide, style.color);
  }

  // 5. Restore context
  ctx.restore();
  ctx.globalAlpha = 1.0;
}

/**
 * Draw cardinality indicators at both endpoints of a connection.
 */
function drawCardinalityIndicators(ctx, connection, sourceAnchor, targetAnchor, sourceSide, targetSide, color) {
  switch (connection.type) {
    case 'one-to-one':
      drawOneSide(ctx, sourceAnchor, sourceSide, color);
      drawOneSide(ctx, targetAnchor, targetSide, color);
      break;
    case 'one-to-many':
      drawOneSide(ctx, targetAnchor, targetSide, color);   // PK side = "one"
      drawManySide(ctx, sourceAnchor, sourceSide, color);   // FK side = "many"
      break;
    case 'many-to-many':
      drawManySide(ctx, sourceAnchor, sourceSide, color);
      drawManySide(ctx, targetAnchor, targetSide, color);
      break;
    default:
      break;
  }
}
```

### Event Subscriptions

```javascript
// connections.js must subscribe to ALL state change events
const REDRAW_EVENTS = [
  'tableMoved',
  'tableAdded',
  'tableRemoved',
  'filterChanged',
  'layoutChanged',
  'connectionAdded',
  'connectionRemoved',
  'viewportChanged',
  'stateReset',
  'blockCollapsed',
  'blockExpanded',
];

REDRAW_EVENTS.forEach((event) => {
  EventBus.on(event, () => redrawAll());
});

// Debounce rapid drag events with trailing edge guarantee
const debouncedRedraw = trailingDebounce(redrawAll, 16);
EventBus.on('tableDragging', () => debouncedRedraw());
```

---

## 8. Connection Tracing

Connection tracing allows users to explore how tables are related beyond direct connections.

### Click to Highlight Direct Connections

```javascript
/**
 * Get all connections directly attached to a table.
 * @param {string} tableName
 * @returns {Object[]} Array of connection objects
 */
function getDirectConnections(tableName) {
  return AppState.connections.filter(
    (c) => c.source.table === tableName || c.target.table === tableName
  );
}
```

### Trace Path Between Two Tables

Find and highlight the shortest connection chain between two tables:

```javascript
/**
 * Find the shortest path between two tables via connections.
 * Uses BFS on the connection graph.
 * @param {string} startTable
 * @param {string} endTable
 * @returns {string[]|null} Array of table names in the path, or null if no path
 */
function findConnectionPath(startTable, endTable) {
  const adjacency = buildAdjacencyMap();
  const visited = new Set();
  const queue = [[startTable]];

  while (queue.length > 0) {
    const path = queue.shift();
    const current = path[path.length - 1];

    if (current === endTable) return path;
    if (visited.has(current)) continue;
    visited.add(current);

    const neighbors = adjacency.get(current) || [];
    for (const neighbor of neighbors) {
      if (!visited.has(neighbor)) {
        queue.push([...path, neighbor]);
      }
    }
  }

  return null;
}

/**
 * Build an adjacency map from the current connections.
 * @returns {Map<string, string[]>}
 */
function buildAdjacencyMap() {
  const map = new Map();

  for (const conn of AppState.connections) {
    const src = conn.source.table;
    const tgt = conn.target.table;

    if (!map.has(src)) map.set(src, []);
    if (!map.has(tgt)) map.set(tgt, []);
    map.get(src).push(tgt);
    map.get(tgt).push(src);
  }

  return map;
}
```

### Depth-Limited Traversal

Show connections up to N levels deep from a selected table:

```javascript
/**
 * Get all tables within N connection hops of the given table.
 * @param {string} tableName - Starting table
 * @param {number} maxDepth - Maximum number of hops
 * @returns {Map<string, number>} Map of tableName -> depth
 */
function getTablesWithinDepth(tableName, maxDepth) {
  const result = new Map();
  result.set(tableName, 0);
  const adjacency = buildAdjacencyMap();
  const queue = [{ table: tableName, depth: 0 }];

  while (queue.length > 0) {
    const { table, depth } = queue.shift();
    if (depth >= maxDepth) continue;

    const neighbors = adjacency.get(table) || [];
    for (const neighbor of neighbors) {
      if (!result.has(neighbor)) {
        result.set(neighbor, depth + 1);
        queue.push({ table: neighbor, depth: depth + 1 });
      }
    }
  }

  return result;
}
```

### Transitive Highlighting

When a path is found between two tables, highlight all connections along the chain:

```javascript
/**
 * Get all connections that form the path between tables.
 * @param {string[]} path - Ordered array of table names in the path
 * @returns {Object[]} Connections along the path
 */
function getConnectionsAlongPath(path) {
  const pathConnections = [];

  for (let i = 0; i < path.length - 1; i++) {
    const tableA = path[i];
    const tableB = path[i + 1];

    const conn = AppState.connections.find(
      (c) =>
        (c.source.table === tableA && c.target.table === tableB) ||
        (c.source.table === tableB && c.target.table === tableA)
    );

    if (conn) pathConnections.push(conn);
  }

  return pathConnections;
}

/**
 * Activate trace mode: highlight the chain between two tables.
 * All connections along the path are highlighted; everything else is dimmed.
 * @param {string} startTable
 * @param {string} endTable
 */
function activateTracePath(startTable, endTable) {
  const path = findConnectionPath(startTable, endTable);

  if (!path) {
    // No connection chain exists between these tables
    return;
  }

  const pathConnections = getConnectionsAlongPath(path);
  const pathTables = new Set(path);

  AppState.update('traceState', {
    active: true,
    path,
    pathConnections,
    pathTables,
  });

  // Triggers redrawAll() via stateChanged event
}
```

---

## Anti-Patterns (NEVER DO)

- Cache line positions or anchor points between redraws
- Skip `redrawAll()` for performance without a trailing-edge guarantee
- Draw connection lines in any module other than `connections.js`
- Store computed line paths in state (they are derived data)
- Use `setInterval` for redraw (use event-driven approach)
- Assume previous anchor points are still valid after any state change
- Perform relationship detection in frontend code (backend only)
- Hard-code column indices instead of looking them up from state
