"""Metadata parser — reads PK, FK, and column metadata from SQL Server export CSVs."""

import io

import pandas as pd


METADATA_SUFFIXES = (
    "Database_ForeignKeys.csv",
    "Database_PrimaryKeys.csv",
    "Database_Columns.csv",
)


def is_metadata_file(filename: str) -> bool:
    """Check if a filename is one of the metadata CSV files.

    Handles both original names (e.g. '_Database_ForeignKeys.csv') and
    sanitized names where secure_filename strips the leading underscore.
    """
    for suffix in METADATA_SUFFIXES:
        if filename.endswith(suffix):
            return True
    return False


def parse_metadata_csvs(
    raw_files: dict[str, bytes],
) -> dict:
    """Parse metadata CSV files into structured lookups.

    Args:
        raw_files: mapping of filename -> raw bytes for each metadata CSV.

    Returns a dict with keys:
        primary_keys: dict[table_name, list[column_name]]
        foreign_keys: list[dict] with keys:
            fk_name, parent_table, parent_column, referenced_table, referenced_column
        columns: dict[(table_name, column_name), dict] with type info
    """
    result = {
        "primary_keys": {},
        "foreign_keys": [],
        "columns": {},
    }

    for filename, raw in raw_files.items():
        df = _read_metadata_csv(raw)
        if df is None:
            continue

        if filename.endswith("Database_PrimaryKeys.csv"):
            result["primary_keys"] = _parse_primary_keys(df)
        elif filename.endswith("Database_ForeignKeys.csv"):
            result["foreign_keys"] = _parse_foreign_keys(df)
        elif filename.endswith("Database_Columns.csv"):
            result["columns"] = _parse_columns(df)

    return result


def build_table_name_map(
    loaded_table_names: list[str],
    metadata_table_names: set[str],
) -> dict[str, str]:
    """Build a mapping from metadata table names to loaded table names.

    The SQL export names data CSVs as '{schema}_{table}.csv' (e.g. 'dbo_Users.csv'),
    but metadata references just '{table}' (e.g. 'Users').

    Returns: dict mapping metadata_name -> loaded_name.
    """
    name_map: dict[str, str] = {}

    for meta_name in metadata_table_names:
        meta_lower = meta_name.lower()

        # Direct match first
        for loaded in loaded_table_names:
            if loaded.lower() == meta_lower:
                name_map[meta_name] = loaded
                break
        else:
            # Try suffix match: 'dbo_Users' ends with '_Users'
            for loaded in loaded_table_names:
                loaded_lower = loaded.lower()
                if loaded_lower.endswith("_" + meta_lower):
                    name_map[meta_name] = loaded
                    break

    return name_map


def apply_metadata_keys(
    table_info: dict,
    pk_lookup: dict[str, list[str]],
    col_lookup: dict[tuple[str, str], dict],
    meta_table_name: str,
) -> dict:
    """Apply PK and column type metadata to a table's columns.

    Overrides heuristic key_type and type with exact metadata values.
    """
    pk_columns = set(pk_lookup.get(meta_table_name, []))

    for col in table_info["columns"]:
        col_name = col["name"]

        # Apply PK from metadata
        if col_name in pk_columns:
            col["key_type"] = "PK"

        # Apply column type from metadata
        col_meta = col_lookup.get((meta_table_name, col_name))
        if col_meta:
            col["type"] = col_meta["data_type"]
            col["nullable"] = col_meta["is_nullable"]

    return table_info


def build_metadata_relationships(
    fk_list: list[dict],
    name_map: dict[str, str],
    tables: dict[str, dict],
    dataframes: dict[str, pd.DataFrame],
) -> list[dict]:
    """Build relationship objects from FK metadata.

    Maps metadata table names to loaded table names and creates
    relationship dicts compatible with the existing format.
    """
    from relationship_analyzer import infer_cardinality

    relationships: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()

    for fk in fk_list:
        parent = fk["parent_table"]
        referenced = fk["referenced_table"]

        # Map metadata names to loaded table names
        source_table = name_map.get(parent)
        target_table = name_map.get(referenced)

        if not source_table or not target_table:
            continue

        # Verify the tables are actually loaded
        if source_table not in tables or target_table not in tables:
            continue

        source_col = fk["parent_column"]
        target_col = fk["referenced_column"]

        key = (source_table, source_col, target_table, target_col)
        if key in seen:
            continue
        seen.add(key)

        # Mark source column as FK
        table_info = tables[source_table]
        for col in table_info["columns"]:
            if col["name"] == source_col and col.get("key_type") != "PK":
                col["key_type"] = "FK"

        # Infer cardinality from actual data
        source_df = dataframes.get(source_table)
        target_df = dataframes.get(target_table)
        cardinality = infer_cardinality(source_df, source_col, target_df, target_col)

        relationships.append({
            "source_table": source_table,
            "source_column": source_col,
            "target_table": target_table,
            "target_column": target_col,
            "type": cardinality,
            "confidence": "high",
        })

    return relationships


# --- Private helpers ---

def _read_metadata_csv(raw: bytes) -> pd.DataFrame | None:
    """Read a metadata CSV from raw bytes, trying multiple encodings."""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(encoding)
            df = pd.read_csv(io.StringIO(text), engine="python", sep=None)
            df.columns = [str(c).strip() for c in df.columns]
            return df
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    return None


def _parse_primary_keys(df: pd.DataFrame) -> dict[str, list[str]]:
    """Parse _Database_PrimaryKeys.csv into {table_name: [pk_columns]}.

    Expected columns: TableName, PrimaryKeyName, ColumnName
    """
    pk_index: dict[str, list[str]] = {}

    required = {"TableName", "ColumnName"}
    if not required.issubset(set(df.columns)):
        return pk_index

    for _, row in df.iterrows():
        table = str(row["TableName"]).strip()
        column = str(row["ColumnName"]).strip()
        if table and column:
            pk_index.setdefault(table, []).append(column)

    return pk_index


def _parse_foreign_keys(df: pd.DataFrame) -> list[dict]:
    """Parse _Database_ForeignKeys.csv into a list of FK dicts.

    Expected columns: ForeignKeyName, ParentTable, ParentColumn,
                      ReferencedTable, ReferencedColumn
    """
    fk_list: list[dict] = []

    required = {"ParentTable", "ParentColumn", "ReferencedTable", "ReferencedColumn"}
    if not required.issubset(set(df.columns)):
        return fk_list

    for _, row in df.iterrows():
        fk_list.append({
            "fk_name": str(row.get("ForeignKeyName", "")).strip(),
            "parent_table": str(row["ParentTable"]).strip(),
            "parent_column": str(row["ParentColumn"]).strip(),
            "referenced_table": str(row["ReferencedTable"]).strip(),
            "referenced_column": str(row["ReferencedColumn"]).strip(),
        })

    return fk_list


def _parse_columns(df: pd.DataFrame) -> dict[tuple[str, str], dict]:
    """Parse _Database_Columns.csv into {(table, column): type_info}.

    Expected columns: TableName, ColumnName, DataType, MaxLength, IsNullable
    """
    col_index: dict[tuple[str, str], dict] = {}

    required = {"TableName", "ColumnName", "DataType"}
    if not required.issubset(set(df.columns)):
        return col_index

    for _, row in df.iterrows():
        table = str(row["TableName"]).strip()
        column = str(row["ColumnName"]).strip()
        data_type = _normalize_sql_type(str(row["DataType"]).strip())
        max_length = int(row.get("MaxLength", 0) or 0)
        raw_nullable = row.get("IsNullable")
        is_nullable = bool(int(raw_nullable)) if pd.notna(raw_nullable) else True

        col_index[(table, column)] = {
            "data_type": data_type,
            "max_length": max_length,
            "is_nullable": is_nullable,
        }

    return col_index


def _normalize_sql_type(sql_type: str) -> str:
    """Normalize a SQL Server data type to our display types."""
    sql_upper = sql_type.upper()

    int_types = {"INT", "BIGINT", "SMALLINT", "TINYINT"}
    if sql_upper in int_types:
        return "INT"

    float_types = {"FLOAT", "REAL", "DECIMAL", "NUMERIC", "MONEY", "SMALLMONEY"}
    if sql_upper in float_types:
        return "FLOAT"

    if sql_upper in ("BIT",):
        return "BOOLEAN"

    text_types = {"TEXT", "NTEXT", "XML"}
    if sql_upper in text_types:
        return "TEXT"

    varchar_types = {"VARCHAR", "NVARCHAR", "CHAR", "NCHAR", "SYSNAME"}
    if sql_upper in varchar_types:
        return "VARCHAR"

    date_types = {"DATETIME", "DATETIME2", "SMALLDATETIME", "DATE", "TIME",
                  "DATETIMEOFFSET", "TIMESTAMP"}
    if sql_upper in date_types:
        return "TIMESTAMP"

    if sql_upper == "UNIQUEIDENTIFIER":
        return "UUID"

    binary_types = {"BINARY", "VARBINARY", "IMAGE"}
    if sql_upper in binary_types:
        return "BINARY"

    return sql_upper
