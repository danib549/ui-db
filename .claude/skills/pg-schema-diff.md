# Skill: PostgreSQL Schema Diff — ALTER Generation and Migration Workflow

## When to Use

Apply this skill when working on `schema_differ.py` or the migration output for modified imported schemas. Covers comparing an original (imported) schema against the current (modified) builder state and generating minimal ALTER DDL to migrate from one to the other.

---

## Architecture

### Module: `schema_differ.py`

Pure functions, no HTTP, no state. Takes two schema dicts (original + modified), returns a list of ordered DDL operations.

```python
def diff_schemas(original: dict, modified: dict) -> list[dict]:
    """Compare two schemas and return a list of migration operations.

    Args:
        original: The imported baseline schema (frozen snapshot).
        modified: The current builder schema (user's edits).

    Returns list of operation dicts, each with:
        {
            "type": "add_table" | "drop_table" | "add_column" | "drop_column" |
                    "alter_column_type" | "alter_column_nullable" | "alter_column_default" |
                    "add_constraint" | "drop_constraint" | "add_index" | "drop_index" |
                    "add_enum" | "drop_enum" | "add_enum_value",
            "table": str | None,
            "details": dict,   # type-specific details
            "sql": str,        # generated DDL statement
        }
    Operations are ordered for safe execution (drops before adds where needed).
    """
```

---

## Diff Categories

### 1. Table-Level Diffs

```python
def diff_tables(original: dict, modified: dict) -> list[dict]:
    """Detect added, dropped, and modified tables."""
    ops = []
    orig_names = {t["name"] for t in original.get("tables", [])}
    mod_names = {t["name"] for t in modified.get("tables", [])}

    # New tables → full CREATE TABLE
    for name in mod_names - orig_names:
        table = _find_table(modified, name)
        ops.append({
            "type": "add_table",
            "table": name,
            "details": {"table": table},
            "sql": "",  # filled by DDL generator
        })

    # Dropped tables → DROP TABLE
    for name in orig_names - mod_names:
        ops.append({
            "type": "drop_table",
            "table": name,
            "details": {},
            "sql": f'DROP TABLE IF EXISTS "{name}" CASCADE',
        })

    # Modified tables → diff columns and constraints
    for name in orig_names & mod_names:
        orig_table = _find_table(original, name)
        mod_table = _find_table(modified, name)
        ops.extend(diff_columns(name, orig_table, mod_table))
        ops.extend(diff_constraints(name, orig_table, mod_table))
        ops.extend(diff_indexes(name, orig_table, mod_table))

    return ops
```

### 2. Column-Level Diffs

```python
def diff_columns(table_name: str, original: dict, modified: dict) -> list[dict]:
    """Detect added, dropped, and modified columns within a table."""
    ops = []
    orig_cols = {c["name"]: c for c in original.get("columns", [])}
    mod_cols = {c["name"]: c for c in modified.get("columns", [])}

    # Added columns
    for name in mod_cols.keys() - orig_cols.keys():
        col = mod_cols[name]
        col_def = _build_column_def(col)
        ops.append({
            "type": "add_column",
            "table": table_name,
            "details": {"column": col},
            "sql": f'ALTER TABLE "{table_name}" ADD COLUMN {col_def}',
        })

    # Dropped columns
    for name in orig_cols.keys() - mod_cols.keys():
        ops.append({
            "type": "drop_column",
            "table": table_name,
            "details": {"column_name": name},
            "sql": f'ALTER TABLE "{table_name}" DROP COLUMN "{name}"',
        })

    # Modified columns
    for name in orig_cols.keys() & mod_cols.keys():
        orig_col = orig_cols[name]
        mod_col = mod_cols[name]
        ops.extend(_diff_single_column(table_name, orig_col, mod_col))

    return ops
```

### 3. Single Column Change Detection

```python
def _diff_single_column(
    table_name: str, orig: dict, mod: dict,
) -> list[dict]:
    """Compare a single column between original and modified versions."""
    ops = []
    col_name = orig["name"]

    # Type change
    if _normalize_type(orig["type"]) != _normalize_type(mod["type"]):
        new_type = mod["type"]
        ops.append({
            "type": "alter_column_type",
            "table": table_name,
            "details": {
                "column": col_name,
                "old_type": orig["type"],
                "new_type": new_type,
            },
            "sql": f'ALTER TABLE "{table_name}" ALTER COLUMN "{col_name}" TYPE {new_type}',
        })

    # Nullable change
    if orig.get("nullable") != mod.get("nullable"):
        if mod.get("nullable"):
            ops.append({
                "type": "alter_column_nullable",
                "table": table_name,
                "details": {"column": col_name, "nullable": True},
                "sql": f'ALTER TABLE "{table_name}" ALTER COLUMN "{col_name}" DROP NOT NULL',
            })
        else:
            ops.append({
                "type": "alter_column_nullable",
                "table": table_name,
                "details": {"column": col_name, "nullable": False},
                "sql": f'ALTER TABLE "{table_name}" ALTER COLUMN "{col_name}" SET NOT NULL',
            })

    # Default change
    orig_default = orig.get("defaultValue")
    mod_default = mod.get("defaultValue")
    if orig_default != mod_default:
        if mod_default is None:
            ops.append({
                "type": "alter_column_default",
                "table": table_name,
                "details": {"column": col_name, "default": None},
                "sql": f'ALTER TABLE "{table_name}" ALTER COLUMN "{col_name}" DROP DEFAULT',
            })
        else:
            ops.append({
                "type": "alter_column_default",
                "table": table_name,
                "details": {"column": col_name, "default": mod_default},
                "sql": f'ALTER TABLE "{table_name}" ALTER COLUMN "{col_name}" SET DEFAULT {mod_default}',
            })

    return ops
```

### 4. Constraint Diffs

```python
def diff_constraints(
    table_name: str, original: dict, modified: dict,
) -> list[dict]:
    """Detect added and dropped constraints."""
    ops = []
    orig_constraints = {c["name"]: c for c in original.get("constraints", [])}
    mod_constraints = {c["name"]: c for c in modified.get("constraints", [])}

    # Dropped constraints (must happen BEFORE adds to avoid conflicts)
    for name in orig_constraints.keys() - mod_constraints.keys():
        ops.append({
            "type": "drop_constraint",
            "table": table_name,
            "details": {"constraint_name": name},
            "sql": f'ALTER TABLE "{table_name}" DROP CONSTRAINT IF EXISTS "{name}"',
        })

    # Added constraints
    for name in mod_constraints.keys() - orig_constraints.keys():
        constraint = mod_constraints[name]
        constraint_sql = _build_constraint_sql(table_name, constraint)
        ops.append({
            "type": "add_constraint",
            "table": table_name,
            "details": {"constraint": constraint},
            "sql": constraint_sql,
        })

    # Modified constraints (drop + re-add)
    for name in orig_constraints.keys() & mod_constraints.keys():
        orig_c = orig_constraints[name]
        mod_c = mod_constraints[name]
        if _constraint_changed(orig_c, mod_c):
            ops.append({
                "type": "drop_constraint",
                "table": table_name,
                "details": {"constraint_name": name},
                "sql": f'ALTER TABLE "{table_name}" DROP CONSTRAINT IF EXISTS "{name}"',
            })
            constraint_sql = _build_constraint_sql(table_name, mod_c)
            ops.append({
                "type": "add_constraint",
                "table": table_name,
                "details": {"constraint": mod_c},
                "sql": constraint_sql,
            })

    return ops
```

### 5. Index Diffs

```python
def diff_indexes(
    table_name: str, original: dict, modified: dict,
) -> list[dict]:
    """Detect added and dropped indexes."""
    ops = []
    orig_indexes = {i["name"]: i for i in original.get("indexes", [])}
    mod_indexes = {i["name"]: i for i in modified.get("indexes", [])}

    for name in orig_indexes.keys() - mod_indexes.keys():
        ops.append({
            "type": "drop_index",
            "table": table_name,
            "details": {"index_name": name},
            "sql": f'DROP INDEX IF EXISTS "{name}"',
        })

    for name in mod_indexes.keys() - orig_indexes.keys():
        idx = mod_indexes[name]
        cols = ", ".join(f'"{c}"' for c in idx["columns"])
        using = f" USING {idx['type']}" if idx.get("type", "btree") != "btree" else ""
        unique = "UNIQUE " if idx.get("unique") else ""
        ops.append({
            "type": "add_index",
            "table": table_name,
            "details": {"index": idx},
            "sql": f'CREATE {unique}INDEX "{name}" ON "{table_name}"{using} ({cols})',
        })

    return ops
```

### 6. Enum Diffs

```python
def diff_enums(original: dict, modified: dict) -> list[dict]:
    """Detect added, dropped, and modified enum types.

    Note: PostgreSQL does not support DROP value from enum or reorder.
    Only ADD VALUE is supported (PG 9.1+). Removing values requires
    DROP TYPE + CREATE TYPE (which breaks dependent columns).
    """
    ops = []
    orig_enums = {e["name"]: e for e in original.get("enums", [])}
    mod_enums = {e["name"]: e for e in modified.get("enums", [])}

    # New enums
    for name in mod_enums.keys() - orig_enums.keys():
        enum = mod_enums[name]
        values = ", ".join(f"'{v}'" for v in enum["values"])
        ops.append({
            "type": "add_enum",
            "details": {"enum": enum},
            "sql": f'CREATE TYPE "{name}" AS ENUM ({values})',
        })

    # Dropped enums
    for name in orig_enums.keys() - mod_enums.keys():
        ops.append({
            "type": "drop_enum",
            "details": {"enum_name": name},
            "sql": f'DROP TYPE IF EXISTS "{name}" CASCADE',
        })

    # Modified enums — only ADD VALUE is safe
    for name in orig_enums.keys() & mod_enums.keys():
        orig_values = orig_enums[name]["values"]
        mod_values = mod_enums[name]["values"]
        new_values = [v for v in mod_values if v not in orig_values]
        removed_values = [v for v in orig_values if v not in mod_values]

        for val in new_values:
            ops.append({
                "type": "add_enum_value",
                "details": {"enum_name": name, "value": val},
                "sql": f"ALTER TYPE \"{name}\" ADD VALUE '{val}'",
            })

        if removed_values:
            # Cannot safely remove enum values — add warning operation
            ops.append({
                "type": "warning",
                "details": {
                    "message": f"Cannot remove values from enum '{name}': {removed_values}. "
                               f"Requires DROP TYPE + CREATE TYPE which breaks dependent columns.",
                },
                "sql": f"-- WARNING: Cannot remove enum values: {removed_values}",
            })

    return ops
```

---

## Operation Ordering

Operations must be ordered for safe execution:

```python
OPERATION_ORDER = {
    "drop_index": 0,        # Drop indexes first (they may reference columns)
    "drop_constraint": 1,   # Drop constraints (FK may block column drops)
    "drop_column": 2,       # Drop columns
    "drop_table": 3,        # Drop tables
    "drop_enum": 4,         # Drop enum types
    "add_enum": 5,          # Create enum types (before tables that use them)
    "add_enum_value": 6,    # Add values to existing enums
    "add_table": 7,         # Create new tables
    "add_column": 8,        # Add columns to existing tables
    "alter_column_type": 9,  # Change column types
    "alter_column_nullable": 10,
    "alter_column_default": 11,
    "add_constraint": 12,   # Add constraints (after columns exist)
    "add_index": 13,        # Create indexes last
    "warning": 99,          # Warnings at the end
}


def order_operations(ops: list[dict]) -> list[dict]:
    """Sort operations for safe execution order."""
    return sorted(ops, key=lambda op: OPERATION_ORDER.get(op["type"], 50))
```

---

## Full Migration Generation

```python
def generate_migration_ddl(original: dict, modified: dict) -> str:
    """Generate a complete ALTER-based migration script.

    Args:
        original: Imported baseline schema.
        modified: Current builder schema.

    Returns: SQL string with all ALTER/CREATE/DROP statements.
    """
    ops = []
    ops.extend(diff_enums(original, modified))
    ops.extend(diff_tables(original, modified))
    ordered = order_operations(ops)

    if not ordered:
        return "-- No changes detected"

    lines = [
        "-- ============================================================",
        "-- MIGRATION: Schema changes",
        f"-- From: original import ({len(original.get('tables', []))} tables)",
        f"-- To: current builder state ({len(modified.get('tables', []))} tables)",
        f"-- Operations: {len([o for o in ordered if o['type'] != 'warning'])}",
        "-- ============================================================",
        "",
        "BEGIN;",
        "",
    ]

    current_type = None
    for op in ordered:
        # Section headers
        op_category = op["type"].split("_")[0]
        if op_category != current_type:
            current_type = op_category
            lines.append(f"-- {current_type.upper()} operations")

        lines.append(f"{op['sql']};")

    lines.append("")
    lines.append("COMMIT;")

    return "\n".join(lines)
```

---

## API Endpoint

```python
# In builder_routes.py
@builder_bp.route('/generate-migration', methods=['POST'])
def generate_migration():
    """Generate ALTER-based migration from original to modified schema.

    Expects JSON: {
        "original": {...},  # original imported schema (or null for from-scratch)
        "modified": {...},  # current builder schema
    }
    """
    from schema_differ import diff_schemas, generate_migration_ddl

    data = request.get_json(silent=True) or {}
    original = data.get("original")
    modified = data.get("modified")

    if not modified:
        return jsonify({"error": "modified schema is required"}), 400

    # If no original, this is a from-scratch build — use full CREATE DDL instead
    if not original:
        from ddl_generator import generate_full_ddl
        return jsonify({"sql": generate_full_ddl(modified), "mode": "create"})

    sql = generate_migration_ddl(original, modified)
    return jsonify({"sql": sql, "mode": "alter"})
```

---

## State Integration

The builder state needs `originalSchema` to store the imported baseline:

```javascript
// In builder-state.js
// Set when importing SQL or loading a saved schema
// null when building from scratch
let originalSchema = null;

export function setOriginalSchema(schema) {
  originalSchema = structuredClone(schema);  // deep freeze the baseline
}

export function getOriginalSchema() {
  return originalSchema;
}

export function hasOriginalSchema() {
  return originalSchema !== null;
}

export function clearOriginalSchema() {
  originalSchema = null;
}
```

`originalSchema` is NOT reactive state — it's a frozen snapshot. No events emitted when set. It's only used when generating migration output.

---

## UI Integration

### Migration Tab Behavior

The output panel's Migration tab changes based on whether an original schema exists:

| State | Tab Content |
|-------|------------|
| No original (from scratch) | Shows `INSERT INTO...SELECT` data migration if source columns mapped |
| Has original (imported SQL) | Shows ALTER-based schema migration + data migration |
| No changes from original | Shows "No schema changes detected" |

### Import Flow

```
User clicks "Import SQL" button in source panel
  → file picker opens (.sql filter)
  → file contents sent to POST /api/builder/import-sql
  → response parsed: schema + warnings
  → builder-state.js: setTargetSchema(parsed schema)
  → builder-state.js: setOriginalSchema(deep clone of parsed schema)
  → if warnings: show in validation tab
  → user edits the schema in the target panel
  → migration tab shows ALTER diff between original and modified
```

---

## Edge Cases

### Type Change with Data

`ALTER COLUMN TYPE` may fail if existing data can't be cast. The diff engine adds a `USING` clause for safe casts:

```python
# Safe type casts that need USING
SAFE_CASTS = {
    ("varchar", "text"): None,            # implicit, no USING needed
    ("text", "varchar"): "USING {col}::varchar({n})",
    ("integer", "bigint"): None,          # implicit widening
    ("bigint", "integer"): "USING {col}::integer",  # may overflow
    ("varchar", "integer"): "USING {col}::integer",  # may fail
    ("integer", "varchar"): "USING {col}::varchar",
}
```

### Column Rename Detection

The differ does NOT detect renames — a renamed column appears as a drop + add. This is a known limitation. Column rename detection would require fuzzy matching (same type, similar position) which is fragile. Users should manually handle renames via the raw SQL tab.

### Destructive Operations Warning

Any DROP operation in the migration output gets flagged with a comment:

```sql
-- WARNING: Destructive operation — data will be lost
ALTER TABLE "users" DROP COLUMN "old_field";
```
