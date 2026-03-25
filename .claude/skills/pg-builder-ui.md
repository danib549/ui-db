# Skill: PostgreSQL Schema Builder UI — Page Layout, Editors, and Interactions

## When to Use

Apply this skill when working on the builder page frontend: `builder.html`, `builder.css`, and any `static/js/builder/*.js` module. Covers the three-panel layout, table/column editors, type picker, constraint picker, live DDL preview, source-to-target column mapping, and export controls.

---

## Page Architecture

### Three-Panel Layout

```
+-------------------+-------------------------+-------------------+
|   SOURCE PANEL    |    TARGET SCHEMA PANEL   |   OUTPUT PANEL    |
|   (left, 250px)   |    (center, flex-grow)   |   (right, 350px)  |
|                   |                         |                   |
| Loaded CSV tables | PG tables being built   | Live DDL preview  |
| Column list       | Table cards with editors | Validation errors |
| Drag source cols  | Add/remove tables       | Export buttons    |
+-------------------+-------------------------+-------------------+
```

### Navigation

- Builder is a **separate page** at `/builder` (not a tab in the diagram page)
- Top nav bar with link back to diagram page
- Builder page reuses the same dark/light theme as diagram

### URL Structure

```
/           → Diagram Visualizer (existing)
/builder    → PostgreSQL Schema Builder (new)
```

---

## Source Panel (Left)

Shows tables loaded from CSV in the diagram page AND provides SQL file import. Read-only reference for mapping.

### SQL Import Section

At the top of the source panel, above the CSV table list:

```html
<div class="builder-source__import">
  <h3 class="builder-source__import-title">Import SQL</h3>
  <div class="builder-source__import-zone" id="sql-import-zone">
    <p class="builder-source__import-text">Drop .sql file or click to browse</p>
    <input type="file" id="sql-file-input" accept=".sql" hidden>
  </div>
  <div class="builder-source__import-status" id="sql-import-status" hidden>
    <span class="builder-source__import-icon">&#10003;</span>
    <span class="builder-source__import-info">Imported: 12 tables, 3 enums</span>
    <button class="builder-source__import-clear" title="Clear imported schema">&#215;</button>
  </div>
</div>
<hr class="builder-source__divider">
```

### SQL Import Flow

1. User drops `.sql` file or clicks to browse
2. File sent to `POST /api/builder/import-sql`
3. Backend parses DDL → returns schema + warnings
4. `builder-state.js`: `setTargetSchema(parsed)` + `setOriginalSchema(deepClone(parsed))`
5. If warnings: show count badge, details in validation tab
6. Target panel populates with imported tables
7. Migration tab shows "No changes" until user edits
8. Source panel shows import status with table/enum count

### Three Input Modes

| Mode | How | Migration Tab Shows |
|------|-----|-------------------|
| **From scratch** | Click "+ Add Table" | Full CREATE DDL only |
| **From CSV** | Map source columns from diagram page | INSERT INTO...SELECT data migration |
| **From SQL** | Import .sql file, then modify | ALTER-based schema migration diff |

Modes can combine: import SQL, then also map CSV source columns for data migration.

### CSV Source Tables

### Data Source

Fetches from existing endpoints:
- `GET /api/table-data?table=<name>` — column metadata and sample rows
- Source tables are loaded into the diagram page first, then available to builder

### UI Elements

```html
<div class="builder-source">
  <h2 class="builder-source__title">Source Tables</h2>
  <div class="builder-source__search">
    <input type="text" placeholder="Filter tables...">
  </div>
  <div class="builder-source__list">
    <!-- Collapsible table entries -->
    <div class="builder-source__table" data-table="users">
      <div class="builder-source__table-header">
        <span class="builder-source__arrow">▶</span>
        <span class="builder-source__table-name">users</span>
        <span class="builder-source__col-count">12 cols</span>
      </div>
      <div class="builder-source__columns" hidden>
        <!-- Each column is draggable. Key icons use SVG, not emoji. -->
        <div class="builder-source__column" draggable="true" data-table="users" data-column="id">
          <svg class="builder-source__key-icon builder-source__key-icon--pk" width="14" height="14" viewBox="0 0 14 14">
            <path d="M5 2a3 3 0 0 0-1.5 5.6V11l1.5 1 1.5-1V7.6A3 3 0 0 0 5 2z" fill="currentColor"/>
          </svg>
          <span class="builder-source__col-name">id</span>
          <span class="builder-source__col-type">INT</span>
        </div>
      </div>
    </div>
  </div>
</div>
```

### Interactions

- Click table header to expand/collapse column list
- Search input filters table list (debounced, 200ms)
- Columns are draggable — drop onto target panel to map source → target
- Key icons match diagram page colors (amber PK, blue FK, violet UQ)

---

## Target Schema Panel (Center)

The main editing area where users build their PostgreSQL schema.

### Table Cards

Each target table is a card with inline editing:

```html
<div class="builder-target">
  <div class="builder-target__header">
    <h2>Target Schema</h2>
    <button class="builder-target__add-table">+ Add Table</button>
    <button class="builder-target__add-enum">+ Add Enum</button>
  </div>

  <!-- Enum cards (inline editable) -->
  <div class="builder-target__enums">
    <!-- View mode: shows name, values, edit/delete buttons -->
    <div class="builder-enum-card">
      <span class="builder-enum-card__name">user_status</span>
      <span class="builder-enum-card__values">(active, inactive, banned)</span>
      <button class="builder-enum-card__edit" title="Edit enum">&#9998;</button>
      <button class="builder-enum-card__delete" title="Remove enum">&times;</button>
    </div>

    <!-- Edit mode: expands inline with name input + values textarea -->
    <div class="builder-enum-card builder-enum-card--editing">
      <div class="builder-enum-editor">
        <div class="builder-enum-editor__row">
          <label>Name</label>
          <input type="text" class="builder-enum-editor__name" value="user_status" spellcheck="false">
        </div>
        <div class="builder-enum-editor__row">
          <label>Values <span class="builder-enum-editor__hint">(one per line)</span></label>
          <textarea class="builder-enum-editor__values" rows="3" spellcheck="false">active
inactive
banned</textarea>
        </div>
        <div class="builder-enum-editor__actions">
          <button class="builder-btn builder-btn--small builder-btn--primary builder-enum-editor__save">Save</button>
          <button class="builder-btn builder-btn--small builder-btn--secondary builder-enum-editor__cancel">Cancel</button>
        </div>
      </div>
    </div>
  </div>

  <div class="builder-target__tables">
    <!-- Table card -->
    <div class="builder-table-card" data-table="users">
      <div class="builder-table-card__header">
        <input class="builder-table-card__name" value="users" spellcheck="false">
        <select class="builder-table-card__type">
          <option value="permanent" selected>Table</option>
          <option value="temp">Temp Table</option>
          <option value="unlogged">Unlogged Table</option>
        </select>
        <button class="builder-table-card__delete" title="Remove table">×</button>
      </div>

      <!-- Column list -->
      <div class="builder-table-card__columns">
        <div class="builder-column-row" data-column="id">
          <span class="builder-column-row__grip">⋮⋮</span>
          <input class="builder-column-row__name" value="id">
          <button class="builder-column-row__type-btn">bigint</button>
          <div class="builder-column-row__badges">
            <span class="builder-badge builder-badge--pk" title="Primary Key">PK</span>
            <span class="builder-badge builder-badge--nn" title="Not Null">NN</span>
            <span class="builder-badge builder-badge--identity" title="Identity">ID</span>
          </div>
          <button class="builder-column-row__edit" title="Edit column">✎</button>
          <button class="builder-column-row__delete" title="Remove column">×</button>
        </div>
      </div>

      <!-- Add column -->
      <button class="builder-table-card__add-column">+ Add Column</button>

      <!-- Table-level constraints summary -->
      <div class="builder-table-card__constraints">
        <span class="builder-constraint-badge">FK: user_id → roles.id</span>
        <span class="builder-constraint-badge">UQ: email</span>
        <button class="builder-table-card__add-constraint">+ Constraint</button>
      </div>

      <!-- Indexes summary -->
      <div class="builder-table-card__indexes">
        <span class="builder-index-badge">idx: email (btree)</span>
        <button class="builder-table-card__add-index">+ Index</button>
      </div>
    </div>
  </div>
</div>
```

### Table Card Interactions

- **Table name**: inline editable input, validates on blur (max 63 chars, no reserved words without warning)
- **Table type**: dropdown selector (permanent/temp/unlogged)
- **Delete table**: confirmation prompt before removal
- **Column reorder**: drag grip handle to reorder columns within table
- **Add column**: appends new column row with defaults (`text`, nullable, no constraints)

### Enum Card Interactions

- **Add enum**: "+ Add Enum" button creates a new enum with default name and placeholder values
- **Edit enum**: click pencil icon (&#9998;) to expand inline editor with name input + values textarea (one value per line)
- **Save**: validates name (non-empty, unique among enums), values (at least one), calls `updateEnum()` in builder-state.js
- **Cancel**: collapses editor without saving changes
- **Delete enum**: click × button, shows confirmation dialog before calling `removeEnum()`
- Enum values are always strings (PostgreSQL constraint) — the textarea is plain text, one value per line
- Editing state (`editingEnumName`) is tracked as module-local in builder-panels.js (not in builder-state.js — it's UI state, not schema state)

---

## Column Editor (Modal/Inline)

Opens when clicking the edit button (✎) on a column row. Shows full column configuration.

### Editor Layout

```html
<div class="builder-column-editor">
  <div class="builder-column-editor__header">
    <h3>Edit Column: <span class="editor-table-name">users</span>.<span class="editor-col-name">email</span></h3>
    <button class="builder-column-editor__close">×</button>
  </div>

  <div class="builder-column-editor__body">
    <!-- Name -->
    <div class="builder-field">
      <label>Column Name</label>
      <input type="text" value="email" class="builder-field__input">
      <span class="builder-field__hint">snake_case, max 63 chars</span>
    </div>

    <!-- Type picker (see Type Picker section) -->
    <div class="builder-field">
      <label>Data Type</label>
      <div class="builder-type-picker" id="type-picker"></div>
    </div>

    <!-- Type parameters (shown conditionally) -->
    <div class="builder-field builder-field--params" id="type-params">
      <label>Length</label>
      <input type="number" value="255" min="1" class="builder-field__input builder-field__input--small">
    </div>

    <!-- Nullable -->
    <div class="builder-field builder-field--toggle">
      <label>
        <input type="checkbox"> Nullable
      </label>
    </div>

    <!-- Identity -->
    <div class="builder-field">
      <label>Identity</label>
      <select class="builder-field__select">
        <option value="">None</option>
        <option value="ALWAYS">GENERATED ALWAYS</option>
        <option value="BY DEFAULT">GENERATED BY DEFAULT</option>
      </select>
    </div>

    <!-- Default value -->
    <div class="builder-field">
      <label>Default Value</label>
      <input type="text" placeholder="e.g., NOW(), 0, 'pending'" class="builder-field__input">
      <span class="builder-field__hint">Leave empty for no default</span>
    </div>

    <!-- Check constraint -->
    <div class="builder-field">
      <label>CHECK Expression</label>
      <input type="text" placeholder='e.g., "age" >= 0' class="builder-field__input">
    </div>

    <!-- Comment -->
    <div class="builder-field">
      <label>Comment</label>
      <input type="text" placeholder="Column description" class="builder-field__input">
    </div>

    <!-- Source mapping -->
    <div class="builder-field builder-field--mapping">
      <label>Source Column</label>
      <div class="builder-mapping">
        <span class="builder-mapping__source">users.email_address</span>
        <button class="builder-mapping__clear">×</button>
      </div>
      <span class="builder-field__hint">Drop a source column here to map</span>
    </div>
  </div>

  <div class="builder-column-editor__footer">
    <button class="builder-btn builder-btn--secondary">Cancel</button>
    <button class="builder-btn builder-btn--primary">Apply</button>
  </div>
</div>
```

### Conditional Fields

Show/hide fields based on type selection:
- `varchar(n)`, `char(n)`: show Length input
- `numeric(p,s)`: show Precision + Scale inputs
- `bit(n)`, `varbit(n)`: show Length input
- Identity types: show Identity dropdown, hide Default
- Array types: show base type picker + `[]` indicator

---

## Type Picker

A categorized dropdown for selecting PostgreSQL data types.

### Design

```html
<div class="builder-type-picker">
  <input class="builder-type-picker__search" placeholder="Search types..." value="varchar">
  <div class="builder-type-picker__dropdown">
    <!-- Common types at top (no category header) -->
    <div class="builder-type-picker__item builder-type-picker__item--selected" data-type="varchar">
      <span class="builder-type-picker__name">varchar(n)</span>
      <span class="builder-type-picker__desc">Variable-length string</span>
    </div>

    <!-- Category: Numeric -->
    <div class="builder-type-picker__category">Numeric</div>
    <div class="builder-type-picker__item" data-type="integer">
      <span class="builder-type-picker__name">integer</span>
      <span class="builder-type-picker__desc">4-byte signed integer</span>
    </div>
    <!-- ... more items ... -->
  </div>
</div>
```

### Behavior

- Search input filters types as you type (instant, no debounce needed — list is small)
- "Common" category shown first: `bigint`, `integer`, `text`, `varchar`, `boolean`, `timestamptz`, `uuid`, `jsonb`, `numeric`
- Click to select, dropdown closes
- Selected type shown in the search input
- If type needs parameters (varchar, numeric), parameter inputs appear below

---

## Constraint Picker

UI for adding table-level constraints.

### Modal Layout

```html
<div class="builder-constraint-picker">
  <h3>Add Constraint to <span>users</span></h3>

  <div class="builder-constraint-picker__type-select">
    <button class="active" data-type="pk">Primary Key</button>
    <button data-type="fk">Foreign Key</button>
    <button data-type="unique">Unique</button>
    <button data-type="check">Check</button>
  </div>

  <!-- PK: select columns -->
  <div class="builder-constraint-form" id="form-pk">
    <label>Columns (select one or more for composite PK)</label>
    <div class="builder-column-select">
      <label><input type="checkbox" value="id" checked> id</label>
      <label><input type="checkbox" value="tenant_id"> tenant_id</label>
    </div>
    <label>Constraint Name</label>
    <input type="text" value="users_pkey" class="builder-field__input">
  </div>

  <!-- FK: select columns + reference -->
  <div class="builder-constraint-form" id="form-fk" hidden>
    <label>Column(s)</label>
    <select><option>role_id</option></select>
    <label>References Table</label>
    <select><option>roles</option></select>
    <label>References Column(s)</label>
    <select><option>id</option></select>
    <label>ON DELETE</label>
    <select>
      <option>NO ACTION</option>
      <option>CASCADE</option>
      <option>SET NULL</option>
      <option>SET DEFAULT</option>
      <option>RESTRICT</option>
    </select>
    <label>ON UPDATE</label>
    <select>
      <option>NO ACTION</option>
      <option>CASCADE</option>
      <option>SET NULL</option>
      <option>SET DEFAULT</option>
      <option>RESTRICT</option>
    </select>
    <label>Constraint Name</label>
    <input type="text" value="users_role_id_fkey" class="builder-field__input">
  </div>

  <!-- Check: expression -->
  <div class="builder-constraint-form" id="form-check" hidden>
    <label>Expression</label>
    <input type="text" placeholder='"age" >= 0' class="builder-field__input">
    <label>Constraint Name</label>
    <input type="text" value="users_age_check" class="builder-field__input">
  </div>
</div>
```

### Auto-Generated Names

When user selects constraint type and columns, auto-generate the name:
- PK: `{table}_pkey`
- FK: `{table}_{column}_fkey`
- Unique: `{table}_{column}_key`
- Check: `{table}_{column}_check`
- Index: `{table}_{column}_idx`

User can always override the auto-generated name.

---

## Output Panel (Right)

### DDL Preview

Live-updating SQL preview that regenerates on every schema change.

```html
<div class="builder-output">
  <div class="builder-output__tabs">
    <button class="builder-output__tab active" data-tab="ddl">DDL</button>
    <button class="builder-output__tab" data-tab="validation">Errors</button>
    <button class="builder-output__tab" data-tab="migration">Migration</button>
  </div>

  <!-- DDL Tab -->
  <div class="builder-output__content" id="tab-ddl">
    <pre class="builder-output__code"><code id="ddl-preview">
-- Generated DDL will appear here as you build your schema
    </code></pre>
    <div class="builder-output__actions">
      <button class="builder-btn" id="copy-ddl">Copy SQL</button>
      <button class="builder-btn" id="export-sql">Export .sql</button>
      <button class="builder-btn" id="export-json">Export JSON</button>
    </div>
  </div>

  <!-- Validation Tab -->
  <div class="builder-output__content" id="tab-validation" hidden>
    <div class="builder-validation">
      <div class="builder-validation__item builder-validation__item--error">
        <span class="builder-validation__icon">✗</span>
        <span>FK "orders.user_id" references non-existent table "users"</span>
      </div>
      <div class="builder-validation__item builder-validation__item--warning">
        <span class="builder-validation__icon">⚠</span>
        <span>"order" is a PostgreSQL reserved word</span>
      </div>
      <div class="builder-validation__item builder-validation__item--ok">
        <span class="builder-validation__icon">✓</span>
        <span>All FK targets exist</span>
      </div>
    </div>
  </div>

  <!-- Migration Tab -->
  <div class="builder-output__content" id="tab-migration" hidden>
    <pre class="builder-output__code"><code id="migration-preview">
-- Migration SQL for mapped columns
    </code></pre>
  </div>
</div>
```

### DDL Preview Behavior

- Regenerates on every `builderStateChanged` event
- Calls `POST /api/builder/generate-ddl` with current schema state
- Syntax highlighting via CSS (keywords blue, strings green, comments gray)
- Debounced: 300ms after last change to avoid hammering the backend

### Validation Display

- Runs automatically on every schema change (debounced 500ms)
- Errors (red): block export — must fix
- Warnings (yellow): allow export — but flag to user
- OK (green): validation passed

### Export Options

| Button | Action |
|--------|--------|
| Copy SQL | Copy DDL to clipboard, show toast "Copied!" |
| Export .sql | Download as `schema_name.sql` file |
| Export JSON | Download schema definition as `.json` (can be re-imported) |

---

## CSS Class Naming

Follow BEM conventions matching the existing project:

```css
/* Block */
.builder-source { }
.builder-target { }
.builder-output { }
.builder-table-card { }
.builder-column-editor { }
.builder-type-picker { }
.builder-constraint-picker { }

/* Element */
.builder-source__title { }
.builder-table-card__header { }
.builder-column-row__name { }

/* Modifier */
.builder-badge--pk { }
.builder-badge--fk { }
.builder-validation__item--error { }
.builder-type-picker__item--selected { }
```

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+S` | Export .sql file |
| `Ctrl+Shift+C` | Copy DDL to clipboard |
| `Escape` | Close active editor/picker |
| `Tab` in column editor | Move to next field |
| `Enter` in table name | Confirm rename |
| `Delete` on selected column | Remove column (with confirm) |

---

## State → UI Update Flow

```
User action (click, type, drag)
  → builder-editors.js / builder-pickers.js handles event
  → calls builder-state.js mutation function
  → builder-state.js emits builderStateChanged event
  → builder-app.js receives event
  → builder-app.js calls:
      1. builder-panels.js → re-render target table cards
      2. builder-output.js → regenerate DDL preview (debounced)
      3. builder-output.js → re-run validation (debounced)
```

---

## Dark Mode

Builder inherits the existing dark mode system (`dark-mode.css`). Builder-specific colors use CSS custom properties:

```css
:root {
  --builder-bg: #ffffff;
  --builder-card-bg: #f8f9fa;
  --builder-border: #e0e0e0;
  --builder-code-bg: #1e1e1e;
  /* Inherit key colors from existing CSS variables (defined in styles.css) */
  --builder-badge-pk: var(--pk-color, #F59E0B);
  --builder-badge-fk: var(--fk-color, #3B82F6);
  --builder-badge-uq: var(--uq-color, #8B5CF6);
  --builder-badge-nn: #6B7280;
  --builder-badge-identity: #22C55E;
  --builder-error: #EF4444;
  --builder-warning: #F59E0B;
  --builder-success: #22C55E;
}

/* Use body.dark to match existing dark-mode.css pattern */
body.dark {
  --builder-bg: #1a1a2e;
  --builder-card-bg: #16213e;
  --builder-border: #2a2a4a;
  --builder-code-bg: #0d1117;
}
```

---

## Typography

Builder inherits fonts from the shared `styles.css`:
- **UI text**: Inter (locally bundled in `/static/fonts/`)
- **Code/types**: JetBrains Mono (locally bundled)
- **DDL preview**: JetBrains Mono, 13px
- **Table card headers**: Inter, 14px, semibold
- **Column names**: Inter, 13px, regular
- **Type badges**: JetBrains Mono, 11px

---

## Empty States

Each panel must show a clear empty state with a call-to-action:

```html
<!-- Source panel: no CSV tables loaded -->
<div class="builder-empty">
  <p class="builder-empty__message">No source tables loaded</p>
  <p class="builder-empty__hint">Import CSV files on the <a href="/">Diagram page</a> first</p>
</div>

<!-- Target panel: no tables created yet -->
<div class="builder-empty">
  <p class="builder-empty__message">No tables yet</p>
  <p class="builder-empty__hint">Click "+ Add Table" to start building your schema</p>
</div>

<!-- DDL preview: nothing to generate -->
<div class="builder-empty">
  <p class="builder-empty__message">DDL preview will appear here</p>
  <p class="builder-empty__hint">Add tables and columns to generate SQL</p>
</div>

<!-- Validation: all clear -->
<div class="builder-validation__item builder-validation__item--ok">
  <span class="builder-validation__icon">&#10003;</span>
  <span>Schema is valid — no issues found</span>
</div>
```

---

## Loading States

```html
<!-- DDL generation in progress (shown during debounce + API call) -->
<div class="builder-loading">
  <span class="builder-loading__spinner"></span>
  <span class="builder-loading__text">Generating DDL...</span>
</div>

<!-- Validation running -->
<div class="builder-loading">
  <span class="builder-loading__spinner"></span>
  <span class="builder-loading__text">Validating schema...</span>
</div>
```

```css
.builder-loading__spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--builder-border);
  border-top-color: var(--builder-badge-pk);
  border-radius: 50%;
  animation: builder-spin 0.6s linear infinite;
}
@keyframes builder-spin { to { transform: rotate(360deg); } }
```

---

## Error States

```html
<!-- API failure -->
<div class="builder-error">
  <span class="builder-error__icon">!</span>
  <p class="builder-error__message">Failed to generate DDL</p>
  <button class="builder-btn builder-btn--small">Retry</button>
</div>
```

---

## Hover States

| Element | Hover Effect |
|---------|-------------|
| Table card | `box-shadow: 0 2px 8px rgba(0,0,0,0.12)`, border color lightens |
| Column row | Background `var(--builder-card-bg)` darkens slightly, edit/delete buttons appear |
| Badge (PK/FK/UQ) | Tooltip appears with full description (e.g., "Primary Key") |
| Delete button (x) | Color changes to `var(--builder-error)` |
| Type picker item | Background highlight, slight indent |
| Add Table/Column button | Background fills, text brightens |
| Export buttons | Standard button hover (darken 10%) |

All transitions: `transition: all 0.15s ease`.

---

## Drag-and-Drop Feedback

| State | Visual |
|-------|--------|
| Drag start (source column) | Source row opacity 0.5, ghost shows column name + type |
| Valid drop target | Target area border becomes `2px dashed var(--builder-badge-fk)`, background lightens |
| Invalid drop target | No visual change (default cursor) |
| Column reorder grip drag | Row lifts with shadow, gap appears at insertion point |
| Drop complete | Brief flash highlight on the mapped column |

---

## Confirmation Dialogs

```html
<div class="builder-confirm" role="alertdialog" aria-modal="true">
  <p class="builder-confirm__message">Delete table "users" and all its columns?</p>
  <div class="builder-confirm__actions">
    <button class="builder-btn builder-btn--secondary">Cancel</button>
    <button class="builder-btn builder-btn--danger">Delete</button>
  </div>
</div>
```

Focus traps inside the dialog. Cancel button gets initial focus. Escape closes.

---

## Undo/Redo

Out of scope for v1. The `isDirty` flag tracks unsaved changes. A full undo stack will be added in v2 once the builder UI is stable.
