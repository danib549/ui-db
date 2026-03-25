# Schema Builder Architecture

## Separation from Diagram Page

The builder is a **separate page** (`/builder`) with its own state, events, and modules. It does NOT share state with the diagram page. It CAN import source table data from the diagram's backend (loaded CSV tables).

## Module Boundaries

### Backend
- `schema_builder.py` — data structures and manipulation (no HTTP, no DDL strings)
- `ddl_generator.py` — takes schema dict, returns SQL string (no HTTP, no state)
- `ddl_parser.py` — parses .sql files into builder schema format (reverse of ddl_generator)
- `schema_differ.py` — compares original vs modified schema, generates ALTER DDL
- `type_mapper.py` — source type → PG type mapping (pure functions, no side effects)
- `migration_generator.py` — generates INSERT INTO...SELECT SQL (pure functions)
- `pg_validator.py` — validates schema, returns error list (pure functions)
- `builder_routes.py` — Flask Blueprint for `/api/builder/*` routes (keeps `app.py` thin)
- `app.py` — registers the builder blueprint, stays as thin route layer

### Flask Blueprint Pattern

Builder routes live in `builder_routes.py` using a Flask Blueprint, NOT in `app.py`. This keeps `app.py` from growing beyond its current scope.

```python
# builder_routes.py
from flask import Blueprint, request, jsonify

builder_bp = Blueprint('builder', __name__, url_prefix='/api/builder')

@builder_bp.route('/validate', methods=['POST'])
def validate():
    ...

# app.py — register the blueprint
from builder_routes import builder_bp
app.register_blueprint(builder_bp)
```

### Backend Access to Source Data

Builder backend modules need access to loaded CSV tables (`loaded_tables`, `loaded_dataframes` in `app.py`). These are passed as **function arguments**, never imported directly:

- Route handlers in `builder_routes.py` import the globals from `app.py`
- Route handlers pass them as arguments to pure backend functions
- Backend modules (`type_mapper.py`, `migration_generator.py`) never import from `app.py`

```python
# builder_routes.py
from app import loaded_tables, loaded_dataframes
from type_mapper import suggest_pg_type

@builder_bp.route('/type-suggest', methods=['POST'])
def type_suggest():
    data = request.get_json()
    table = data.get('table', '')
    column = data.get('column', '')
    df = loaded_dataframes.get(table)
    # Pass data as arguments — type_mapper never imports from app
    result = suggest_pg_type(source_type, column, df=df)
    return jsonify(result)
```

### Shared vs Diagram-Specific Modules

Frontend modules that builder CAN import (shared infrastructure):
- `events.js` — event bus (shared)
- `utils.js` — shared utilities (escapeHtml)
- `constants.js` — shared colors only (`KEY_COLORS`), NOT diagram-specific constants

Frontend modules that builder MUST NOT import:
- `state.js` — diagram-only state
- `blocks.js`, `connections.js`, `canvas.js` — diagram rendering
- `filters.js`, `search.js`, `trace.js` — diagram features
- `layout.js`, `csv-import.js`, `export.js` — diagram features

### Frontend (`static/js/builder/`)
- `builder-app.js` — orchestrator: initializes page, wires events, owns render cycle
- `builder-state.js` — single source of truth for builder schema state
- `builder-panels.js` — source panel (left) + target panel (center) rendering
- `builder-editors.js` — table editor + column editor modal/inline UI
- `builder-pickers.js` — type selector dropdown + constraint picker UI
- `builder-output.js` — DDL preview panel (right) + export controls
- `builder-relationships.js` — FK relationship creation/editing UI
- `builder-constants.js` — PG type catalog, constraint options, colors

### Communication Rules
1. Builder JS modules communicate via the **existing event bus** (`events.js`) — no separate bus
2. Builder events are namespaced: `builderTableAdded`, `builderColumnUpdated`, etc.
3. Builder state is in `builder-state.js` — completely separate from `state.js`
4. Source data (loaded CSV tables) is fetched from existing backend endpoints (`/api/table-data`)
5. No direct imports between diagram modules and builder modules

## State Shape

```javascript
const builderState = {
  targetSchema: {
    name: 'public',                // schema name
    tables: [
      {
        name: 'users',
        tableType: 'permanent',    // permanent | temp | unlogged
        columns: [
          {
            name: 'id',
            type: 'bigint',
            identity: 'ALWAYS',    // null | 'ALWAYS' | 'BY DEFAULT'
            nullable: false,
            defaultValue: null,
            isPrimaryKey: true,
            isUnique: false,
            checkExpression: null,
            comment: null,
          }
        ],
        constraints: [
          { type: 'pk', columns: ['id'], name: 'users_pkey' },
          { type: 'fk', columns: ['role_id'], refTable: 'roles', refColumns: ['id'],
            onDelete: 'CASCADE', onUpdate: 'NO ACTION', name: 'users_role_id_fkey' },
          { type: 'unique', columns: ['email'], name: 'users_email_key' },
          { type: 'check', expression: 'age >= 0', name: 'users_age_check' },
        ],
        indexes: [
          { name: 'users_email_idx', columns: ['email'], type: 'btree', unique: false },
        ],
        comment: null,
        ifNotExists: false,
      }
    ],
    enums: [
      { name: 'user_status', values: ['active', 'inactive', 'banned'] }
    ],
  },
  sourceMapping: {
    // 'target_table.target_column' → { sourceTable, sourceColumn, transform }
  },
  activeEditor: null,              // { type: 'table' | 'column', table: 'users', column: 'id' }
  isDirty: false,                  // unsaved changes flag
};

// originalSchema — frozen snapshot of imported SQL baseline.
// NOT part of reactive state. Stored as module-local in builder-state.js.
// null when building from scratch. Set on SQL import via setOriginalSchema().
// Used by schema_differ.py to generate ALTER-based migrations.
// Exposes: getOriginalSchema(), hasOriginalSchema(), setOriginalSchema(), clearOriginalSchema()

// Derived data — NOT in state, computed in builder-output.js:
// - ddlPreview (string) — recomputed on builderStateChanged
// - validationErrors (list) — recomputed on builderStateChanged
//
// builder-output.js exposes getter functions so other modules can read them:
//   getDDLPreview() → string
//   getValidationErrors() → list[dict]
//   hasBlockingErrors() → boolean (for disabling Export button)
```

## Event Contracts

| Event | Payload | Trigger |
|-------|---------|---------|
| `builderTableAdded` | `{ table }` | New table created |
| `builderTableRemoved` | `{ tableName }` | Table deleted |
| `builderTableUpdated` | `{ tableName, changes }` | Table name/type/comment changed |
| `builderColumnAdded` | `{ tableName, column }` | Column added to table |
| `builderColumnRemoved` | `{ tableName, columnName }` | Column deleted |
| `builderColumnUpdated` | `{ tableName, columnName, changes }` | Column type/constraints changed |
| `builderConstraintAdded` | `{ tableName, constraint }` | Constraint added |
| `builderConstraintRemoved` | `{ tableName, constraintName }` | Constraint removed |
| `builderEnumAdded` | `{ enum }` | Enum type created |
| `builderEnumUpdated` | `{ enumName, changes }` | Enum name or values edited |
| `builderEnumRemoved` | `{ enumName }` | Enum type deleted |
| `builderValidationRan` | `{ errors }` | Validation completed |
| `builderDDLGenerated` | `{ sql }` | DDL preview updated |
| `builderSourceMapped` | `{ targetPath, source }` | Column mapped from source |
| `builderSqlImported` | `{ tableCount, warnings }` | SQL file parsed and loaded |
| `builderStateChanged` | `{ key }` | Any state mutation |

## State Mutation Rules

Same as diagram page:
1. All mutations go through `builder-state.js` functions
2. Every mutation emits a `builderStateChanged` event
3. Never store derived data in state — DDL preview and validation errors are computed in the render pipeline and held as module-local variables in `builder-output.js`
4. No exceptions to rule 3

## Page Layout

```
+------------------+------------------------+------------------+
|  Source Panel     |  Target Schema Panel   |  DDL Preview     |
|  (loaded tables)  |  (tables being built)  |  (live SQL)      |
|                  |                        |                  |
|  - Table list    |  - Table cards         |  - Generated DDL |
|  - Column list   |  - Add table btn       |  - Copy button   |
|  - Drag to map   |  - Inline editors      |  - Export button  |
|                  |                        |  - Validation     |
+------------------+------------------------+------------------+
```

## Naming Conventions

- Auto-generate constraint names: `{table}_pkey`, `{table}_{col}_fkey`, `{table}_{col}_key`, `{table}_{col}_check`
- Auto-generate index names: `{table}_{col}_idx`
- Users can override any auto-generated name
- All names enforced: snake_case, max 63 chars, no reserved words without warning
