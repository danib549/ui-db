"""CSV parsing module — reads DataFrames and extracts column metadata."""

import pandas as pd


DTYPE_MAP: dict[str, str] = {
    "int64": "INT",
    "float64": "FLOAT",
    "object": "VARCHAR",
    "bool": "BOOLEAN",
    "datetime64[ns]": "TIMESTAMP",
    "timedelta64[ns]": "INTERVAL",
    "category": "ENUM",
}


def parse_csv_columns(df: pd.DataFrame) -> list[dict]:
    """Extract column metadata from a DataFrame.

    For each column: detect dtype, map to display type, check nullable,
    count unique and total values. Object columns with avg length > 255
    are mapped to TEXT instead of VARCHAR.
    """
    columns: list[dict] = []

    for col_name in df.columns:
        series = df[col_name]
        dtype_str = str(series.dtype)
        display_type = _map_dtype(dtype_str, series)
        nullable = bool(series.isna().any())
        unique_count = int(series.nunique())
        total_count = int(series.count())

        columns.append({
            "name": col_name,
            "type": display_type,
            "nullable": nullable,
            "unique_count": unique_count,
            "total_count": total_count,
        })

    return columns


def _map_dtype(dtype_str: str, series: pd.Series) -> str:
    """Map a pandas dtype string to a display type.

    Falls back to VARCHAR for unknown types. Promotes VARCHAR to TEXT
    when average string length exceeds 255.
    """
    display_type = DTYPE_MAP.get(dtype_str, "VARCHAR")

    if display_type == "VARCHAR" and dtype_str == "object":
        avg_len = _average_string_length(series)
        if avg_len > 255:
            return "TEXT"

    return display_type


def _average_string_length(series: pd.Series) -> float:
    """Calculate average string length of non-null values in a series."""
    non_null = series.dropna()
    if non_null.empty:
        return 0.0
    return float(non_null.astype(str).str.len().mean())
