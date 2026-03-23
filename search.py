"""Cross-table search module — find values across all loaded tables."""

import re

import pandas as pd


MAX_MATCHES_PER_TABLE: int = 100
MAX_MATCHES_TOTAL: int = 500


def search_all_tables(
    dataframes: dict[str, pd.DataFrame],
    query: str,
    mode: str = "contains",
    scope: str = "all",
) -> dict:
    """Search for a value across all (or one) loaded tables.

    Modes: 'exact', 'contains', 'starts_with', 'regex'.
    Scope: 'all' or a specific table name.

    Returns a dict with query, mode, total count, and match list.
    Each match: {table, column, value, row_index}.
    """
    if not query:
        return {"query": query, "mode": mode, "total": 0, "matches": []}

    tables_to_search = _resolve_scope(dataframes, scope)
    matcher = _build_matcher(query, mode)

    if matcher is None:
        return {"query": query, "mode": mode, "total": 0, "matches": [], "error": "Invalid regex pattern"}

    all_matches: list[dict] = []

    for table_name, df in tables_to_search.items():
        table_matches = _search_table(table_name, df, matcher)
        all_matches.extend(table_matches[:MAX_MATCHES_PER_TABLE])
        if len(all_matches) >= MAX_MATCHES_TOTAL:
            all_matches = all_matches[:MAX_MATCHES_TOTAL]
            break

    return {
        "query": query,
        "mode": mode,
        "total": len(all_matches),
        "matches": all_matches,
    }


def _resolve_scope(
    dataframes: dict[str, pd.DataFrame],
    scope: str,
) -> dict[str, pd.DataFrame]:
    """Return the subset of dataframes to search."""
    if scope == "all":
        return dataframes
    if scope in dataframes:
        return {scope: dataframes[scope]}
    return {}


def _build_matcher(query: str, mode: str):
    """Return a callable(str) -> bool for the given mode, or None on error."""
    if mode == "exact":
        return lambda val: val == query
    if mode == "contains":
        lower_q = query.lower()
        return lambda val: lower_q in val.lower()
    if mode == "starts_with":
        lower_q = query.lower()
        return lambda val: val.lower().startswith(lower_q)
    if mode == "regex":
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            return None
        return lambda val: bool(pattern.search(val))
    # Unknown mode falls back to contains
    return _build_matcher(query, "contains")


def _search_table(
    table_name: str,
    df: pd.DataFrame,
    matcher,
) -> list[dict]:
    """Search all cells in a single table and return matches."""
    matches: list[dict] = []

    for col_name in df.columns:
        for row_idx, cell_value in df[col_name].items():
            if pd.isna(cell_value):
                continue
            str_val = str(cell_value)
            if matcher(str_val):
                matches.append({
                    "table": table_name,
                    "column": col_name,
                    "value": str_val,
                    "row_index": int(row_idx),
                })
                if len(matches) >= MAX_MATCHES_PER_TABLE:
                    return matches

    return matches
