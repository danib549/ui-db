"""Relationship analysis module — detects FK relationships between tables."""

import pandas as pd

from key_detector import find_fk_candidates


def detect_relationships(
    tables: list[dict],
    dataframes: dict[str, pd.DataFrame],
) -> list[dict]:
    """Detect FK relationships across all loaded tables.

    Builds a PK index, then matches FK columns to PK columns in other
    tables using name-based heuristics.
    """
    pk_index = _build_pk_index(tables)
    relationships: list[dict] = []

    for table in tables:
        table_name = table["name"]
        source_df = dataframes.get(table_name)

        for col in table["columns"]:
            if col.get("key_type") != "FK":
                continue

            matches = _find_target_table(col["name"], table_name, pk_index, tables)
            for target_table, target_column in matches:
                target_df = dataframes.get(target_table)
                cardinality = infer_cardinality(
                    source_df, col["name"], target_df, target_column,
                )
                confidence = score_relationship(
                    col["name"], target_table, target_column,
                    col.get("type", ""), _get_column_type(tables, target_table, target_column),
                )
                relationships.append({
                    "source_table": table_name,
                    "source_column": col["name"],
                    "target_table": target_table,
                    "target_column": target_column,
                    "type": cardinality,
                    "confidence": confidence,
                })

        self_refs = detect_self_reference(table_name, table["columns"])
        for ref in self_refs:
            if source_df is not None:
                cardinality = infer_cardinality(
                    source_df, ref["source_column"], source_df, ref["target_column"],
                )
                ref["type"] = cardinality
            relationships.append(ref)

    return relationships


def infer_cardinality(
    source_df: pd.DataFrame | None,
    source_column: str,
    target_df: pd.DataFrame | None,
    target_column: str,
) -> str:
    """Infer relationship cardinality from value uniqueness.

    Returns 'one-to-one', 'one-to-many', or 'many-to-many'.
    """
    if source_df is None or target_df is None:
        return "one-to-many"

    if source_column not in source_df.columns or target_column not in target_df.columns:
        return "one-to-many"

    source_unique = source_df[source_column].nunique() == source_df[source_column].count()
    target_unique = target_df[target_column].nunique() == target_df[target_column].count()

    if source_unique and target_unique:
        return "one-to-one"
    if target_unique:
        return "one-to-many"
    return "many-to-many"


def detect_junction_table(
    table_name: str,
    columns: list[dict],
    relationships: list[dict],
) -> bool:
    """Detect whether a table is a junction/bridge table.

    A junction table has 2+ FK columns and at most 1 non-metadata,
    non-FK column.
    """
    metadata_names = {"id", "created_at", "updated_at", "deleted_at"}
    fk_columns = [c for c in columns if c.get("key_type") == "FK"]

    if len(fk_columns) < 2:
        return False

    fk_names = {c["name"].lower() for c in fk_columns}
    non_fk_non_meta = [
        c for c in columns
        if c["name"].lower() not in fk_names and c["name"].lower() not in metadata_names
        and c.get("key_type") != "PK"
    ]

    return len(non_fk_non_meta) <= 1


def detect_self_reference(
    table_name: str,
    columns: list[dict],
) -> list[dict]:
    """Detect FK columns that reference the same table.

    Example: 'manager_id' in an 'employees' table references 'employee'/'employees'.
    """
    results: list[dict] = []
    table_lower = table_name.lower()
    singular = table_lower.rstrip("s") if table_lower.endswith("s") else table_lower

    for col in columns:
        if col.get("key_type") != "FK":
            continue

        candidates = find_fk_candidates(col["name"])
        for candidate in candidates:
            if candidate == table_lower or candidate == singular:
                results.append({
                    "source_table": table_name,
                    "source_column": col["name"],
                    "target_table": table_name,
                    "target_column": "id",
                    "type": "one-to-many",
                    "confidence": "medium",
                })
                break

    return results


def score_relationship(
    source_col: str,
    target_table: str,
    target_col: str,
    source_dtype: str,
    target_dtype: str,
) -> str:
    """Score the confidence of a detected relationship.

    Returns 'high', 'medium', or 'low'.
    """
    score = 0

    # Name match: FK column base matches target table
    candidates = find_fk_candidates(source_col)
    target_lower = target_table.lower()
    if target_lower in candidates:
        score += 2

    # Target column is 'id' (most common PK name)
    if target_col.lower() == "id":
        score += 1

    # Type compatibility
    if source_dtype and target_dtype and source_dtype == target_dtype:
        score += 1

    if score >= 3:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


# --- Private helpers ---

def _build_pk_index(tables: list[dict]) -> dict[str, list[str]]:
    """Build a mapping of table_name -> list of PK column names."""
    index: dict[str, list[str]] = {}
    for table in tables:
        pks = [c["name"] for c in table["columns"] if c.get("key_type") == "PK"]
        if pks:
            index[table["name"]] = pks
    return index


def _find_target_table(
    fk_column: str,
    source_table: str,
    pk_index: dict[str, list[str]],
    tables: list[dict],
) -> list[tuple[str, str]]:
    """Find target (table, pk_column) pairs for a given FK column."""
    candidates = find_fk_candidates(fk_column)
    matches: list[tuple[str, str]] = []

    for table_name, pk_cols in pk_index.items():
        if table_name == source_table:
            continue
        table_lower = table_name.lower()
        if table_lower in candidates:
            matches.append((table_name, pk_cols[0]))

    return matches


def _get_column_type(
    tables: list[dict],
    table_name: str,
    column_name: str,
) -> str:
    """Look up the display type for a specific column in a table."""
    for table in tables:
        if table["name"] == table_name:
            for col in table["columns"]:
                if col["name"] == column_name:
                    return col.get("type", "")
    return ""
