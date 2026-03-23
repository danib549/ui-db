"""Key detection module — identifies PKs, FKs, and unique columns."""


def detect_keys(
    table_name: str,
    columns: list[dict],
    all_table_names: list[str] | None = None,
) -> list[dict]:
    """Detect key types for each column in a table.

    Rules:
      - Column named 'id' with all unique non-null values -> PK
      - Column named 'uuid' or 'guid' with all unique values -> PK
      - Column ending in '_id', '_ref', or '_key' -> FK candidate
      - All values unique, non-null, and not a FK candidate -> UQ
    """
    for col in columns:
        col["key_type"] = _classify_column(col, table_name, all_table_names)

    return columns


def _classify_column(
    col: dict,
    table_name: str,
    all_table_names: list[str] | None,
) -> str | None:
    """Return the key type for a single column, or None."""
    name = col["name"].lower()
    is_all_unique = col["unique_count"] == col["total_count"] and col["total_count"] > 0
    is_non_null = not col["nullable"]

    if name == "id" and is_all_unique and is_non_null:
        return "PK"

    if name in ("uuid", "guid") and is_all_unique:
        return "PK"

    if _is_fk_candidate(name):
        return "FK"

    if is_all_unique and is_non_null:
        return "UQ"

    return None


def _is_fk_candidate(column_name: str) -> bool:
    """Check whether a column name looks like a foreign key."""
    return len(find_fk_candidates(column_name)) > 0


def find_fk_candidates(column_name: str) -> list[str]:
    """Derive possible target table names from an FK column name.

    Strips the suffix (_id, _ref, _key) and returns both singular
    and plural forms.

    Examples:
        'user_id'   -> ['user', 'users']
        'order_ref' -> ['order', 'orders']
    """
    lower = column_name.lower()

    for suffix in ("_id", "_ref", "_key"):
        if lower.endswith(suffix):
            base = lower[: -len(suffix)]
            return [base, base + "s"]

    return []
