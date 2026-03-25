"""Schema builder — data structures and manipulation helpers."""


def create_empty_schema(name: str = "public") -> dict:
    """Create an empty schema structure."""
    return {
        "name": name,
        "tables": [],
        "enums": [],
    }


def create_table(
    name: str,
    table_type: str = "permanent",
    columns: list[dict] | None = None,
    constraints: list[dict] | None = None,
    indexes: list[dict] | None = None,
    comment: str | None = None,
    if_not_exists: bool = False,
) -> dict:
    """Create a table definition."""
    return {
        "name": name,
        "tableType": table_type,
        "columns": columns or [],
        "constraints": constraints or [],
        "indexes": indexes or [],
        "comment": comment,
        "ifNotExists": if_not_exists,
    }


def create_column(
    name: str,
    col_type: str = "text",
    nullable: bool = True,
    identity: str | None = None,
    default_value: str | None = None,
    is_primary_key: bool = False,
    is_unique: bool = False,
    check_expression: str | None = None,
    comment: str | None = None,
) -> dict:
    """Create a column definition."""
    return {
        "name": name,
        "type": col_type,
        "identity": identity,
        "nullable": nullable,
        "defaultValue": default_value,
        "isPrimaryKey": is_primary_key,
        "isUnique": is_unique,
        "checkExpression": check_expression,
        "comment": comment,
    }


def add_table(schema: dict, table: dict) -> dict:
    """Add a table to the schema. Returns the schema."""
    schema["tables"].append(table)
    return schema


def remove_table(schema: dict, table_name: str) -> dict:
    """Remove a table from the schema by name."""
    schema["tables"] = [t for t in schema["tables"] if t["name"] != table_name]
    return schema


def find_table(schema: dict, table_name: str) -> dict | None:
    """Find a table by name."""
    for t in schema["tables"]:
        if t["name"] == table_name:
            return t
    return None


def add_column(table: dict, column: dict) -> dict:
    """Add a column to a table. Returns the table."""
    table["columns"].append(column)
    return table


def update_column(table: dict, column_name: str, changes: dict) -> dict:
    """Update a column in a table by name. Returns the table."""
    for col in table["columns"]:
        if col["name"] == column_name:
            col.update(changes)
            break
    return table


def remove_column(table: dict, column_name: str) -> dict:
    """Remove a column from a table by name."""
    table["columns"] = [c for c in table["columns"] if c["name"] != column_name]
    return table


def find_column(table: dict, column_name: str) -> dict | None:
    """Find a column by name in a table."""
    for c in table["columns"]:
        if c["name"] == column_name:
            return c
    return None


def add_constraint(table: dict, constraint: dict) -> dict:
    """Add a constraint to a table."""
    table["constraints"].append(constraint)
    return table


def remove_constraint(table: dict, constraint_name: str) -> dict:
    """Remove a constraint from a table by name."""
    table["constraints"] = [c for c in table["constraints"] if c["name"] != constraint_name]
    return table


def add_index(table: dict, index: dict) -> dict:
    """Add an index to a table."""
    table["indexes"].append(index)
    return table


def remove_index(table: dict, index_name: str) -> dict:
    """Remove an index from a table by name."""
    table["indexes"] = [i for i in table["indexes"] if i["name"] != index_name]
    return table


def add_enum(schema: dict, enum: dict) -> dict:
    """Add an enum type to the schema."""
    schema["enums"].append(enum)
    return schema


def remove_enum(schema: dict, enum_name: str) -> dict:
    """Remove an enum type from the schema by name."""
    schema["enums"] = [e for e in schema["enums"] if e["name"] != enum_name]
    return schema


def find_enum(schema: dict, enum_name: str) -> dict | None:
    """Find an enum by name."""
    for e in schema["enums"]:
        if e["name"] == enum_name:
            return e
    return None


def generate_constraint_name(table_name: str, columns: list[str], constraint_type: str) -> str:
    """Auto-generate a constraint name.

    PK: {table}_pkey
    FK: {table}_{col}_fkey
    Unique: {table}_{col}_key
    Check: {table}_{col}_check
    """
    suffix_map = {
        "pk": "pkey",
        "fk": "fkey",
        "unique": "key",
        "check": "check",
    }
    suffix = suffix_map.get(constraint_type, constraint_type)

    if constraint_type == "pk":
        return f"{table_name}_pkey"

    col_part = "_".join(columns) if columns else "unnamed"
    name = f"{table_name}_{col_part}_{suffix}"

    # Truncate to 63 chars
    if len(name) > 63:
        name = name[:63]

    return name


def generate_index_name(table_name: str, columns: list[str]) -> str:
    """Auto-generate an index name: {table}_{col}_idx."""
    col_part = "_".join(columns) if columns else "unnamed"
    name = f"{table_name}_{col_part}_idx"

    if len(name) > 63:
        name = name[:63]

    return name
