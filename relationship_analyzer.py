"""Relationship analysis module — detects FK relationships between tables."""

import pandas as pd

from key_detector import find_fk_candidates


def detect_relationships(
    tables: list[dict],
    dataframes: dict[str, pd.DataFrame],
    value_matching: bool = False,
    name_matching: bool = True,
) -> list[dict]:
    """Detect FK relationships across all loaded tables.

    Uses three strategies in order:
      1. Name-based: FK columns matched to PK columns by naming convention
      2. Value-based: columns with matching values across tables
      3. Self-references: FK columns pointing back to same table
    Deduplicates results so the same pair isn't reported twice.
    """
    pk_index = _build_pk_index(tables)
    unique_index = _build_unique_index(tables)
    relationships: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()

    # Strategy 1: name-based matching (FK columns -> PK columns)
    if name_matching:
        for table in tables:
            table_name = table["name"]
            source_df = dataframes.get(table_name)

            for col in table["columns"]:
                if col.get("key_type") != "FK":
                    continue

                matches = _find_target_table(col["name"], table_name, pk_index, tables)
                for target_table, target_column in matches:
                    key = (table_name, col["name"], target_table, target_column)
                    if key in seen:
                        continue
                    seen.add(key)

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

    # Strategy 2: value-based matching (compare actual data across tables)
    if value_matching:
        value_rels = _detect_by_values(tables, dataframes, unique_index, seen)
        relationships.extend(value_rels)

    # Strategy 3: self-references (part of name-based detection)
    if not name_matching:
        return relationships

    for table in tables:
        table_name = table["name"]
        source_df = dataframes.get(table_name)

        self_refs = detect_self_reference(table_name, table["columns"])
        for ref in self_refs:
            key = (ref["source_table"], ref["source_column"],
                   ref["target_table"], ref["target_column"])
            if key in seen:
                continue
            seen.add(key)

            if source_df is not None:
                cardinality = infer_cardinality(
                    source_df, ref["source_column"], source_df, ref["target_column"],
                )
                ref["type"] = cardinality
            relationships.append(ref)

    return relationships


def _detect_by_values(
    tables: list[dict],
    dataframes: dict[str, pd.DataFrame],
    unique_index: dict[str, list[str]],
    seen: set[tuple[str, str, str, str]],
) -> list[dict]:
    """Detect relationships by comparing actual column values across tables.

    For each unique/PK column in table A, check if any column in table B
    has values that are a subset. This catches relationships regardless
    of column naming conventions.
    """
    relationships: list[dict] = []

    # Build lookup: for each table, its unique/PK columns and their value sets
    value_sets: dict[str, dict[str, set]] = {}
    for table_name, cols in unique_index.items():
        df = dataframes.get(table_name)
        if df is None:
            continue
        value_sets[table_name] = {}
        for col_name in cols:
            if col_name not in df.columns:
                continue
            vals = set(df[col_name].dropna().astype(str))
            if len(vals) < 2:
                continue
            value_sets[table_name][col_name] = vals

    table_list = list(dataframes.keys())

    for src_name in table_list:
        src_df = dataframes.get(src_name)
        if src_df is None:
            continue
        src_table = _find_table_meta(tables, src_name)
        if src_table is None:
            continue

        for src_col in src_table["columns"]:
            src_col_name = src_col["name"]
            if src_col_name not in src_df.columns:
                continue
            # Skip columns already detected as PK/UQ in this table
            if src_col.get("key_type") in ("PK", "UQ"):
                continue
            # Skip text/desc columns (too many false positives)
            if src_col.get("type") in ("TEXT",):
                continue

            src_vals = set(src_df[src_col_name].dropna().astype(str))
            if len(src_vals) < 2:
                continue

            # Compare against unique/PK columns in other tables
            for tgt_name, tgt_cols in value_sets.items():
                if tgt_name == src_name:
                    continue

                for tgt_col_name, tgt_vals in tgt_cols.items():
                    key = (src_name, src_col_name, tgt_name, tgt_col_name)
                    reverse_key = (tgt_name, tgt_col_name, src_name, src_col_name)
                    if key in seen or reverse_key in seen:
                        continue

                    overlap = src_vals & tgt_vals
                    if len(overlap) == 0:
                        continue

                    # Source values should be a subset of target values
                    # (FK values must exist in the referenced PK column)
                    overlap_ratio = len(overlap) / len(src_vals)
                    if overlap_ratio < 0.5:
                        continue

                    seen.add(key)
                    tgt_df = dataframes.get(tgt_name)
                    cardinality = infer_cardinality(
                        src_df, src_col_name, tgt_df, tgt_col_name,
                    )

                    # Score confidence based on overlap ratio and name similarity
                    if overlap_ratio >= 0.9:
                        confidence = "high"
                    elif overlap_ratio >= 0.7:
                        confidence = "medium"
                    else:
                        confidence = "low"

                    relationships.append({
                        "source_table": src_name,
                        "source_column": src_col_name,
                        "target_table": tgt_name,
                        "target_column": tgt_col_name,
                        "type": cardinality,
                        "confidence": confidence,
                    })

    return relationships


def _build_unique_index(tables: list[dict]) -> dict[str, list[str]]:
    """Build a mapping of table_name -> columns that are PK or UQ."""
    index: dict[str, list[str]] = {}
    for table in tables:
        cols = [
            c["name"] for c in table["columns"]
            if c.get("key_type") in ("PK", "UQ")
        ]
        if cols:
            index[table["name"]] = cols
    return index


def _find_table_meta(tables: list[dict], table_name: str) -> dict | None:
    """Find table metadata dict by name."""
    for t in tables:
        if t["name"] == table_name:
            return t
    return None


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
    """Detect whether a table is a junction/bridge table."""
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
    """Detect FK columns that reference the same table."""
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
    """Score the confidence of a detected relationship."""
    score = 0

    candidates = find_fk_candidates(source_col)
    target_lower = target_table.lower()
    if target_lower in candidates:
        score += 2

    if target_col.lower() == "id":
        score += 1

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
