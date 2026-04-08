# Skill: Layout Algorithms

## When to Use
Apply this skill when working on block positioning: layout algorithms (top-down, left-right, force-directed, grid, by-file), dependency graph building, animated transitions, and auto-fit viewport. All layout code is in `cstruct-app.js`.

---

## 1. Layout System Overview

Five layout modes, activated via sidebar buttons:

```javascript
function applyLayout(mode, animate = true) {
  // 1. Get all entities and connections
  // 2. Compute new positions based on mode
  // 3. Set file containers (by-file only, empty for others)
  // 4. Animate (if positions exist) or set directly (first load)
  // 5. Auto-fit viewport to show all entities
}
```

| Mode | Key | Strategy | Best For |
|------|-----|----------|----------|
| Top-Down | `top-down` | Dependency levels top-to-bottom, centered rows | Default, hierarchical view |
| Left-Right | `left-right` | Dependency levels left-to-right, stacked columns | Wide diagrams |
| Force-Directed | `force` | Physics simulation (repulsion + springs) | Organic clustering |
| Grid | `grid` | Alphabetical order, column-based | Clean reset, browsing |
| By File | `by-file` | Group by source file in visual containers | Multi-file projects |

### Layout State Tracking

`activeLayout` is tracked in state via `setActiveLayout(mode)`. This persists across uploads — if the user selected "left-right", new uploads also use left-right.

### File Containers State

`fileContainers` in state is a dict of `{filename: {x, y, width, height}}`. Set by `layoutByFile()`, cleared to `{}` by all other layouts. Used by the render pipeline to draw container boxes.

## 2. Dependency Graph — `buildDepthMap()`

Shared by top-down and left-right layouts. Builds a depth map using topological ordering:

```javascript
function buildDepthMap(connections, nameSet) {
  // 1. Build adjacency list and in-degree count
  // 2. Initialize queue with zero-in-degree nodes (roots)
  // 3. BFS: assign depth = max(parent depths) + 1
  // 4. Orphan nodes (cycles or disconnected) get maxDepth + 1
  // 5. Group entities by depth level
  // Returns: { groups: { 0: [names], 1: [names], ... }, maxDepth }
}
```

Key behaviors:
- Self-referencing connections (`source === target`) are skipped
- Duplicate edges are skipped
- Entities not reachable from any root get placed at the deepest level
- Depth is the **longest** path from any root, not the shortest

## 3. Top-Down Layout

Dependency levels stacked vertically, each row centered:

```
          Level 0 (roots)
    ┌─────┐     ┌─────┐
    │  A  │     │  B  │         ← centered row
    └─────┘     └─────┘
                   ↓
          Level 1 (children)
    ┌─────┐  ┌─────┐  ┌─────┐
    │  C  │  │  D  │  │  E  │  ← centered row
    └─────┘  └─────┘  └─────┘
```

```javascript
function layoutTopDown(entities, entityMap, connections, nameSet) {
  const { groups } = buildDepthMap(connections, nameSet);
  let y = 0;
  for (const row of groups) {
    // Center row: x starts at -rowWidth/2
    let x = -rowWidth / 2;
    for (const name of row) {
      positions[name] = { x, y, width: BLOCK.minWidth, height };
      x += BLOCK.minWidth + BLOCK.gapX;  // gapX = 100
    }
    y += maxRowHeight + BLOCK.gapY;  // gapY = 60
  }
}
```

## 4. Left-Right Layout

Same depth logic, but levels arranged as columns left-to-right:

```
  Level 0         Level 1         Level 2
  ┌─────┐        ┌─────┐
  │  A  │───────>│  C  │
  └─────┘        └─────┘        ┌─────┐
                 ┌─────┐───────>│  E  │
  ┌─────┐───────>│  D  │        └─────┘
  │  B  │        └─────┘
  └─────┘
```

```javascript
function layoutLeftRight(entities, entityMap, connections, nameSet) {
  let x = 0;
  for (const col of groups) {
    let y = 0;
    for (const name of col) {
      positions[name] = { x, y, width: BLOCK.minWidth, height };
      y += height + 40;   // Vertical gap within column
    }
    x += maxColWidth + 200;  // Horizontal gap between columns
  }
}
```

## 5. Force-Directed Layout

Physics simulation with repulsion between all nodes and spring attraction along connections:

### Parameters
```javascript
const REPULSION = 8000;
const SPRING_LENGTH = 300;
const SPRING_STRENGTH = 0.015;
const DAMPING = 0.85;
const ITERATIONS = 120;
```

### Algorithm
```
For 120 iterations:
  1. Repulsion: every pair of nodes pushes each other away
     force = REPULSION / distance²
  2. Springs: connected nodes pull toward SPRING_LENGTH apart
     force = (distance - SPRING_LENGTH) × SPRING_STRENGTH
  3. Apply: update positions += velocity, velocity *= DAMPING
```

### Initialization
Nodes start from current positions (if available) or grid placement with random jitter. This means re-running force layout from different starting layouts gives different results.

### Edge Deduplication
Connections are deduplicated by sorting [source, target] and checking a Set, so parallel connections between the same nodes don't double the spring force.

## 6. Grid Layout

Ignores connections entirely. Sorts entities alphabetically (structs first, then unions, then functions):

```javascript
function layoutGrid(entities, entityMap) {
  const sorted = [...entities].sort((a, b) => {
    const order = (e) => e.isFunction ? 2 : e.isUnion ? 1 : 0;
    return order(a) - order(b) || a.name.localeCompare(b.name);
  });
  const cols = Math.max(2, Math.ceil(Math.sqrt(sorted.length)));
  // Place in grid with BLOCK.gapX and BLOCK.gapY spacing
}
```

## 7. By-File Layout

Groups entities by their `sourceFile` property into visual containers:

```
┌──────────────────────────┐    ┌──────────────────────────┐
│ sensors/data.h           │    │ main.c                   │
│ ┌─────┐ ┌─────┐ ┌─────┐ │    │ ┌─────┐                  │
│ │ A   │ │ B   │ │ C   │ │    │ │ F   │                  │
│ └─────┘ └─────┘ └─────┘ │    │ └─────┘                  │
│ ┌─────┐                  │    │                          │
│ │ D   │                  │    │                          │
│ └─────┘                  │    │                          │
└──────────────────────────┘    └──────────────────────────┘
```

### Implementation

```javascript
function layoutByFile(entities, entityMap) {
  // 1. Group entities by sourceFile (unknown → "(unknown)")
  // 2. Sort files alphabetically
  // 3. For each file group:
  //    - Layout entities inside as a grid (sqrt-based columns)
  //    - Compute container dimensions with padding
  // 4. Arrange containers in a grid layout
  // Returns: { positions, containers }
}
```

### Container Dimensions
```javascript
const containerPad = 20;      // Padding around entities inside container
const containerTitleH = 32;   // Height of filename title bar
const innerGapX = 20;         // Gap between entities inside container
const innerGapY = 16;         // Vertical gap inside container
const containerGapX = 60;     // Gap between containers
const containerGapY = 50;     // Vertical gap between container rows
```

### State Integration
- Entity positions are stored in `positions` state (absolute coordinates within containers)
- Container boxes are stored in `fileContainers` state
- All other layouts clear `fileContainers` to `{}`
- Render pipeline checks `getActiveLayout() === 'by-file'` before drawing containers

### Rendering
File containers are drawn in `cstruct-blocks.js` via `drawFileContainer()`:
- Semi-transparent background (0.35 alpha)
- Dashed border (6,4 pattern)
- Filename title at top-left
- Drawn BEFORE connections and blocks in the pipeline

## 8. Animated Transitions

Layout changes animate blocks smoothly from current to target positions over 350ms:

```javascript
function animateToPositions(targetPositions, duration = 350) {
  const startPositions = { ...currentPositions };
  const startTime = performance.now();

  function step(now) {
    const t = Math.min((now - startTime) / duration, 1);
    // Cubic ease-in-out
    const eased = t < 0.5 ? 4*t*t*t : 1 - Math.pow(-2*t + 2, 3) / 2;
    // Interpolate each position
    setPositions(interpolated);  // Triggers render via event
    if (t < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}
```

### When Animation Is Used
- **Animated**: switching between layouts after initial load
- **Not animated**: first load (no previous positions to animate from)

### Animation Cancellation
If a new layout is applied during animation, the previous animation is cancelled:
```javascript
if (animationId) cancelAnimationFrame(animationId);
```

## 9. Auto-Fit Viewport

After every layout change, the viewport adjusts to show all entities:

```javascript
function autoFit() {
  // 1. Compute bounding box of all positions
  // 2. Calculate zoom to fit content with 60px padding on all sides
  // 3. Cap zoom at 1.5x (prevent over-zoom on small diagrams)
  // 4. Center content in viewport
}
```

## 10. Data Load Sequence

When new data is loaded from the backend:

```javascript
function onDataLoaded() {
  applyLayout(currentLayoutMode, false);  // false = no animation (first load)
  autoFit();
  scheduleRender();
}
```

The `currentLayoutMode` persists across uploads — if the user selected "by-file", new uploads also use by-file.

## 11. Anti-Patterns

- **Never animate the first layout** — there are no previous positions to animate from
- **Never skip autoFit after layout** — the content may be off-screen otherwise
- **Never assume all entities are in the depth map** — disconnected nodes get maxDepth + 1
- **Never modify state.positions directly** — always go through `setPositions()` or `setPosition()`
- **Never run force simulation with zero iterations** — at least 80-120 iterations needed for convergence
- **Never forget to clear fileContainers** — non-by-file layouts must set it to `{}`
