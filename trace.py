"""Value tracing module — BFS traversal across FK relationships."""

from collections import deque

import pandas as pd


def trace_value(
    tables: list[dict],
    relationships: list[dict],
    dataframes: dict[str, pd.DataFrame],
    start_table: str,
    start_column: str,
    value: str,
    max_depth: int = 5,
) -> dict:
    """Trace a value across tables by following FK relationships via BFS.

    Starting from (start_table, start_column, value), finds connected rows
    in other tables by following relationship edges.

    Returns nodes (tables visited), edges (relationships traversed),
    and the maximum depth reached.
    """
    nodes: list[dict] = []
    edges: list[dict] = []
    visited: set[tuple[str, str, str]] = set()

    queue: deque[tuple[str, str, str, int]] = deque()
    queue.append((start_table, start_column, value, 0))
    visited.add((start_table, start_column, value))

    depth_reached = 0

    while queue:
        table, column, val, depth = queue.popleft()

        if depth > max_depth:
            continue

        depth_reached = max(depth_reached, depth)
        matching_values = _find_matching_values(dataframes, table, column, val)

        nodes.append({
            "table": table,
            "column": column,
            "values": matching_values,
            "depth": depth,
        })

        if depth >= max_depth:
            continue

        neighbors = _find_connected_relationships(table, column, relationships)
        for rel in neighbors:
            next_table, next_column, from_col = _resolve_next_hop(rel, table)
            linked_values = _get_linked_values(
                dataframes, table, from_col, val, next_table, next_column,
            )
            for linked_val in linked_values:
                visit_key = (next_table, next_column, linked_val)
                if visit_key not in visited:
                    visited.add(visit_key)
                    queue.append((next_table, next_column, linked_val, depth + 1))
                    edges.append({
                        "from_table": table,
                        "from_column": from_col,
                        "to_table": next_table,
                        "to_column": next_column,
                    })

    return {
        "nodes": nodes,
        "edges": edges,
        "depth_reached": depth_reached,
    }


def _find_matching_values(
    dataframes: dict[str, pd.DataFrame],
    table: str,
    column: str,
    value: str,
) -> list[str]:
    """Find all distinct values in a column that match the given value."""
    df = dataframes.get(table)
    if df is None or column not in df.columns:
        return [value]

    matches = df[df[column].astype(str) == str(value)][column]
    return [str(v) for v in matches.unique().tolist()]


def _find_connected_relationships(
    table: str,
    column: str,
    relationships: list[dict],
) -> list[dict]:
    """Find relationships where this table.column is on either side."""
    connected: list[dict] = []
    for rel in relationships:
        if rel["source_table"] == table and rel["source_column"] == column:
            connected.append(rel)
        elif rel["target_table"] == table and rel["target_column"] == column:
            connected.append(rel)
    return connected


def _resolve_next_hop(
    rel: dict,
    current_table: str,
) -> tuple[str, str, str]:
    """Determine the next table/column to hop to, plus the local FK column.

    Returns (next_table, next_column, from_column_on_current_table).
    """
    if rel["source_table"] == current_table:
        return rel["target_table"], rel["target_column"], rel["source_column"]
    return rel["source_table"], rel["source_column"], rel["target_column"]


def _get_linked_values(
    dataframes: dict[str, pd.DataFrame],
    source_table: str,
    source_column: str,
    source_value: str,
    target_table: str,
    target_column: str,
) -> list[str]:
    """Get target column values that link to the source value.

    Finds rows in the source table matching source_value, extracts the
    join column values, then finds corresponding values in the target table.
    """
    source_df = dataframes.get(source_table)
    target_df = dataframes.get(target_table)

    if source_df is None or target_df is None:
        return []

    if source_column not in source_df.columns or target_column not in target_df.columns:
        return []

    # Get the values from source rows that match
    source_matches = source_df[source_df[source_column].astype(str) == str(source_value)]
    if source_matches.empty:
        return []

    # The linked values are the target column values themselves
    # We need to find what values in target_column correspond to our source match
    source_vals = source_matches[source_column].astype(str).unique().tolist()

    target_matches = target_df[target_df[target_column].astype(str).isin(source_vals)]
    return [str(v) for v in target_matches[target_column].unique().tolist()]
