# Skill: DB Diagram Frontend Design

## When to Use

Apply this skill when building or modifying the frontend UI for the DB Diagram Visualizer project. This includes work on the canvas rendering, table block components, connection lines, filter/toolbar UI, layout algorithms, and any interactive diagram features. Use this guide to ensure visual consistency, accessibility, and a professional feel across all frontend code.

---

## Design Principles

### Canvas-First Architecture
- The diagram canvas is the primary workspace. It must feel immediate, responsive, and uncluttered.
- Use an HTML5 Canvas or SVG layer for rendering diagrams. Prefer SVG for interactivity (event handling per element) unless performance with hundreds of tables demands Canvas.
- Maintain a clear visual hierarchy: grid background < connection lines < table blocks < active selection overlays < tooltips/popovers.

### Grid Layout
- Render a subtle dot-grid or line-grid background to help users align table blocks visually.
- Grid color: `#E5E7EB` (light gray) on a `#F9FAFB` (near-white) canvas background.
- Grid spacing: 20px intervals. Snap-to-grid should be available (togglable).

### Card-Based Table Blocks
- Each database table is represented as a distinct card/block on the canvas.
- Blocks must have clear boundaries, a header, and structured rows — never free-floating text.

### Connection Lines
- Relationships between tables are drawn as lines connecting specific column rows.
- Lines must never obscure table content. Route lines around blocks when possible.

### Color Coding
- Use color intentionally to distinguish key types, relationship types, and interactive states.
- Never rely on color alone — pair with icons or labels for accessibility.

---

## Color Palette

### Canvas & Chrome
| Element              | Color     | Hex       |
|----------------------|-----------|-----------|
| Canvas background    | Near white| `#F9FAFB` |
| Grid dots/lines      | Light gray| `#E5E7EB` |
| Panel/sidebar bg     | White     | `#FFFFFF` |
| Panel border         | Gray 200  | `#E5E7EB` |
| Text primary         | Gray 900  | `#111827` |
| Text secondary       | Gray 500  | `#6B7280` |

### Key Type Colors
| Key Type         | Color Name   | Hex       | Usage                          |
|------------------|--------------|-----------|--------------------------------|
| Primary Key (PK) | Amber        | `#F59E0B` | Icon fill, left-border accent  |
| Foreign Key (FK) | Blue         | `#3B82F6` | Icon fill, left-border accent  |
| Unique           | Violet       | `#8B5CF6` | Icon fill, left-border accent  |
| Index            | Teal         | `#14B8A6` | Icon fill, left-border accent  |
| Regular column   | Gray         | `#9CA3AF` | Subtle icon or no icon         |

### Relationship Line Colors
| Relationship   | Color     | Hex       |
|----------------|-----------|-----------|
| One-to-One     | Blue 500  | `#3B82F6` |
| One-to-Many    | Green 500 | `#22C55E` |
| Many-to-Many   | Orange 500| `#F97316` |
| Self-reference | Purple 400| `#A78BFA` |

### Interactive States
| State           | Color / Treatment                        |
|-----------------|------------------------------------------|
| Hover (block)   | Drop shadow `0 4px 12px rgba(0,0,0,0.08)`, border shifts to `#3B82F6` |
| Selected (block)| Border `#2563EB` (2px solid), light blue fill `#EFF6FF` on header |
| Hover (line)    | Stroke width increases from 1.5px to 3px, opacity 1.0 |
| Dimmed (filter) | Opacity 0.25 for non-matching elements   |

---

## Typography & Spacing

### Font Stack
- Primary: `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`
- Monospace (for data types): `"JetBrains Mono", "Fira Code", "Consolas", monospace`

### Table Block Typography
| Element            | Font Size | Weight | Font Family | Color     |
|--------------------|-----------|--------|-------------|-----------|
| Table name (header)| 13px      | 600    | Primary     | `#111827` |
| Column name        | 12px      | 400    | Primary     | `#111827` |
| Data type          | 11px      | 400    | Monospace   | `#6B7280` |
| Constraint badge   | 10px      | 500    | Primary     | White on key-type color |

### Spacing Within Table Blocks
- Block min-width: 200px. Max-width: 360px.
- Header padding: 10px 12px.
- Column row padding: 6px 12px.
- Row separator: 1px solid `#F3F4F6`.
- Block border-radius: 8px.
- Block border: 1px solid `#D1D5DB`. On hover/select, see interactive states above.
- Block drop shadow (default): `0 1px 3px rgba(0,0,0,0.06)`.

---

## Canvas Interaction Patterns

### Drag
- Table blocks are draggable by their header area. Cursor changes to `grab` on hover, `grabbing` while dragging.
- While dragging, the block should render at slight elevation (increased shadow) and at `opacity: 0.92`.
- Connection lines must update in real time as a block is dragged.
- Optional: snap-to-grid on drop (nearest grid intersection).

### Zoom
- Support zoom via mouse wheel (Ctrl+Scroll or pinch on trackpad).
- Zoom range: 25% to 200%. Default: 100%.
- Zoom should be centered on the cursor position, not the canvas center.
- Display current zoom level in a small indicator (bottom-right corner), e.g., "75%".
- Provide zoom-in / zoom-out / reset-zoom buttons in a floating toolbar.

### Pan
- Pan the canvas by clicking and dragging on empty space (no block underneath). Cursor: `default` normally, `move` while panning.
- Also support pan via middle-mouse-button drag anywhere.
- Minimap (optional, lower-right): a small overview rectangle showing viewport position within the full diagram.

### Select
- Click a table block to select it. Click empty canvas to deselect.
- Shift+Click to add to selection (multi-select).
- Drag-select (marquee/lasso) on empty canvas to select multiple blocks.
- Selected blocks can be moved together.

### Hover Highlights
- Hovering over a table block highlights all connection lines attached to it.
- Hovering over a specific column row highlights only the connection lines for that column.
- Hovering over a connection line highlights both endpoint columns and their parent blocks.
- Non-highlighted elements dim to `opacity: 0.25` during any hover highlight.

---

## Connection Line Rendering

### Curve Style
- Use cubic Bezier curves for all connection lines. Straight lines look rigid; Bezier curves give a professional, readable appearance.
- Control points should extend horizontally from the edge of each table block to prevent lines from overlapping block content.
- Typical control point offset: 60-100px horizontally from the block edge, scaling with distance between blocks.

### Endpoints
- Every connection line must have clearly visible endpoints at both the source and target column rows.
- Endpoint markers:
  - Source (PK side): small filled circle, radius 4px.
  - Target (FK side): arrowhead or crow's foot notation depending on cardinality.
- Endpoints attach to the left or right edge of the column row, whichever produces the shorter/cleaner path.

### Cardinality Notation
- Use crow's foot notation at line endpoints to indicate relationship cardinality:
  - `1` side: single perpendicular tick mark.
  - `N` / many side: three-pronged crow's foot.
  - Optional (`0..1`, `0..N`): add a small open circle before the tick/crow's foot.

### Line Rendering Details
- Default stroke width: 1.5px. On hover: 3px.
- Line colors: see Relationship Line Colors table above.
- Lines render behind table blocks (lower z-index).
- When many lines overlap, consider slight vertical offset (line bundling) to reduce visual clutter.
- Animated dashed lines can indicate "in-progress" or "suggested" relationships during editing.

---

## Table Block Design

### Structure (Top to Bottom)

```
+-------------------------------------+
|  [icon]  TABLE_NAME           [...]  |  <-- Header row
+-------------------------------------+
|  [PK]  id          INT        NN    |  <-- Column row
|  [FK]  user_id     INT        NN    |
|        name        VARCHAR(255)     |
|  [UQ]  email       VARCHAR(255) NN  |
|        created_at  TIMESTAMP        |
+-------------------------------------+
```

### Header
- Background: `#F9FAFB` or a subtle color tint based on schema/group.
- Left side: small database-table icon (16x16).
- Center/left-aligned: table name in semibold.
- Right side: overflow menu button (`...`) visible on hover, offering actions like "Edit", "Remove", "Highlight connections".
- Bottom border of header: 2px solid with a color accent (can represent schema grouping).

### Column Rows
- Each row displays: key-type icon | column name | data type | constraint badges.
- Key-type icons (14x14, left-aligned):
  - PK: key icon, filled amber `#F59E0B`.
  - FK: link/chain icon, filled blue `#3B82F6`.
  - UQ: fingerprint or shield icon, filled violet `#8B5CF6`.
  - IDX: lightning or list icon, filled teal `#14B8A6`.
  - None: no icon, or a subtle dot in gray.
- Column name: left-aligned after icon, primary text color.
- Data type: right-aligned or after column name with secondary text color, monospace font.
- Constraint badges: small pill-shaped labels — "NN" (not null), "AI" (auto-increment), "DF" (default) — rendered in 10px uppercase, subtle background.

### Collapsed State
- Allow table blocks to collapse to header-only (toggle via double-click on header or chevron icon).
- Collapsed block shows: table name + column count badge, e.g., "users (8)".
- Connection lines attach to the block edge when collapsed (no specific row).

---

## Responsive Layout Considerations

### Viewport Breakpoints
- **Desktop (>= 1024px):** Full canvas with sidebar panel visible. Toolbar across the top or as a floating bar.


### Sidebar / Panel
- Default width: 280px. Resizable via drag handle on the edge.
- On narrow screens, the sidebar should be toggleable (hamburger icon or swipe gesture).
- Sidebar content scrolls independently from the canvas.

### Canvas Sizing
- Canvas fills the remaining viewport after sidebar and toolbar.
- On resize, maintain current zoom level and pan position (do not reset view).

---

## Filter UI Design

### Placement
- Filters live in a sidebar panel (left side) or a top toolbar dropdown section.
- A filter icon in the toolbar toggles the filter panel open/closed.

### Filter Controls

#### Search Box
- Text input at the top of the filter panel: "Search tables or columns..."
- Searches across table names, column names, and data types.
- As the user types, matching tables/columns highlight on the canvas; non-matching elements dim (opacity 0.25).
- Highlight matching text within table blocks with a subtle yellow background (`#FEF3C7`).

#### Checkbox Filters
- **By key type:** Checkboxes for PK, FK, Unique, Index. Checking "FK" highlights all foreign key columns and their connection lines.
- **By data type:** Collapsible group of checkboxes (INT, VARCHAR, TIMESTAMP, etc.), auto-populated from the loaded schema.
- **By table/schema:** Collapsible tree of table names with checkboxes to show/hide specific tables.
- **By relationship:** Checkboxes for One-to-One, One-to-Many, Many-to-Many to show/hide connection lines by type.

#### Filter Behavior
- Active filters are shown as removable pill/chips at the top of the filter panel or below the toolbar.
- "Clear all filters" button resets everything.
- Filtered-out elements are dimmed, not hidden, so the user retains spatial context. Provide a toggle: "Dim" vs "Hide" for filtered-out elements.

#### Connection Highlighting on Filter
- When a filter is active, matching connection lines render at full opacity with increased stroke width (2.5px).
- Non-matching lines dim to opacity 0.1 and stroke width 1px.

---

## Auto-Sort / Layout Button

### Button Placement
- A "Layout" or "Auto-arrange" button in the top toolbar, with a grid/flowchart icon.
- Dropdown beside it offers layout algorithm choices.

### Layout Algorithms
- **Left-to-Right (LR):** Arrange tables in a directed flow from left to right based on FK dependencies. Root/parent tables on the left, child tables to the right.
- **Top-to-Bottom (TB):** Same as LR but vertical.
- **Force-directed:** Physics-based layout that minimizes line crossings and distributes tables evenly. Good for complex schemas.
- **Grid:** Simple grid arrangement (alphabetical or by schema), ignoring relationships. Useful as a reset.

### Animation
- When the user triggers auto-layout, tables should animate smoothly to their new positions (300-400ms ease-in-out transition).
- Connection lines update in real time during the animation.

### Undo
- Auto-layout is a destructive action on user-arranged positions. Always push the current layout to an undo stack before applying.
- Show a toast/snackbar: "Layout applied. [Undo]" with a 5-second undo window.

### "Fit to View" Button
- Separate button (magnifying glass with arrows or a "fit" icon) that adjusts zoom and pan so the entire diagram is visible within the viewport with 40px padding on all sides.
