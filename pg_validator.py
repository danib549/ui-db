"""PostgreSQL schema validator — naming, constraints, FK targets, safety checks."""

import re

# Severity constants
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

MAX_IDENTIFIER_LENGTH = 63
VALID_IDENTIFIER_PATTERN = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')
INJECTION_CHARS = re.compile(r'[;\-]{2}|/\*|\*/|\\|\x00|"')

PG_RESERVED_WORDS: set[str] = {
    "all", "and", "any", "array", "as", "asc", "between", "bigint",
    "bit", "boolean", "case", "cast", "char", "character", "check",
    "column", "constraint", "create", "cross", "current_date",
    "current_time", "current_timestamp", "current_user", "default",
    "delete", "desc", "distinct", "do", "drop", "else", "end",
    "except", "exists", "false", "fetch", "float", "for", "foreign",
    "from", "full", "grant", "group", "having", "in", "index",
    "inner", "insert", "integer", "intersect", "interval", "into",
    "is", "join", "key", "leading", "left", "like", "limit",
    "natural", "new", "not", "null", "numeric", "offset", "old",
    "on", "only", "or", "order", "outer", "overlaps", "placing",
    "primary", "real", "references", "returning", "right", "row",
    "select", "session_user", "similar", "smallint", "some", "table",
    "then", "time", "timestamp", "to", "trailing", "true", "union",
    "unique", "update", "user", "using", "values", "varchar",
    "when", "where", "window", "with",
}

CHECK_BANNED_KEYWORDS = {
    "drop", "alter", "insert", "update", "delete", "execute",
    "copy", "create", "grant", "revoke", "truncate", "call",
}

CHECK_BANNED_PATTERNS = re.compile(
    r';\s*|--|\\/\*|\*\\/|\\\\|pg_|information_schema|pg_catalog'
)

MAX_CHECK_LENGTH = 500

DEFAULT_ALLOWED_FUNCTIONS = {
    "now()", "current_timestamp", "current_date", "current_time",
    "gen_random_uuid()", "true", "false", "null",
}


def validate_identifier(name: str, context: str) -> list[dict]:
    """Validate a table, column, constraint, or index name."""
    issues: list[dict] = []

    if not name:
        issues.append({
            "severity": SEVERITY_ERROR,
            "message": f"{context}: name cannot be empty",
            "code": "EMPTY_NAME",
        })
        return issues

    if len(name) > MAX_IDENTIFIER_LENGTH:
        issues.append({
            "severity": SEVERITY_ERROR,
            "message": f"{context}: '{name}' exceeds 63 character limit ({len(name)} chars)",
            "code": "NAME_TOO_LONG",
        })

    if INJECTION_CHARS.search(name):
        issues.append({
            "severity": SEVERITY_ERROR,
            "message": f"{context}: '{name}' contains dangerous characters",
            "code": "INJECTION_RISK",
        })

    if not VALID_IDENTIFIER_PATTERN.match(name):
        issues.append({
            "severity": SEVERITY_WARNING,
            "message": f"{context}: '{name}' contains non-standard characters",
            "code": "NONSTANDARD_NAME",
        })

    if name.lower() in PG_RESERVED_WORDS:
        issues.append({
            "severity": SEVERITY_WARNING,
            "message": f"{context}: '{name}' is a PostgreSQL reserved word",
            "code": "RESERVED_WORD",
        })

    if name != name.lower() and '_' not in name:
        issues.append({
            "severity": SEVERITY_INFO,
            "message": f"{context}: '{name}' uses mixed case — PostgreSQL convention is snake_case",
            "code": "NAMING_CONVENTION",
        })

    return issues


def validate_no_duplicates(schema: dict) -> list[dict]:
    """Check for duplicate table names, column names, constraint names."""
    issues: list[dict] = []

    table_names = [t["name"].lower() for t in schema.get("tables", [])]
    seen: set[str] = set()
    for name in table_names:
        if name in seen:
            issues.append({
                "severity": SEVERITY_ERROR,
                "message": f"Duplicate table name: '{name}'",
                "code": "DUPLICATE_TABLE",
            })
        seen.add(name)

    for table in schema.get("tables", []):
        col_names = [c["name"].lower() for c in table.get("columns", [])]
        col_seen: set[str] = set()
        for name in col_names:
            if name in col_seen:
                issues.append({
                    "severity": SEVERITY_ERROR,
                    "table": table["name"],
                    "message": f"Duplicate column name '{name}' in table '{table['name']}'",
                    "code": "DUPLICATE_COLUMN",
                })
            col_seen.add(name)

    constraint_names: list[str] = []
    for table in schema.get("tables", []):
        for c in table.get("constraints", []):
            constraint_names.append(c["name"].lower())

    c_seen: set[str] = set()
    for name in constraint_names:
        if name in c_seen:
            issues.append({
                "severity": SEVERITY_ERROR,
                "message": f"Duplicate constraint name: '{name}'",
                "code": "DUPLICATE_CONSTRAINT",
            })
        c_seen.add(name)

    return issues


def validate_fk_targets(schema: dict) -> list[dict]:
    """Every FK must reference an existing table and column."""
    issues: list[dict] = []
    table_map = {t["name"]: t for t in schema.get("tables", [])}

    for table in schema.get("tables", []):
        for constraint in table.get("constraints", []):
            if constraint["type"] != "fk":
                continue

            ref_table = constraint["refTable"]
            ref_cols = constraint["refColumns"]

            if ref_table not in table_map:
                issues.append({
                    "severity": SEVERITY_ERROR,
                    "table": table["name"],
                    "constraint": constraint["name"],
                    "message": f"FK '{constraint['name']}' references non-existent table '{ref_table}'",
                    "code": "FK_MISSING_TABLE",
                })
                continue

            target_col_names = {c["name"] for c in table_map[ref_table]["columns"]}
            for ref_col in ref_cols:
                if ref_col not in target_col_names:
                    issues.append({
                        "severity": SEVERITY_ERROR,
                        "table": table["name"],
                        "constraint": constraint["name"],
                        "message": f"FK '{constraint['name']}' references non-existent column '{ref_table}.{ref_col}'",
                        "code": "FK_MISSING_COLUMN",
                    })

            source_col_names = {c["name"] for c in table["columns"]}
            for src_col in constraint["columns"]:
                if src_col not in source_col_names:
                    issues.append({
                        "severity": SEVERITY_ERROR,
                        "table": table["name"],
                        "constraint": constraint["name"],
                        "message": f"FK '{constraint['name']}' uses non-existent source column '{src_col}'",
                        "code": "FK_MISSING_SOURCE_COLUMN",
                    })

    return issues


def validate_fk_types(schema: dict) -> list[dict]:
    """FK column type must be compatible with referenced column type."""
    issues: list[dict] = []
    table_map = {t["name"]: t for t in schema.get("tables", [])}

    compatible_types = {
        "smallint": {"smallint", "integer", "bigint"},
        "integer": {"integer", "bigint", "serial"},
        "bigint": {"bigint", "bigserial"},
        "serial": {"integer", "bigint", "serial"},
        "bigserial": {"bigint", "bigserial"},
        "numeric": {"numeric", "decimal"},
        "decimal": {"numeric", "decimal"},
        "text": {"text", "varchar"},
        "varchar": {"varchar", "text"},
        "uuid": {"uuid"},
        "boolean": {"boolean"},
        "timestamp": {"timestamp", "timestamptz"},
        "timestamptz": {"timestamp", "timestamptz"},
    }

    for table in schema.get("tables", []):
        col_type_map = {c["name"]: c["type"].lower().split("(")[0] for c in table["columns"]}

        for constraint in table.get("constraints", []):
            if constraint["type"] != "fk":
                continue

            ref_table = table_map.get(constraint["refTable"])
            if not ref_table:
                continue

            ref_col_type_map = {c["name"]: c["type"].lower().split("(")[0] for c in ref_table["columns"]}

            for src_col, ref_col in zip(constraint["columns"], constraint["refColumns"]):
                src_type = col_type_map.get(src_col, "")
                ref_type = ref_col_type_map.get(ref_col, "")

                if src_type and ref_type and src_type != ref_type:
                    compat = compatible_types.get(src_type, {src_type})
                    if ref_type not in compat:
                        issues.append({
                            "severity": SEVERITY_WARNING,
                            "table": table["name"],
                            "constraint": constraint["name"],
                            "message": f"FK type mismatch: '{table['name']}.{src_col}' ({src_type}) → '{constraint['refTable']}.{ref_col}' ({ref_type})",
                            "code": "FK_TYPE_MISMATCH",
                        })

    return issues


def detect_circular_fks(schema: dict) -> list[dict]:
    """Detect circular FK dependency chains."""
    issues: list[dict] = []

    deps: dict[str, set[str]] = {t["name"]: set() for t in schema.get("tables", [])}
    for table in schema.get("tables", []):
        for c in table.get("constraints", []):
            if c["type"] == "fk" and c["refTable"] != table["name"]:
                if c["refTable"] in deps:
                    deps[table["name"]].add(c["refTable"])

    visited: set[str] = set()
    rec_stack: set[str] = set()
    cycles: list[list[str]] = []

    def dfs(node: str, path: list[str]) -> None:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for neighbor in deps.get(node, set()):
            if neighbor not in visited:
                dfs(neighbor, path)
            elif neighbor in rec_stack:
                cycle_start = path.index(neighbor)
                cycles.append(path[cycle_start:] + [neighbor])

        path.pop()
        rec_stack.remove(node)

    for table_name in deps:
        if table_name not in visited:
            dfs(table_name, [])

    for cycle in cycles:
        chain = " → ".join(cycle)
        issues.append({
            "severity": SEVERITY_WARNING,
            "message": f"Circular FK dependency: {chain}",
            "code": "CIRCULAR_FK",
        })

    return issues


def validate_constraint_conflicts(schema: dict) -> list[dict]:
    """Detect conflicting constraints on the same column."""
    issues: list[dict] = []

    for table in schema.get("tables", []):
        for col in table.get("columns", []):
            if col.get("identity") and col.get("defaultValue"):
                issues.append({
                    "severity": SEVERITY_ERROR,
                    "table": table["name"],
                    "column": col["name"],
                    "message": f"Column '{col['name']}' has both IDENTITY and DEFAULT",
                    "code": "IDENTITY_DEFAULT_CONFLICT",
                })

            if col.get("isPrimaryKey") and col.get("nullable", False):
                issues.append({
                    "severity": SEVERITY_ERROR,
                    "table": table["name"],
                    "column": col["name"],
                    "message": f"Column '{col['name']}' is PRIMARY KEY but marked nullable",
                    "code": "PK_NULLABLE_CONFLICT",
                })

        pk_constraints = [c for c in table.get("constraints", []) if c["type"] == "pk"]
        if len(pk_constraints) > 1:
            issues.append({
                "severity": SEVERITY_ERROR,
                "table": table["name"],
                "message": f"Table '{table['name']}' has {len(pk_constraints)} PRIMARY KEY constraints",
                "code": "MULTIPLE_PK",
            })

        for pk in pk_constraints:
            col_names = {c["name"] for c in table.get("columns", [])}
            for pk_col in pk["columns"]:
                if pk_col not in col_names:
                    issues.append({
                        "severity": SEVERITY_ERROR,
                        "table": table["name"],
                        "message": f"PK constraint references non-existent column '{pk_col}'",
                        "code": "PK_MISSING_COLUMN",
                    })

    return issues


def validate_check_expression(
    expression: str, table_name: str, constraint_name: str,
) -> list[dict]:
    """Validate a CHECK constraint expression for safety."""
    issues: list[dict] = []

    if not expression.strip():
        issues.append({
            "severity": SEVERITY_ERROR,
            "table": table_name,
            "constraint": constraint_name,
            "message": "CHECK expression cannot be empty",
            "code": "EMPTY_CHECK",
        })
        return issues

    if len(expression) > MAX_CHECK_LENGTH:
        issues.append({
            "severity": SEVERITY_ERROR,
            "table": table_name,
            "constraint": constraint_name,
            "message": f"CHECK expression exceeds {MAX_CHECK_LENGTH} character limit",
            "code": "CHECK_TOO_LONG",
        })

    if CHECK_BANNED_PATTERNS.search(expression.lower()):
        issues.append({
            "severity": SEVERITY_ERROR,
            "table": table_name,
            "constraint": constraint_name,
            "message": "CHECK expression contains suspicious patterns",
            "code": "CHECK_INJECTION_RISK",
        })

    words = re.findall(r'\b\w+\b', expression.lower())
    found_banned = [w for w in words if w in CHECK_BANNED_KEYWORDS]
    if found_banned:
        issues.append({
            "severity": SEVERITY_ERROR,
            "table": table_name,
            "constraint": constraint_name,
            "message": f"CHECK expression contains banned keyword(s): {', '.join(found_banned)}",
            "code": "CHECK_BANNED_KEYWORD",
        })

    depth = 0
    for char in expression:
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        if depth < 0:
            break
    if depth != 0:
        issues.append({
            "severity": SEVERITY_ERROR,
            "table": table_name,
            "constraint": constraint_name,
            "message": "CHECK expression has unbalanced parentheses",
            "code": "CHECK_UNBALANCED_PARENS",
        })

    return issues


def validate_default_value(
    value: str, col_type: str, table_name: str, col_name: str,
) -> list[dict]:
    """Validate a DEFAULT value against column type and safety rules."""
    issues: list[dict] = []
    val_lower = value.strip().lower()

    if re.search(r';\s*|--|\\/\*', value):
        issues.append({
            "severity": SEVERITY_ERROR,
            "table": table_name,
            "column": col_name,
            "message": "DEFAULT value contains suspicious characters",
            "code": "DEFAULT_INJECTION_RISK",
        })
        return issues

    if val_lower in DEFAULT_ALLOWED_FUNCTIONS:
        return issues

    try:
        float(value)
        return issues
    except ValueError:
        pass

    if value.startswith("'") and value.endswith("'"):
        inner = value[1:-1]
        if "'" in inner.replace("''", ""):
            issues.append({
                "severity": SEVERITY_ERROR,
                "table": table_name,
                "column": col_name,
                "message": "DEFAULT string contains unescaped single quotes",
                "code": "DEFAULT_BAD_QUOTES",
            })
        return issues

    issues.append({
        "severity": SEVERITY_WARNING,
        "table": table_name,
        "column": col_name,
        "message": f"DEFAULT value '{value}' is not a recognized safe expression",
        "code": "DEFAULT_UNKNOWN_EXPR",
    })

    return issues


def validate_table(table: dict) -> list[dict]:
    """Validate a single table definition."""
    issues: list[dict] = []

    if not table.get("columns"):
        issues.append({
            "severity": SEVERITY_ERROR,
            "table": table["name"],
            "message": f"Table '{table['name']}' has no columns",
            "code": "EMPTY_TABLE",
        })

    has_pk = any(c.get("isPrimaryKey") for c in table.get("columns", []))
    pk_constraints = [c for c in table.get("constraints", []) if c["type"] == "pk"]
    if not has_pk and not pk_constraints:
        issues.append({
            "severity": SEVERITY_WARNING,
            "table": table["name"],
            "message": f"Table '{table['name']}' has no PRIMARY KEY",
            "code": "NO_PRIMARY_KEY",
        })

    if table.get("tableType") == "unlogged":
        issues.append({
            "severity": SEVERITY_WARNING,
            "table": table["name"],
            "message": f"Table '{table['name']}' is UNLOGGED — data will be lost on crash",
            "code": "UNLOGGED_WARNING",
        })

    return issues


def validate_enums(schema: dict) -> list[dict]:
    """Validate enum type definitions."""
    issues: list[dict] = []

    for enum in schema.get("enums", []):
        if not enum.get("values"):
            issues.append({
                "severity": SEVERITY_ERROR,
                "message": f"Enum '{enum['name']}' has no values",
                "code": "EMPTY_ENUM",
            })

        vals = enum.get("values", [])
        if len(vals) != len(set(vals)):
            issues.append({
                "severity": SEVERITY_ERROR,
                "message": f"Enum '{enum['name']}' has duplicate values",
                "code": "DUPLICATE_ENUM_VALUE",
            })

        for val in vals:
            if re.search(r"[;'\"]", val.replace("''", "")):
                issues.append({
                    "severity": SEVERITY_ERROR,
                    "message": f"Enum value '{val}' in '{enum['name']}' contains dangerous characters",
                    "code": "ENUM_VALUE_INJECTION",
                })

    return issues


def validate_schema(schema: dict) -> list[dict]:
    """Run all validations on a schema. Returns combined issue list."""
    issues: list[dict] = []

    for table in schema.get("tables", []):
        issues.extend(validate_identifier(table["name"], f"Table '{table['name']}'"))
        for col in table.get("columns", []):
            issues.extend(validate_identifier(col["name"], f"Column '{table['name']}.{col['name']}'"))
        for c in table.get("constraints", []):
            issues.extend(validate_identifier(c["name"], f"Constraint '{c['name']}'"))
        for idx in table.get("indexes", []):
            issues.extend(validate_identifier(idx["name"], f"Index '{idx['name']}'"))

    for enum in schema.get("enums", []):
        issues.extend(validate_identifier(enum["name"], f"Enum type '{enum['name']}'"))

    issues.extend(validate_no_duplicates(schema))
    issues.extend(validate_fk_targets(schema))
    issues.extend(validate_fk_types(schema))
    issues.extend(detect_circular_fks(schema))
    issues.extend(validate_constraint_conflicts(schema))
    issues.extend(validate_enums(schema))

    # Enum/table name collision
    table_names_lower = {t["name"].lower() for t in schema.get("tables", [])}
    enum_names_lower = {e["name"].lower() for e in schema.get("enums", [])}
    for name in table_names_lower & enum_names_lower:
        issues.append({
            "severity": SEVERITY_WARNING,
            "message": f"Enum type '{name}' has the same name as a table",
            "code": "ENUM_TABLE_NAME_COLLISION",
        })

    for table in schema.get("tables", []):
        issues.extend(validate_table(table))

        for c in table.get("constraints", []):
            if c["type"] == "check":
                issues.extend(validate_check_expression(
                    c.get("expression", ""), table["name"], c["name"],
                ))

        for col in table.get("columns", []):
            if col.get("defaultValue"):
                issues.extend(validate_default_value(
                    col["defaultValue"], col.get("type", ""), table["name"], col["name"],
                ))

    return issues
