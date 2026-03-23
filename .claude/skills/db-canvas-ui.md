# DB Canvas UI & Interaction

Skill for the UI and interaction layer of the database diagram canvas. Covers table block design, user interactions, visual states, typography, colors, layout, and toolbar controls.

---

## 1. Table Block Design

### Block Structure

```
+---------------------------------------+
| [icon] Table Name            [menu]   |  <-- Header (grab handle for drag)
+---------------------------------------+
| [PK] id          INT        NOT NULL  |  <-- Column row
| [FK] user_id     INT                  |
|      name        VARCHAR(255)         |
|      created_at  TIMESTAMP   DEFAULT  |
+---------------------------------------+
```

Each column row contains (left to right):
- **Key icon** — colored icon if PK, FK, UQ, or IDX; blank spacer otherwise
- **Column name** — left-aligned text
- **Data type** — right-aligned monospace text
- **Constraint badges** — small pills for NOT NULL, DEFAULT, UNIQUE, AUTO_INCREMENT

### Sizing

| Property       | Value               |
|----------------|---------------------|
| Min width      | 200px               |
| Max width      | 360px               |
| Border radius  | 8px                 |
| Header height  | 36px                |
| Row height     | 28px                |
| Horizontal pad | 12px                |
| Shadow         | `0 1px 3px rgba(0,0,0,0.1), 0 1px 2px rgba(0,0,0,0.06)` |

Width is auto-calculated based on longest column name + data type, clamped to min/max.

### Collapsed State

- Only the header is visible (column rows hidden).
- A small chevron in the header indicates collapsed/expanded.
- Toggle via double-click on header or menu option.
- Connection lines attach to the header center when collapsed.

---

## 2. Interaction Patterns

### Drag

- **Initiation**: mousedown on the header area (not menu button).
- **Behavior**: block follows cursor with offset preserved from grab point.
- **Snap-to-grid**: optional, 20px grid. Hold Shift to toggle snap behavior.
- **Line update**: connection lines redraw in real-time during drag (use `requestAnimationFrame`, trailing-edge debounce). The iron rule applies — `redrawAll()` fires on every frame.
- **Multi-drag**: if multiple blocks are selected, all selected blocks move together, maintaining relative positions.

### Zoom

- **Trigger**: Ctrl+Scroll (or Cmd+Scroll on Mac).
- **Range**: 25% to 200%, step 5%.
- **Center**: zoom is centered on the cursor position, not the viewport center.
- **Indicator**: show a transient zoom percentage label (e.g., "75%") that fades after 1.5s.
- **Pinch-to-zoom**: support on trackpad/touch devices.

### Pan

- **Trigger**: click and drag on empty canvas space (no block under cursor).
- **Alt trigger**: middle mouse button drag works anywhere (even over blocks).
- **Cursor**: `grab` on hover over empty space, `grabbing` while panning.
- **Momentum**: none — pan stops immediately on mouseup.

### Select

- **Single select**: click on a block. Deselects all others.
- **Multi-select**: Shift+click to add/remove a block from selection.
- **Marquee select**: click and drag on empty space while holding Ctrl to draw a selection rectangle. All blocks intersecting the rectangle are selected on mouseup.
- **Select all**: Ctrl+A selects all visible (non-filtered) blocks.
- **Deselect**: click on empty canvas space (without Ctrl) or press Escape.

### Hover Highlights

- **Block hover**: all connection lines touching that block highlight (full opacity, thicker stroke). All other lines dim to 0.25 opacity. Connected blocks get a subtle glow.
- **Column hover**: only lines connected to that specific column highlight. Other lines dim.
- **Line hover**: the hovered line highlights; its source and target columns get a highlight background.
- **Exit**: on mouseleave, restore all elements to default opacity.

---

## 3. Visual States

| State    | Shadow                                          | Border               | Opacity | Other                          |
|----------|------------------------------------------------|----------------------|---------|--------------------------------|
| Default  | `0 1px 3px rgba(0,0,0,0.1)`                   | 1px solid #E5E7EB   | 1.0     | —                              |
| Hover    | `0 4px 6px rgba(0,0,0,0.1)`                   | 1px solid #3B82F6   | 1.0     | Transition 150ms ease          |
| Selected | `0 4px 6px rgba(59,130,246,0.15)`              | 2px solid #3B82F6   | 1.0     | Header fill #EFF6FF            |
| Dragging | `0 12px 24px rgba(0,0,0,0.15)`                | 2px solid #3B82F6   | 0.92    | Elevated above other blocks    |
| Dimmed   | none                                            | 1px solid #E5E7EB   | 0.25    | Non-interactive (pointer-events: none on DOM, skip hit-test on canvas) |

State transitions should use CSS transitions (DOM) or interpolation frames (canvas) at 150ms ease for smooth feedback.

---

## 4. Typography

| Element          | Font            | Size  | Weight | Color   |
|------------------|-----------------|-------|--------|---------|
| Table name       | Inter           | 13px  | 600    | #111827 |
| Column name      | Inter           | 12px  | 400    | #374151 |
| Data type        | JetBrains Mono  | 11px  | 400    | #6B7280 |
| Constraint badge | Inter           | 10px  | 500    | varies  |
| Key icon label   | Inter           | 10px  | 600    | matches key color |

### Font Loading

Load Inter and JetBrains Mono via Google Fonts or self-hosted. Use `font-display: swap` to avoid invisible text during load. Fall back to `system-ui, -apple-system, sans-serif` for Inter and `monospace` for JetBrains Mono.

---

## 5. Color System

### Canvas

| Element         | Color   |
|-----------------|---------|
| Background      | #F9FAFB |
| Grid dots/lines | #E5E7EB |
| Grid spacing    | 20px    |

### Key Colors

| Key Type | Color   | Name   | Usage                          |
|----------|---------|--------|--------------------------------|
| PK       | #F59E0B | Amber  | Primary key icon and row accent |
| FK       | #3B82F6 | Blue   | Foreign key icon and row accent |
| UQ       | #8B5CF6 | Violet | Unique constraint icon          |
| IDX      | #14B8A6 | Teal   | Index icon                      |

### Constraint Badge Colors

Badges use the key color as background at 10% opacity with the key color as text. Non-key constraints (NOT NULL, DEFAULT) use gray (#6B7280 text, #F3F4F6 bg).

### Relationship Line Colors

| Relationship | Color   | Name   | Stroke Style      |
|--------------|---------|--------|--------------------|
| 1:1          | #3B82F6 | Blue   | Solid, 1.5px       |
| 1:N          | #10B981 | Green  | Solid, 1.5px       |
| N:M          | #F97316 | Orange | Solid, 1.5px       |
| Self-ref     | #8B5CF6 | Purple | Solid, 1.5px       |
| Dimmed       | —       | —      | Original at 0.25 opacity |
| Highlighted  | —       | —      | Original at 2.5px stroke |

### Block Colors

| Element          | Color   |
|------------------|---------|
| Block background | #FFFFFF |
| Header background| #F9FAFB |
| Header (selected)| #EFF6FF |
| Row hover        | #F3F4F6 |
| Divider line     | #E5E7EB |

---

## 6. Responsive Layout

### Desktop (>1024px)

```
+----------+------------------------------------+
| Sidebar  |          Canvas                    |
| 280px    |     (fills remaining)              |
|          |                                    |
| - Tables |                                    |
| - Filter |                                    |
| - Search |                                    |
+----------+------------------------------------+
```

- Sidebar default width: 280px. Resizable via drag handle (min 200px, max 400px).
- Canvas fills remaining viewport width and full height.

### Tablet (768px-1024px)

- Sidebar collapsed to icon-only rail (48px wide).
- Click icon or hamburger to expand sidebar as overlay (does not push canvas).
- Canvas takes full width.

### Mobile (<768px)

- View-only mode. No drag, no edit.
- Sidebar becomes a bottom sheet (swipe up to open).
- Pinch-to-zoom and two-finger pan supported.
- Blocks render at fixed scale, user can zoom to explore.

---

## 7. Toolbar & Controls

The toolbar sits at the top of the canvas area (not the sidebar).

### Layout

```
[ Layout v ] [ Fit ] [ - ] 75% [ + ] | [ Filter ] [ Minimap ] [ Export ]
```

### Layout / Auto-Arrange

Dropdown button with algorithm options:
- **Left-to-Right (LR)** — Dagre/hierarchical, flows left to right. Best for dependency chains.
- **Top-to-Bottom (TB)** — Dagre/hierarchical, flows top to bottom. Best for tree structures.
- **Force-Directed** — Physics simulation (repulsion + spring). Good for exploratory layouts.
- **Grid** — Simple grid arrangement sorted by table name or connection count.

Clicking the button applies the last-used algorithm. Clicking the dropdown arrow shows the full list. Layout animation runs over 300ms ease-out.

### Fit-to-View

Calculates bounding box of all visible blocks, then sets zoom and pan so all blocks fit within the viewport with 40px padding.

### Zoom Controls

- `[-]` and `[+]` buttons step zoom by 10%.
- Percentage label in the center is clickable — opens a dropdown with preset levels (25%, 50%, 75%, 100%, 125%, 150%, 200%).
- Double-click the percentage label to reset to 100%.

### Filter Toggle

Opens/closes the filter panel (sidebar or floating panel). Active filter count shown as a badge on the button.

### Minimap Toggle

Shows/hides a small minimap in the bottom-right corner of the canvas. The minimap shows all blocks as small rectangles with a viewport indicator rectangle. Clicking/dragging on the minimap pans the main canvas.

### Export

Dropdown with options:
- **PNG** — rasterize current view at 2x resolution.
- **SVG** — vector export of all visible blocks and lines.
- **SQL DDL** — generate CREATE TABLE statements from the loaded schema.
