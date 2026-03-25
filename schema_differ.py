"""Schema differ — compares original vs modified schema, generates ALTER DDL."""

import re

from ddl_generator import (
    quote_identifier, generate_create_table, generate_index,
    escape_enum_value, topological_sort_tables,
)


OPERATION_ORDER = {
    "drop_index": 0,
    "drop_constraint": 1,
    "drop_column": 2,
    "drop_table": 3,
    "drop_enum": 4,
    "add_enum": 5,
    "add_enum_value": 6,
    "add_table": 7,
    "add_column": 8,
    "alter_column_type": 9,
    "alter_column_nullable": 10,
    "alter_column_default": 11,
    "add_constraint": 12,
    "add_index": 13,
    "warning": 99,
}


def diff_schemas(original: dict, modified: dict) -> list[dict]:
    """Compare two schemas and return a list of migration operations."""
    ops: list[dict] = []
    ops.extend(diff_enums(original, modified))
    ops.extend(diff_tables(original, modified))
    return order_operations(ops)


def generate_migration_ddl(original: dict, modified: dict) -> str:
    """Generate a complete ALTER-based migration script."""
    ops = diff_schemas(original, modified)

    if not ops:
        return "-- No changes detected"

    # ALTER TYPE ADD VALUE cannot run inside a transaction (PG < 12)
    pre_tx_ops = [o for o in ops if o["type"] == "add_enum_value"]
    in_tx_ops = [o for o in ops if o["type"] != "add_enum_value"]
    non_warning_count = len([o for o in ops if o["type"] != "warning"])

    lines = [
        "-- ============================================================",
        "-- MIGRATION: Schema changes",
        f"-- From: original import ({len(original.get('tables', []))} tables)",
        f"-- To: current builder state ({len(modified.get('tables', []))} tables)",
        f"-- Operations: {non_warning_count}",
        "-- ============================================================",
        "",
    ]

    if pre_tx_ops:
        lines.append("-- ALTER TYPE ... ADD VALUE cannot run inside a transaction (PG < 12)")
        for op in pre_tx_ops:
            lines.append(f"{op['sql']};")
        lines.append("")

    if in_tx_ops:
        lines.append("BEGIN;")
        lines.append("")

        current_category = None
        for op in in_tx_ops:
            category = op["type"].split("_")[0]
            if category != current_category:
                current_category = category
                lines.append(f"-- {current_category.upper()} operations")

            if op["type"] in ("drop_table", "drop_column"):
                lines.append("-- WARNING: Destructive operation — data will be lost")

            lines.append(f"{op['sql']};")

        lines.append("")
        lines.append("COMMIT;")

    return "\n".join(lines)


def order_operations(ops: list[dict]) -> list[dict]:
    """Sort operations for safe execution order."""
    return sorted(ops, key=lambda op: OPERATION_ORDER.get(op["type"], 50))


def diff_tables(original: dict, modified: dict) -> list[dict]:
    """Detect added, dropped, and modified tables."""
    ops: list[dict] = []
    orig_names = {t["name"] for t in original.get("tables", [])}
    mod_names = {t["name"] for t in modified.get("tables", [])}

    # Sort new tables by FK dependencies so referenced tables are created first
    new_tables = [_find_table(modified, n) for n in mod_names - orig_names]
    if len(new_tables) > 1:
        new_tables, circular = topological_sort_tables(new_tables)
        # Circular FKs in new tables: create tables first, add FK via ALTER later
        for item in circular:
            tbl = item["table"]
            fk = item["constraint"]
            cols = ", ".join(quote_identifier(c) for c in fk["columns"])
            ref_cols = ", ".join(quote_identifier(c) for c in fk["refColumns"])
            ops.append({
                "type": "add_constraint",
                "table": tbl,
                "details": {"constraint": fk},
                "sql": (
                    f'ALTER TABLE {quote_identifier(tbl)} '
                    f'ADD CONSTRAINT {quote_identifier(fk["name"])} '
                    f'FOREIGN KEY ({cols}) '
                    f'REFERENCES {quote_identifier(fk["refTable"])} ({ref_cols})'
                ),
            })

    for table in new_tables:
        ops.append({
            "type": "add_table",
            "table": table["name"],
            "details": {"table": table},
            "sql": generate_create_table(table).rstrip(';'),
        })

    for name in orig_names - mod_names:
        ops.append({
            "type": "drop_table",
            "table": name,
            "details": {},
            "sql": f'DROP TABLE IF EXISTS {quote_identifier(name)} CASCADE',
        })

    for name in orig_names & mod_names:
        orig_table = _find_table(original, name)
        mod_table = _find_table(modified, name)
        ops.extend(diff_columns(name, orig_table, mod_table))
        ops.extend(diff_constraints(name, orig_table, mod_table))
        ops.extend(diff_indexes(name, orig_table, mod_table))

    return ops


def diff_columns(table_name: str, original: dict, modified: dict) -> list[dict]:
    """Detect added, dropped, and modified columns within a table."""
    ops: list[dict] = []
    orig_cols = {c["name"]: c for c in original.get("columns", [])}
    mod_cols = {c["name"]: c for c in modified.get("columns", [])}

    for name in mod_cols.keys() - orig_cols.keys():
        col = mod_cols[name]
        is_not_null = not col.get("nullable", True)
        has_default = col.get("defaultValue") is not None
        has_identity = col.get("identity") is not None
        if is_not_null and not has_default and not has_identity:
            ops.append({
                "type": "warning",
                "table": table_name,
                "details": {"message": f"Adding NOT NULL column '{name}' without DEFAULT will fail if table has existing rows"},
                "sql": f"-- WARNING: Adding NOT NULL column '{name}' to '{table_name}' without DEFAULT — will fail if table has rows",
            })
        col_def = _build_column_def(col)
        ops.append({
            "type": "add_column",
            "table": table_name,
            "details": {"column": col},
            "sql": f'ALTER TABLE {quote_identifier(table_name)} ADD COLUMN {col_def}',
        })

    for name in orig_cols.keys() - mod_cols.keys():
        ops.append({
            "type": "drop_column",
            "table": table_name,
            "details": {"column_name": name},
            "sql": f'ALTER TABLE {quote_identifier(table_name)} DROP COLUMN {quote_identifier(name)}',
        })

    for name in orig_cols.keys() & mod_cols.keys():
        ops.extend(_diff_single_column(table_name, orig_cols[name], mod_cols[name]))

    return ops


def diff_constraints(table_name: str, original: dict, modified: dict) -> list[dict]:
    """Detect added and dropped constraints."""
    ops: list[dict] = []
    orig_constraints = {c["name"]: c for c in original.get("constraints", [])}
    mod_constraints = {c["name"]: c for c in modified.get("constraints", [])}

    for name in orig_constraints.keys() - mod_constraints.keys():
        ops.append({
            "type": "drop_constraint",
            "table": table_name,
            "details": {"constraint_name": name},
            "sql": f'ALTER TABLE {quote_identifier(table_name)} DROP CONSTRAINT IF EXISTS {quote_identifier(name)}',
        })

    for name in mod_constraints.keys() - orig_constraints.keys():
        constraint = mod_constraints[name]
        constraint_sql = _build_constraint_sql(table_name, constraint)
        ops.append({
            "type": "add_constraint",
            "table": table_name,
            "details": {"constraint": constraint},
            "sql": constraint_sql,
        })

    for name in orig_constraints.keys() & mod_constraints.keys():
        orig_c = orig_constraints[name]
        mod_c = mod_constraints[name]
        if _constraint_changed(orig_c, mod_c):
            ops.append({
                "type": "drop_constraint",
                "table": table_name,
                "details": {"constraint_name": name},
                "sql": f'ALTER TABLE {quote_identifier(table_name)} DROP CONSTRAINT IF EXISTS {quote_identifier(name)}',
            })
            constraint_sql = _build_constraint_sql(table_name, mod_c)
            ops.append({
                "type": "add_constraint",
                "table": table_name,
                "details": {"constraint": mod_c},
                "sql": constraint_sql,
            })

    return ops


def diff_indexes(table_name: str, original: dict, modified: dict) -> list[dict]:
    """Detect added and dropped indexes."""
    ops: list[dict] = []
    orig_indexes = {i["name"]: i for i in original.get("indexes", [])}
    mod_indexes = {i["name"]: i for i in modified.get("indexes", [])}

    for name in orig_indexes.keys() - mod_indexes.keys():
        ops.append({
            "type": "drop_index",
            "table": table_name,
            "details": {"index_name": name},
            "sql": f'DROP INDEX IF EXISTS {quote_identifier(name)}',
        })

    for name in mod_indexes.keys() - orig_indexes.keys():
        idx = mod_indexes[name]
        cols = ", ".join(quote_identifier(c) for c in idx["columns"])
        using = f" USING {idx['type'].upper()}" if idx.get("type", "btree") != "btree" else ""
        unique = "UNIQUE " if idx.get("unique") else ""
        ops.append({
            "type": "add_index",
            "table": table_name,
            "details": {"index": idx},
            "sql": f'CREATE {unique}INDEX {quote_identifier(name)} ON {quote_identifier(table_name)}{using} ({cols})',
        })

    # Modified indexes (same name, different definition)
    for name in orig_indexes.keys() & mod_indexes.keys():
        if _index_changed(orig_indexes[name], mod_indexes[name]):
            ops.append({
                "type": "drop_index",
                "table": table_name,
                "details": {"index_name": name},
                "sql": f'DROP INDEX IF EXISTS {quote_identifier(name)}',
            })
            idx = mod_indexes[name]
            cols = ", ".join(quote_identifier(c) for c in idx["columns"])
            using = f" USING {idx['type'].upper()}" if idx.get("type", "btree") != "btree" else ""
            unique = "UNIQUE " if idx.get("unique") else ""
            ops.append({
                "type": "add_index",
                "table": table_name,
                "details": {"index": idx},
                "sql": f'CREATE {unique}INDEX {quote_identifier(name)} ON {quote_identifier(table_name)}{using} ({cols})',
            })

    return ops


def diff_enums(original: dict, modified: dict) -> list[dict]:
    """Detect added, dropped, and modified enum types."""
    ops: list[dict] = []
    orig_enums = {e["name"]: e for e in original.get("enums", [])}
    mod_enums = {e["name"]: e for e in modified.get("enums", [])}

    for name in mod_enums.keys() - orig_enums.keys():
        enum = mod_enums[name]
        values = ", ".join(f"'{escape_enum_value(v)}'" for v in enum["values"])
        ops.append({
            "type": "add_enum",
            "details": {"enum": enum},
            "sql": f'CREATE TYPE {quote_identifier(name)} AS ENUM ({values})',
        })

    for name in orig_enums.keys() - mod_enums.keys():
        # Warn if any column in modified schema still uses this enum type
        dependents = []
        for table in modified.get("tables", []):
            for col in table.get("columns", []):
                if col.get("type", "").lower() == name.lower():
                    dependents.append(f'{table["name"]}.{col["name"]}')
        if dependents:
            ops.append({
                "type": "warning",
                "details": {"message": f"Dropping enum '{name}' affects columns: {', '.join(dependents)}"},
                "sql": f"-- WARNING: Dropping enum '{name}' affects columns: {', '.join(dependents)}",
            })
        ops.append({
            "type": "drop_enum",
            "details": {"enum_name": name},
            "sql": f'DROP TYPE IF EXISTS {quote_identifier(name)} CASCADE',
        })

    for name in orig_enums.keys() & mod_enums.keys():
        orig_values = orig_enums[name]["values"]
        mod_values = mod_enums[name]["values"]
        new_values = [v for v in mod_values if v not in orig_values]
        removed_values = [v for v in orig_values if v not in mod_values]

        for val in new_values:
            ops.append({
                "type": "add_enum_value",
                "details": {"enum_name": name, "value": val},
                "sql": f"ALTER TYPE {quote_identifier(name)} ADD VALUE IF NOT EXISTS '{escape_enum_value(val)}'",
            })

        if removed_values:
            ops.append({
                "type": "warning",
                "details": {
                    "message": f"Cannot remove values from enum '{name}': {removed_values}",
                },
                "sql": f"-- WARNING: Cannot remove enum values: {removed_values}",
            })

    return ops


# ---- Internal helpers ----

def _find_table(schema: dict, name: str) -> dict:
    """Find a table by name in a schema."""
    for t in schema.get("tables", []):
        if t["name"] == name:
            return t
    return {}


def _get_using_clause(col_name: str, old_type: str, new_type: str) -> str:
    """Return a USING clause for ALTER COLUMN TYPE, or empty string if not needed."""
    old_norm = old_type.lower().split("(")[0].strip()
    new_norm = new_type.lower().split("(")[0].strip()

    if old_norm == new_norm:
        return ""

    safe_implicit = {
        ("integer", "bigint"), ("smallint", "integer"), ("smallint", "bigint"),
        ("varchar", "text"), ("char", "text"), ("char", "varchar"),
        ("real", "double precision"),
    }
    if (old_norm, new_norm) in safe_implicit:
        return ""

    return f" USING {quote_identifier(col_name)}::{new_type}"


def _diff_single_column(table_name: str, orig: dict, mod: dict) -> list[dict]:
    """Compare a single column between original and modified versions."""
    ops: list[dict] = []
    col_name = orig["name"]
    tbl = quote_identifier(table_name)
    col = quote_identifier(col_name)

    # Identity change must happen before type change
    orig_identity = orig.get("identity")
    mod_identity = mod.get("identity")
    if orig_identity != mod_identity:
        if orig_identity and not mod_identity:
            ops.append({
                "type": "alter_column_default",
                "table": table_name,
                "details": {"column": col_name, "drop_identity": True},
                "sql": f'ALTER TABLE {tbl} ALTER COLUMN {col} DROP IDENTITY IF EXISTS',
            })
        elif not orig_identity and mod_identity:
            ops.append({
                "type": "alter_column_default",
                "table": table_name,
                "details": {"column": col_name, "add_identity": mod_identity},
                "sql": f'ALTER TABLE {tbl} ALTER COLUMN {col} ADD GENERATED {mod_identity} AS IDENTITY',
            })
        else:
            # Change identity type (ALWAYS <-> BY DEFAULT): drop then add
            ops.append({
                "type": "alter_column_default",
                "table": table_name,
                "details": {"column": col_name, "drop_identity": True},
                "sql": f'ALTER TABLE {tbl} ALTER COLUMN {col} DROP IDENTITY IF EXISTS',
            })
            ops.append({
                "type": "alter_column_default",
                "table": table_name,
                "details": {"column": col_name, "add_identity": mod_identity},
                "sql": f'ALTER TABLE {tbl} ALTER COLUMN {col} ADD GENERATED {mod_identity} AS IDENTITY',
            })

    if _normalize_type(orig.get("type", "")) != _normalize_type(mod.get("type", "")):
        new_type = mod["type"]
        using = _get_using_clause(col_name, orig.get("type", ""), new_type)
        ops.append({
            "type": "alter_column_type",
            "table": table_name,
            "details": {"column": col_name, "old_type": orig["type"], "new_type": new_type},
            "sql": f'ALTER TABLE {tbl} ALTER COLUMN {col} TYPE {new_type}{using}',
        })

    if orig.get("nullable") != mod.get("nullable"):
        if mod.get("nullable"):
            ops.append({
                "type": "alter_column_nullable",
                "table": table_name,
                "details": {"column": col_name, "nullable": True},
                "sql": f'ALTER TABLE {tbl} ALTER COLUMN {col} DROP NOT NULL',
            })
        else:
            ops.append({
                "type": "alter_column_nullable",
                "table": table_name,
                "details": {"column": col_name, "nullable": False},
                "sql": f'ALTER TABLE {tbl} ALTER COLUMN {col} SET NOT NULL',
            })

    orig_default = orig.get("defaultValue")
    mod_default = mod.get("defaultValue")
    if orig_default != mod_default:
        if mod_default is None:
            ops.append({
                "type": "alter_column_default",
                "table": table_name,
                "details": {"column": col_name, "default": None},
                "sql": f'ALTER TABLE {tbl} ALTER COLUMN {col} DROP DEFAULT',
            })
        else:
            ops.append({
                "type": "alter_column_default",
                "table": table_name,
                "details": {"column": col_name, "default": mod_default},
                "sql": f'ALTER TABLE {tbl} ALTER COLUMN {col} SET DEFAULT {mod_default}',
            })

    return ops


def _normalize_type(type_str: str) -> str:
    """Normalize a type string for comparison."""
    return type_str.lower().strip()


def _build_column_def(col: dict) -> str:
    """Build a column definition for ALTER TABLE ADD COLUMN."""
    from ddl_generator import generate_column_def
    return generate_column_def(col)


def _build_constraint_sql(table_name: str, constraint: dict) -> str:
    """Build ALTER TABLE ADD CONSTRAINT SQL."""
    from ddl_generator import generate_constraint_def
    constraint_def = generate_constraint_def(constraint)
    return f'ALTER TABLE {quote_identifier(table_name)} ADD {constraint_def}'


def _index_changed(orig: dict, mod: dict) -> bool:
    """Check if an index definition has been modified."""
    if orig.get("columns") != mod.get("columns"):
        return True
    if orig.get("type", "btree") != mod.get("type", "btree"):
        return True
    if orig.get("unique", False) != mod.get("unique", False):
        return True
    return False


def _constraint_changed(orig: dict, mod: dict) -> bool:
    """Check if a constraint has been modified."""
    if orig.get("type") != mod.get("type"):
        return True
    if orig.get("columns") != mod.get("columns"):
        return True
    if orig.get("type") == "fk":
        if orig.get("refTable") != mod.get("refTable"):
            return True
        if orig.get("refColumns") != mod.get("refColumns"):
            return True
        if orig.get("onDelete") != mod.get("onDelete"):
            return True
        if orig.get("onUpdate") != mod.get("onUpdate"):
            return True
    if orig.get("type") == "check":
        if orig.get("expression") != mod.get("expression"):
            return True
    return False
