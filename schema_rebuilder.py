"""Schema rebuilder — generates a redesigned PG schema from CSV designer state.

Pure functions that take the designer's detected state (loaded_tables,
loaded_dataframes, detected_relationships) and produce a complete target
PostgreSQL schema: normalized names, inferred types, promoted FKs,
surrogate PKs, ENUM extraction, FK indexes.

Output:
    {
        "schema":    <builder schema dict>,  # loadable into Builder page
        "ddl":       <full SQL string>,
        "report":    <markdown decisions log>,
        "decisions": <list of decision dicts>,
    }

Conventions (per user config):
    - Table names: singular snake_case (customers -> customer)
    - Surrogate PK naming: {table}_id (user -> user_id)
    - Keep flat: do not extract lookup tables from high-cardinality strings
    - Skip audit columns (no created_at/updated_at added)
"""

from __future__ import annotations

import re

from schema_builder import (
    create_empty_schema,
    create_table,
    create_column,
    add_table,
    add_column,
    add_constraint,
    add_index,
    add_enum,
    generate_constraint_name,
    generate_index_name,
)
from type_mapper import suggest_pg_type
from ddl_generator import generate_full_ddl

ENUM_MAX_UNIQUE = 15
ENUM_MIN_TOTAL = 10

_CAMEL_1 = re.compile(r'(.)([A-Z][a-z]+)')
_CAMEL_2 = re.compile(r'([a-z0-9])([A-Z])')


def to_snake_case(name: str) -> str:
    """Convert CamelCase/PascalCase/mixed to snake_case.

    CustomerID -> customer_id, OrderItems -> order_items,
    firstName -> first_name, already_snake -> already_snake
    """
    if not name:
        return name
    # Insert underscore between lower/digit and upper
    s = _CAMEL_1.sub(r'\1_\2', name)
    s = _CAMEL_2.sub(r'\1_\2', s)
    # Replace spaces, dashes, dots with underscore
    s = re.sub(r'[\s\-\.]+', '_', s)
    # Collapse multiple underscores
    s = re.sub(r'_+', '_', s)
    return s.strip('_').lower()


def singularize(name: str) -> str:
    """Best-effort plural -> singular. Conservative (wrong = still readable).

    categories -> category, orders -> order, class -> class,
    data -> data, status -> status (already singular-looking)
    """
    if not name or len(name) < 4:
        return name
    lower = name
    # -ies -> -y (categories -> category)
    if lower.endswith('ies') and len(lower) > 4:
        return lower[:-3] + 'y'
    # -ses, -xes, -zes, -ches, -shes -> drop -es
    if lower.endswith(('ses', 'xes', 'zes', 'ches', 'shes')):
        return lower[:-2]
    # -ss -> no change (class, status, address)
    if lower.endswith('ss'):
        return lower
    # -us, -is -> no change (status, analysis, corpus)
    if lower.endswith(('us', 'is')):
        return lower
    # -s -> drop
    if lower.endswith('s'):
        return lower[:-1]
    return lower


def _normalize_table_name(raw: str) -> str:
    snake = to_snake_case(raw)
    parts = snake.split('_')
    # Singularize only the last word: "order_items" -> "order_item"
    if parts:
        parts[-1] = singularize(parts[-1])
    return '_'.join(parts)


def _normalize_column_name(raw: str) -> str:
    return to_snake_case(raw)


def _is_enum_candidate(col: dict, df) -> bool:
    """True if a string column has low cardinality and is not PK/FK."""
    if col.get("key_type") in ("PK", "FK"):
        return False
    src_type = col.get("type", "")
    if src_type not in ("VARCHAR", "TEXT", "ENUM"):
        return False
    unique = col.get("unique_count", 0)
    total = col.get("total_count", 0)
    if total < ENUM_MIN_TOTAL or unique == 0:
        return False
    if unique > ENUM_MAX_UNIQUE or unique >= total:
        return False
    if df is None or col["name"] not in df.columns:
        return False
    return True


def _enum_values(df, col_name: str) -> list[str]:
    if df is None or col_name not in df.columns:
        return []
    vals = df[col_name].dropna().unique()
    return sorted(str(v) for v in vals)


def _enum_type_name(table_name: str, col_name: str) -> str:
    name = f"{table_name}_{col_name}_enum"
    return name[:63]


def _should_be_not_null(col: dict, df) -> bool:
    """NOT NULL if no nulls observed and has data."""
    if df is None or col["name"] not in df.columns:
        return not col.get("nullable", True)
    total = len(df)
    if total == 0:
        return False
    non_null = int(df[col["name"]].count())
    return non_null == total


def rebuild_schema(
    tables: list[dict],
    dataframes: dict,
    relationships: list[dict],
) -> dict:
    """Rebuild a PostgreSQL schema from designer state.

    See module docstring for output format.
    """
    decisions: list[dict] = []
    schema = create_empty_schema("public")

    # Build name map: source table name -> normalized name
    name_map: dict[str, str] = {}
    used_names: set[str] = set()
    for t in tables:
        raw = t.get("name", "")
        norm = _normalize_table_name(raw) or raw.lower()
        # Resolve collisions
        final = norm
        i = 2
        while final in used_names:
            final = f"{norm}_{i}"
            i += 1
        used_names.add(final)
        name_map[raw] = final
        if final != raw:
            decisions.append({
                "kind": "rename_table",
                "source": raw,
                "target": final,
                "reason": "Normalized to snake_case singular",
            })

    # Per-table column name maps: (source_table_name, source_col) -> normalized col
    col_map: dict[tuple[str, str], str] = {}

    # Pass 1: build tables with columns, types, enums, surrogate PKs
    for src_table in tables:
        src_name = src_table.get("name", "")
        tgt_name = name_map[src_name]
        df = dataframes.get(src_name)

        target = create_table(tgt_name)

        # Track existing PK columns (if any) to decide on surrogate
        detected_pk_cols: list[str] = []

        used_cols: set[str] = set()
        for col in src_table.get("columns", []):
            src_col_name = col.get("name", "")
            norm = _normalize_column_name(src_col_name) or src_col_name.lower()
            final = norm
            i = 2
            while final in used_cols:
                final = f"{norm}_{i}"
                i += 1
            used_cols.add(final)
            col_map[(src_name, src_col_name)] = final
            if final != src_col_name:
                decisions.append({
                    "kind": "rename_column",
                    "table": tgt_name,
                    "source": src_col_name,
                    "target": final,
                    "reason": "Normalized to snake_case",
                })

            # Enum promotion
            if _is_enum_candidate(col, df):
                values = _enum_values(df, src_col_name)
                enum_name = _enum_type_name(tgt_name, final)
                if not any(e["name"] == enum_name for e in schema["enums"]):
                    add_enum(schema, {"name": enum_name, "values": values})
                    decisions.append({
                        "kind": "create_enum",
                        "table": tgt_name,
                        "column": final,
                        "enum_name": enum_name,
                        "values": values,
                        "reason": (
                            f"{len(values)} distinct values in "
                            f"{col.get('total_count', 0)} rows — promoted to ENUM"
                        ),
                    })
                pg_type = enum_name
                confidence = "high"
                reason = f"Promoted to enum {enum_name}"
            else:
                suggestion = suggest_pg_type(
                    source_type=col.get("type", "TEXT"),
                    column_name=src_col_name,
                    nullable=col.get("nullable", True),
                    unique_count=col.get("unique_count", 0),
                    total_count=col.get("total_count", 0),
                    df=df,
                )
                pg_type = suggestion["type"]
                confidence = suggestion["confidence"]
                reason = suggestion["reason"]

            not_null = _should_be_not_null(col, df)
            is_pk = col.get("key_type") == "PK"
            is_uq = col.get("key_type") == "UQ"
            if is_pk:
                detected_pk_cols.append(final)

            new_col = create_column(
                name=final,
                col_type=pg_type,
                nullable=not not_null,
                is_primary_key=is_pk,
                is_unique=is_uq,
            )
            add_column(target, new_col)

            decisions.append({
                "kind": "column_type",
                "table": tgt_name,
                "column": final,
                "source_type": col.get("type"),
                "target_type": pg_type,
                "not_null": not_null,
                "confidence": confidence,
                "reason": reason,
            })

        # Surrogate PK if none detected
        if not detected_pk_cols:
            surrogate = f"{tgt_name}_id"
            # If name collides with an existing column, suffix
            if surrogate in used_cols:
                surrogate = f"{tgt_name}_pk"
            surrogate_col = create_column(
                name=surrogate,
                col_type="bigint",
                nullable=False,
                identity="ALWAYS",
                is_primary_key=True,
            )
            # Insert at the beginning
            target["columns"].insert(0, surrogate_col)
            add_constraint(target, {
                "type": "pk",
                "columns": [surrogate],
                "name": generate_constraint_name(tgt_name, [surrogate], "pk"),
            })
            decisions.append({
                "kind": "surrogate_pk",
                "table": tgt_name,
                "column": surrogate,
                "reason": "No detected PK; added bigint IDENTITY surrogate",
            })
        else:
            # Emit explicit PK constraint for detected PK columns
            add_constraint(target, {
                "type": "pk",
                "columns": detected_pk_cols,
                "name": generate_constraint_name(tgt_name, detected_pk_cols, "pk"),
            })

        add_table(schema, target)

    # Pass 2: promote detected relationships to FK constraints + indexes
    seen_fks: set[tuple[str, tuple[str, ...], str]] = set()
    for rel in relationships:
        src_t = rel.get("source_table", "")
        src_c = rel.get("source_column", "")
        tgt_t = rel.get("target_table", "")
        tgt_c = rel.get("target_column", "")
        if src_t not in name_map or tgt_t not in name_map:
            continue
        norm_src_t = name_map[src_t]
        norm_tgt_t = name_map[tgt_t]
        norm_src_c = col_map.get((src_t, src_c))
        norm_tgt_c = col_map.get((tgt_t, tgt_c))
        if not norm_src_c or not norm_tgt_c:
            continue
        key = (norm_src_t, (norm_src_c,), norm_tgt_t)
        if key in seen_fks:
            continue
        seen_fks.add(key)

        target = next((t for t in schema["tables"] if t["name"] == norm_src_t), None)
        if not target:
            continue
        fk_name = generate_constraint_name(norm_src_t, [norm_src_c], "fk")
        add_constraint(target, {
            "type": "fk",
            "columns": [norm_src_c],
            "refTable": norm_tgt_t,
            "refColumns": [norm_tgt_c],
            "onDelete": "NO ACTION",
            "onUpdate": "NO ACTION",
            "name": fk_name,
        })
        idx_name = generate_index_name(norm_src_t, [norm_src_c])
        add_index(target, {
            "name": idx_name,
            "columns": [norm_src_c],
            "type": "btree",
            "unique": False,
        })
        decisions.append({
            "kind": "foreign_key",
            "from_table": norm_src_t,
            "from_column": norm_src_c,
            "to_table": norm_tgt_t,
            "to_column": norm_tgt_c,
            "relationship": rel.get("type", "unknown"),
            "confidence": rel.get("confidence", "unknown"),
            "reason": f"Detected {rel.get('type', '?')} relationship",
        })

    ddl = generate_full_ddl(schema)
    report = _build_report(schema, decisions, tables, relationships)
    return {
        "schema": schema,
        "ddl": ddl,
        "report": report,
        "decisions": decisions,
    }


def _build_report(
    schema: dict,
    decisions: list[dict],
    source_tables: list[dict],
    relationships: list[dict],
) -> str:
    """Markdown explanation of every rebuild decision — LLM-friendly."""
    lines: list[str] = []
    lines.append("# Schema Rebuild Report")
    lines.append("")
    lines.append(
        f"Rebuilt **{len(schema['tables'])} tables** from "
        f"{len(source_tables)} CSVs with {len(relationships)} detected relationships."
    )
    lines.append("")
    lines.append("## Conventions Applied")
    lines.append("- Table names: singular snake_case")
    lines.append("- Column names: snake_case")
    lines.append("- Surrogate PK naming: `{table}_id` (bigint IDENTITY)")
    lines.append("- No lookup table extraction (kept flat)")
    lines.append("- No audit columns added")
    lines.append("")

    renames_t = [d for d in decisions if d["kind"] == "rename_table"]
    if renames_t:
        lines.append("## Table Renames")
        for d in renames_t:
            lines.append(f"- `{d['source']}` → `{d['target']}`")
        lines.append("")

    surrogates = [d for d in decisions if d["kind"] == "surrogate_pk"]
    if surrogates:
        lines.append("## Surrogate Primary Keys Added")
        for d in surrogates:
            lines.append(f"- **{d['table']}**: `{d['column']}` ({d['reason']})")
        lines.append("")

    enums = [d for d in decisions if d["kind"] == "create_enum"]
    if enums:
        lines.append("## ENUM Types Created")
        for d in enums:
            vals = ", ".join(f"`{v}`" for v in d["values"])
            lines.append(
                f"- **{d['enum_name']}** for `{d['table']}.{d['column']}` "
                f"({d['reason']})"
            )
            lines.append(f"  - values: {vals}")
        lines.append("")

    fks = [d for d in decisions if d["kind"] == "foreign_key"]
    if fks:
        lines.append("## Foreign Keys Promoted")
        for d in fks:
            lines.append(
                f"- `{d['from_table']}.{d['from_column']}` → "
                f"`{d['to_table']}.{d['to_column']}` "
                f"({d['relationship']}, confidence: {d['confidence']})"
            )
        lines.append("")

    type_changes = [
        d for d in decisions
        if d["kind"] == "column_type"
        and (d.get("source_type") or "").upper() != (d.get("target_type") or "").split("(")[0].upper()
    ]
    if type_changes:
        lines.append("## Type Refinements")
        for d in type_changes[:50]:
            tag = "NOT NULL" if d.get("not_null") else ""
            lines.append(
                f"- `{d['table']}.{d['column']}`: "
                f"{d['source_type']} → **{d['target_type']}** {tag} — {d['reason']}"
            )
        if len(type_changes) > 50:
            lines.append(f"- … and {len(type_changes) - 50} more")
        lines.append("")

    return "\n".join(lines)
