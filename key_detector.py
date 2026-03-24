"""Key detection module — identifies PKs, FKs, and unique columns."""

import re


def detect_keys(
    table_name: str,
    columns: list[dict],
    all_table_names: list[str] | None = None,
) -> list[dict]:
    """Detect key types for each column in a table.

    Rules:
      - Column named 'id' (any case) with all unique non-null values -> PK
      - Column named '<TableName>ID' with all unique non-null values -> PK
      - Column named 'uuid' or 'guid' with all unique values -> PK
      - Column ending in '_id', '_ref', '_key', 'Id', 'ID' -> FK candidate
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
    name = col["name"]
    name_lower = name.lower()
    is_all_unique = col["unique_count"] == col["total_count"] and col["total_count"] > 0
    is_non_null = not col["nullable"]

    # PK: 'id', 'ID', 'Id'
    if name_lower == "id" and is_all_unique and is_non_null:
        return "PK"

    # PK: '<TableName>ID' e.g. 'CustomerID' in table 'Customers'
    if _is_table_pk(name, table_name) and is_all_unique and is_non_null:
        return "PK"

    # PK: uuid/guid
    if name_lower in ("uuid", "guid") and is_all_unique:
        return "PK"

    # FK: check if column name references another table
    if _is_fk_candidate(name):
        return "FK"

    # UQ: all unique non-null values
    if is_all_unique and is_non_null:
        return "UQ"

    return None


def _is_table_pk(column_name: str, table_name: str) -> bool:
    """Check if column is '<TableName>ID' pattern for its own table.

    Handles: CustomerID in Customers, customer_id in customers,
    OrderId in Orders, etc.
    """
    col_lower = column_name.lower()
    table_lower = table_name.lower()
    singular = table_lower.rstrip("s") if table_lower.endswith("s") else table_lower

    # customer_id in customers table, or customerid in customers table
    col_base = col_lower.replace("_", "")
    if col_base == singular + "id" or col_base == table_lower + "id":
        return True

    return False


def _is_fk_candidate(column_name: str) -> bool:
    """Check whether a column name looks like a foreign key."""
    return len(find_fk_candidates(column_name)) > 0


def _split_camel_case(name: str) -> list[str]:
    """Split a CamelCase or PascalCase name into parts.

    'CustomerID' -> ['Customer', 'ID']
    'orderItemId' -> ['order', 'Item', 'Id']
    'user_id' -> ['user_id'] (not camelCase, handled elsewhere)
    """
    parts = re.sub(r'([a-z])([A-Z])', r'\1_\2', name)
    parts = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', parts)
    return parts.split('_')


def find_fk_candidates(column_name: str) -> list[str]:
    """Derive possible target table names from an FK column name.

    Handles both snake_case and PascalCase/camelCase naming:
      'user_id'     -> ['user', 'users']
      'order_ref'   -> ['order', 'orders']
      'CustomerID'  -> ['customer', 'customers']
      'OrderId'     -> ['order', 'orders']
      'categoryId'  -> ['category', 'categorys', 'categorie', 'categories']
    """
    candidates: list[str] = []

    # Try snake_case suffixes first
    lower = column_name.lower()
    for suffix in ("_id", "_ref", "_key"):
        if lower.endswith(suffix):
            base = lower[: -len(suffix)]
            if base:
                candidates.extend(_pluralize(base))
            return candidates

    # Try PascalCase/camelCase: split and check if last part is Id/ID/Ref/Key
    parts = _split_camel_case(column_name)
    if len(parts) >= 2:
        last = parts[-1].lower()
        if last in ("id", "ref", "key"):
            base = "_".join(parts[:-1]).lower()
            if base:
                candidates.extend(_pluralize(base))
            return candidates

    return candidates


def _pluralize(base: str) -> list[str]:
    """Return singular and plural forms of a base name."""
    forms = [base]
    if base.endswith("s"):
        # Already plural-looking, add singular
        forms.append(base.rstrip("s"))
    elif base.endswith("y"):
        # category -> categories
        forms.append(base + "s")
        forms.append(base[:-1] + "ie")
        forms.append(base[:-1] + "ies")
    else:
        forms.append(base + "s")
    return forms
