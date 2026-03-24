"""Migration generator — generates INSERT INTO...SELECT data migration SQL."""

import re
from datetime import datetime

from ddl_generator import quote_identifier


def generate_migration_sql(
    source_mapping: dict[str, dict],
    target_schema: dict,
) -> str:
    """Generate INSERT INTO...SELECT migration SQL.

    source_mapping: {
        'users.id': {'sourceTable': 'dbo_Users', 'sourceColumn': 'UserID', 'transform': None},
        'users.email': {'sourceTable': 'dbo_Users', 'sourceColumn': 'Email', 'transform': 'LOWER'},
    }
    """
    lines = [
        "-- ============================================================",
        "-- DATA MIGRATION",
        "-- Source: CSV/imported tables",
        "-- Target: PostgreSQL schema",
        "-- ============================================================",
        "",
        "BEGIN;",
        "",
    ]

    table_mappings: dict[str, list[dict]] = {}
    for target_path, source in source_mapping.items():
        parts = target_path.split(".", 1)
        if len(parts) != 2:
            continue
        table_name, col_name = parts
        table_mappings.setdefault(table_name, []).append({
            "target_column": col_name,
            "source_table": source["sourceTable"],
            "source_column": source["sourceColumn"],
            "transform": source.get("transform"),
        })

    for table_name, mappings in table_mappings.items():
        if not mappings:
            continue

        target_cols = ", ".join(quote_identifier(m["target_column"]) for m in mappings)
        source_exprs = [_build_select_expr(m) for m in mappings]
        source_table = mappings[0]["source_table"]
        select_cols = ", ".join(source_exprs)

        lines.append(f"-- Migrate: {source_table} → {table_name}")
        lines.append(f'INSERT INTO {quote_identifier(table_name)} ({target_cols})')
        lines.append(f'SELECT {select_cols}')
        lines.append(f'FROM {quote_identifier(source_table)};')
        lines.append("")

    lines.append("COMMIT;")
    return "\n".join(lines)


def _build_select_expr(mapping: dict) -> str:
    """Build a SELECT expression for a single column mapping."""
    col = quote_identifier(mapping["source_column"])
    transform = mapping.get("transform")

    if not transform:
        return col

    transforms = {
        "LOWER": f"LOWER({col})",
        "UPPER": f"UPPER({col})",
        "TRIM": f"TRIM({col})",
        "CAST_INT": f"CAST({col} AS INTEGER)",
        "CAST_BIGINT": f"CAST({col} AS BIGINT)",
        "CAST_BOOLEAN": f"CAST({col} AS BOOLEAN)",
        "CAST_TIMESTAMPTZ": f"CAST({col} AS TIMESTAMPTZ)",
        "CAST_UUID": f"CAST({col} AS UUID)",
        "CAST_NUMERIC": f"CAST({col} AS NUMERIC)",
        "CAST_JSONB": f"CAST({col} AS JSONB)",
        "NULLIF_EMPTY": f"NULLIF(TRIM({col}), '')",
    }

    return transforms.get(transform, col)


def generate_export_filename(schema_name: str, export_type: str) -> str:
    """Generate a safe filename for export."""
    safe_name = re.sub(r'[^\w\-]', '_', schema_name)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    suffixes = {
        "ddl": f"{safe_name}_ddl_{timestamp}.sql",
        "migration": f"{safe_name}_migration_{timestamp}.sql",
        "schema": f"{safe_name}_schema_{timestamp}.json",
    }
    return suffixes.get(export_type, f"{safe_name}_{timestamp}.sql")
