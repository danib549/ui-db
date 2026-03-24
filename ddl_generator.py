"""DDL generator — generates PostgreSQL DDL from schema definitions.

SQL style conventions:
- Uppercase SQL keywords (CREATE TABLE, ALTER TABLE, NOT NULL, etc.)
- Lowercase quoted identifiers ("users", "created_at")
- 2-space indentation for column/constraint defs
- Section comment headers between ENUMs, TABLEs, INDEXes
- One definition per line, blank line between tables
"""

from datetime import datetime, timezone


def quote_identifier(name: str) -> str:
    """Quote a PostgreSQL identifier safely."""
    if '"' in name:
        raise ValueError(f"Cannot quote identifier containing double quote: {name}")
    return f'"{name}"'


def generate_column_def(col: dict) -> str:
    """Generate a single column definition line."""
    parts = [quote_identifier(col["name"])]

    if col.get("identity"):
        base_type = col["type"].upper()
        parts.append(f"{base_type} GENERATED {col['identity']} AS IDENTITY")
    else:
        parts.append(_format_type(col["type"]))

    if not col.get("nullable", True):
        parts.append("NOT NULL")

    if col.get("defaultValue") is not None:
        parts.append(f"DEFAULT {col['defaultValue']}")

    return " ".join(parts)


def generate_constraint_def(constraint: dict) -> str:
    """Generate a table-level constraint definition."""
    cols = ", ".join(quote_identifier(c) for c in constraint["columns"])

    if constraint["type"] == "pk":
        return f'CONSTRAINT {quote_identifier(constraint["name"])} PRIMARY KEY ({cols})'

    if constraint["type"] == "fk":
        ref_cols = ", ".join(quote_identifier(c) for c in constraint["refColumns"])
        parts = [
            f'CONSTRAINT {quote_identifier(constraint["name"])}',
            f'FOREIGN KEY ({cols})',
            f'REFERENCES {quote_identifier(constraint["refTable"])} ({ref_cols})',
        ]
        if constraint.get("onDelete", "NO ACTION") != "NO ACTION":
            parts.append(f'ON DELETE {constraint["onDelete"]}')
        if constraint.get("onUpdate", "NO ACTION") != "NO ACTION":
            parts.append(f'ON UPDATE {constraint["onUpdate"]}')
        return " ".join(parts)

    if constraint["type"] == "unique":
        return f'CONSTRAINT {quote_identifier(constraint["name"])} UNIQUE ({cols})'

    if constraint["type"] == "check":
        return f'CONSTRAINT {quote_identifier(constraint["name"])} CHECK ({constraint["expression"]})'

    return ""


def generate_create_table(table: dict) -> str:
    """Generate CREATE TABLE statement from table definition."""
    prefix = {
        "permanent": "CREATE TABLE",
        "temp": "CREATE TEMP TABLE",
        "unlogged": "CREATE UNLOGGED TABLE",
    }.get(table.get("tableType", "permanent"), "CREATE TABLE")

    exists = "IF NOT EXISTS " if table.get("ifNotExists") else ""
    header = f'{prefix} {exists}{quote_identifier(table["name"])} ('

    col_defs: list[str] = []
    for col in table.get("columns", []):
        col_defs.append("  " + generate_column_def(col))

    for constraint in table.get("constraints", []):
        col_defs.append("  " + generate_constraint_def(constraint))

    body = ",\n".join(col_defs)
    sql = f"{header}\n{body}\n);"

    if table.get("comment"):
        comment = table["comment"].replace("'", "''")
        sql += f'\n\nCOMMENT ON TABLE {quote_identifier(table["name"])} IS \'{comment}\';'

    return sql


def generate_index(table_name: str, idx: dict) -> str:
    """Generate CREATE INDEX statement."""
    cols = ", ".join(quote_identifier(c) for c in idx["columns"])
    unique = "UNIQUE " if idx.get("unique") else ""
    using = f" USING {idx['type'].upper()}" if idx.get("type", "btree") != "btree" else ""
    name = quote_identifier(idx["name"])
    table = quote_identifier(table_name)
    return f'CREATE {unique}INDEX {name} ON {table}{using} ({cols});'


def topological_sort_tables(tables: list[dict]) -> tuple[list[dict], list[dict]]:
    """Sort tables by FK dependencies. Returns (ordered_tables, circular_fk_constraints).

    Uses Kahn's algorithm. Circular FKs are separated for ALTER TABLE pass.
    """
    deps: dict[str, set[str]] = {t["name"]: set() for t in tables}
    all_fk_constraints: dict[str, list[dict]] = {t["name"]: [] for t in tables}

    for table in tables:
        for constraint in table.get("constraints", []):
            if constraint["type"] == "fk":
                ref = constraint["refTable"]
                if ref != table["name"] and ref in deps:
                    deps[table["name"]].add(ref)
                all_fk_constraints[table["name"]].append(constraint)

    in_degree = {name: len(d) for name, d in deps.items()}
    queue = [name for name, deg in in_degree.items() if deg == 0]
    ordered_names: list[str] = []

    while queue:
        node = queue.pop(0)
        ordered_names.append(node)
        for name, d in deps.items():
            if node in d:
                d.remove(node)
                in_degree[name] -= 1
                if in_degree[name] == 0:
                    queue.append(name)

    circular_fks: list[dict] = []
    remaining = [name for name in deps if name not in ordered_names]

    if remaining:
        for name in remaining:
            ordered_names.append(name)
            for fk in all_fk_constraints[name]:
                if fk["refTable"] in remaining or fk["refTable"] not in {t["name"] for t in tables}:
                    circular_fks.append({"table": name, "constraint": fk})

    table_map = {t["name"]: t for t in tables}
    ordered = [table_map[name] for name in ordered_names if name in table_map]

    return ordered, circular_fks


def generate_full_ddl(schema: dict) -> str:
    """Generate complete PostgreSQL DDL for a schema.

    Order: header → BEGIN → ENUMs → TABLEs (sorted) → ALTER TABLE (circular FKs)
    → INDEXes → COMMENTs → COMMIT
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    table_count = len(schema.get("tables", []))

    lines = [
        "-- ============================================================",
        "-- Generated by DB Diagram Visualizer",
        f"-- Schema: {schema.get('name', 'public')}",
        f"-- Generated: {now}",
        f"-- Tables: {table_count}",
        "-- ============================================================",
        "",
        "SET client_encoding = 'UTF8';",
        "",
        "BEGIN;",
        "",
    ]

    # Enums
    enums = schema.get("enums", [])
    if enums:
        lines.append("-- ============================================================")
        lines.append("-- ENUM TYPES")
        lines.append("-- ============================================================")
        lines.append("")
        for enum in enums:
            values = ", ".join(f"'{v}'" for v in enum["values"])
            lines.append(f'CREATE TYPE {quote_identifier(enum["name"])} AS ENUM ({values});')
        lines.append("")

    # Tables (sorted)
    tables = schema.get("tables", [])
    ordered, circular_fks = topological_sort_tables(tables)

    if ordered:
        lines.append("-- ============================================================")
        lines.append("-- TABLES (ordered by FK dependencies)")
        lines.append("-- ============================================================")
        lines.append("")

    circular_table_names = {item["table"] for item in circular_fks}
    circular_constraint_names = {item["constraint"]["name"] for item in circular_fks}

    for i, table in enumerate(ordered):
        dep_info = _get_table_deps(table)
        dep_str = f" (depends on: {', '.join(dep_info)})" if dep_info else " (no dependencies)"
        lines.append(f"-- Table {i + 1} of {len(ordered)}: {table['name']}{dep_str}")

        clean_table = _remove_circular_fks(table, circular_constraint_names)
        lines.append(generate_create_table(clean_table))
        lines.append("")

    # Circular FK constraints via ALTER TABLE
    if circular_fks:
        lines.append("-- ============================================================")
        lines.append("-- DEFERRED CONSTRAINTS (circular FK dependencies)")
        lines.append("-- ============================================================")
        lines.append("")
        for item in circular_fks:
            table_name = item["table"]
            fk = item["constraint"]
            cols = ", ".join(quote_identifier(c) for c in fk["columns"])
            ref_cols = ", ".join(quote_identifier(c) for c in fk["refColumns"])
            line = (
                f'ALTER TABLE {quote_identifier(table_name)} '
                f'ADD CONSTRAINT {quote_identifier(fk["name"])} '
                f'FOREIGN KEY ({cols}) '
                f'REFERENCES {quote_identifier(fk["refTable"])} ({ref_cols})'
            )
            if fk.get("onDelete", "NO ACTION") != "NO ACTION":
                line += f' ON DELETE {fk["onDelete"]}'
            if fk.get("onUpdate", "NO ACTION") != "NO ACTION":
                line += f' ON UPDATE {fk["onUpdate"]}'
            lines.append(line + ";")
        lines.append("")

    # Indexes
    has_indexes = any(t.get("indexes") for t in ordered)
    if has_indexes:
        lines.append("-- ============================================================")
        lines.append("-- INDEXES")
        lines.append("-- ============================================================")
        lines.append("")
        for table in ordered:
            for idx in table.get("indexes", []):
                lines.append(generate_index(table["name"], idx))
        lines.append("")

    # Column comments
    comments: list[str] = []
    for table in ordered:
        for col in table.get("columns", []):
            if col.get("comment"):
                comment = col["comment"].replace("'", "''")
                comments.append(
                    f'COMMENT ON COLUMN {quote_identifier(table["name"])}.{quote_identifier(col["name"])} '
                    f"IS '{comment}';"
                )

    if comments:
        lines.append("-- ============================================================")
        lines.append("-- COMMENTS")
        lines.append("-- ============================================================")
        lines.append("")
        lines.extend(comments)
        lines.append("")

    lines.append("COMMIT;")

    return "\n".join(lines)


def generate_table_preview(table: dict) -> str:
    """Generate DDL preview for a single table (no transaction wrapping)."""
    return generate_create_table(table)


# ---- Internal helpers ----

def _format_type(type_str: str) -> str:
    """Format a type string for DDL output."""
    return type_str


def _get_table_deps(table: dict) -> list[str]:
    """Get list of tables this table depends on via FK."""
    deps: set[str] = set()
    for c in table.get("constraints", []):
        if c["type"] == "fk" and c["refTable"] != table["name"]:
            deps.add(c["refTable"])
    return sorted(deps)


def _remove_circular_fks(table: dict, circular_constraint_names: set[str]) -> dict:
    """Return a copy of table with circular FK constraints removed."""
    if not circular_constraint_names:
        return table

    clean = dict(table)
    clean["constraints"] = [
        c for c in table.get("constraints", [])
        if c["name"] not in circular_constraint_names
    ]
    return clean
