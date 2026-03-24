# Skill: PostgreSQL Schema Validation — Safety, Naming, and Constraint Checks

## When to Use

Apply this skill when working on `pg_validator.py` or any validation logic in the builder. Covers identifier naming rules, reserved word detection, constraint conflict detection, FK target validation, circular reference detection, CHECK/DEFAULT expression safety, and type compatibility checks.

---

## Validation Categories

The validator returns a list of issues, each with a severity level:

```python
# Severity constants — module-level, not a class (matches project's functional style)
SEVERITY_ERROR = "error"      # Blocks export. Must fix.
SEVERITY_WARNING = "warning"  # Allows export. Flag to user.
SEVERITY_INFO = "info"        # Suggestion only.

def validate_schema(schema: dict) -> list[dict]:
    """Validate entire schema. Returns list of issues.

    Each issue: {
        severity: 'error' | 'warning' | 'info',
        table: str | None,
        column: str | None,
        constraint: str | None,
        message: str,
        code: str,  # machine-readable error code
    }
    """
```

---

## 1. Identifier Naming Validation

### Rules

```python
import re

MAX_IDENTIFIER_LENGTH = 63
VALID_IDENTIFIER_PATTERN = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')
INJECTION_CHARS = re.compile(r'[;\-]{2}|/\*|\*/|\\|\x00|"')

def validate_identifier(name: str, context: str) -> list[dict]:
    """Validate a table, column, constraint, or index name.

    Args:
        name: The identifier to validate.
        context: Human-readable context like "table name" or "column users.email".
    """
    issues = []

    if not name:
        issues.append({
            "severity": "error",
            "message": f"{context}: name cannot be empty",
            "code": "EMPTY_NAME",
        })
        return issues

    if len(name) > MAX_IDENTIFIER_LENGTH:
        issues.append({
            "severity": "error",
            "message": f"{context}: '{name}' exceeds 63 character limit ({len(name)} chars)",
            "code": "NAME_TOO_LONG",
        })

    if INJECTION_CHARS.search(name):
        issues.append({
            "severity": "error",
            "message": f"{context}: '{name}' contains dangerous characters (quotes, semicolons, comment markers)",
            "code": "INJECTION_RISK",
        })

    if not VALID_IDENTIFIER_PATTERN.match(name):
        issues.append({
            "severity": "warning",
            "message": f"{context}: '{name}' contains non-standard characters (will be quoted, but may cause issues)",
            "code": "NONSTANDARD_NAME",
        })

    if name.lower() in PG_RESERVED_WORDS:
        issues.append({
            "severity": "warning",
            "message": f"{context}: '{name}' is a PostgreSQL reserved word (will be quoted automatically)",
            "code": "RESERVED_WORD",
        })

    if name != name.lower() and '_' not in name:
        issues.append({
            "severity": "info",
            "message": f"{context}: '{name}' uses mixed case — PostgreSQL convention is snake_case",
            "code": "NAMING_CONVENTION",
        })

    return issues
```

### Reserved Words (Subset — Most Common)

```python
PG_RESERVED_WORDS: set[str] = {
    # SQL keywords that break unquoted identifiers
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
```

---

## 2. Duplicate Detection

```python
def validate_no_duplicates(schema: dict) -> list[dict]:
    """Check for duplicate table names, column names within a table,
    constraint names globally, and index names globally."""
    issues = []

    # Duplicate table names
    table_names = [t["name"].lower() for t in schema["tables"]]
    seen = set()
    for name in table_names:
        if name in seen:
            issues.append({
                "severity": "error",
                "message": f"Duplicate table name: '{name}'",
                "code": "DUPLICATE_TABLE",
            })
        seen.add(name)

    # Duplicate column names within each table
    for table in schema["tables"]:
        col_names = [c["name"].lower() for c in table["columns"]]
        col_seen = set()
        for name in col_names:
            if name in col_seen:
                issues.append({
                    "severity": "error",
                    "table": table["name"],
                    "message": f"Duplicate column name '{name}' in table '{table['name']}'",
                    "code": "DUPLICATE_COLUMN",
                })
            col_seen.add(name)

    # Duplicate constraint names (must be unique within schema)
    constraint_names = []
    for table in schema["tables"]:
        for c in table.get("constraints", []):
            constraint_names.append(c["name"].lower())

    c_seen = set()
    for name in constraint_names:
        if name in c_seen:
            issues.append({
                "severity": "error",
                "message": f"Duplicate constraint name: '{name}'",
                "code": "DUPLICATE_CONSTRAINT",
            })
        c_seen.add(name)

    return issues
```

---

## 3. Foreign Key Validation

### FK Target Existence

```python
def validate_fk_targets(schema: dict) -> list[dict]:
    """Every FK must reference an existing table and column."""
    issues = []
    table_map = {t["name"]: t for t in schema["tables"]}

    for table in schema["tables"]:
        for constraint in table.get("constraints", []):
            if constraint["type"] != "fk":
                continue

            ref_table = constraint["refTable"]
            ref_cols = constraint["refColumns"]

            # Check target table exists
            if ref_table not in table_map:
                issues.append({
                    "severity": "error",
                    "table": table["name"],
                    "constraint": constraint["name"],
                    "message": f"FK '{constraint['name']}' references non-existent table '{ref_table}'",
                    "code": "FK_MISSING_TABLE",
                })
                continue

            # Check target columns exist
            target_col_names = {c["name"] for c in table_map[ref_table]["columns"]}
            for ref_col in ref_cols:
                if ref_col not in target_col_names:
                    issues.append({
                        "severity": "error",
                        "table": table["name"],
                        "constraint": constraint["name"],
                        "message": f"FK '{constraint['name']}' references non-existent column '{ref_table}.{ref_col}'",
                        "code": "FK_MISSING_COLUMN",
                    })

            # Check source columns exist in this table
            source_col_names = {c["name"] for c in table["columns"]}
            for src_col in constraint["columns"]:
                if src_col not in source_col_names:
                    issues.append({
                        "severity": "error",
                        "table": table["name"],
                        "constraint": constraint["name"],
                        "message": f"FK '{constraint['name']}' uses non-existent source column '{src_col}'",
                        "code": "FK_MISSING_SOURCE_COLUMN",
                    })

    return issues
```

### FK Type Compatibility

```python
def validate_fk_types(schema: dict) -> list[dict]:
    """FK column type must be compatible with referenced PK column type."""
    issues = []
    table_map = {t["name"]: t for t in schema["tables"]}

    COMPATIBLE_TYPES = {
        "smallint": {"smallint", "integer", "bigint"},
        "integer": {"integer", "bigint"},
        "bigint": {"bigint"},
        "text": {"text", "varchar"},
        "varchar": {"varchar", "text"},
        "uuid": {"uuid"},
        "boolean": {"boolean"},
    }

    for table in schema["tables"]:
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
                    compatible = COMPATIBLE_TYPES.get(src_type, {src_type})
                    if ref_type not in compatible:
                        issues.append({
                            "severity": "warning",
                            "table": table["name"],
                            "constraint": constraint["name"],
                            "message": f"FK type mismatch: '{table['name']}.{src_col}' ({src_type}) → '{constraint['refTable']}.{ref_col}' ({ref_type})",
                            "code": "FK_TYPE_MISMATCH",
                        })

    return issues
```

---

## 4. Circular Reference Detection

```python
def detect_circular_fks(schema: dict) -> list[dict]:
    """Detect circular FK dependency chains. Returns warnings (not errors —
    circular FKs are valid in PG via ALTER TABLE, but user should be aware)."""
    issues = []

    # Build adjacency list: table -> set of tables it references via FK
    deps: dict[str, set[str]] = {t["name"]: set() for t in schema["tables"]}
    for table in schema["tables"]:
        for c in table.get("constraints", []):
            if c["type"] == "fk" and c["refTable"] != table["name"]:
                deps[table["name"]].add(c["refTable"])

    # DFS cycle detection
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
                # Found cycle
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                cycles.append(cycle)

        path.pop()
        rec_stack.remove(node)

    for table_name in deps:
        if table_name not in visited:
            dfs(table_name, [])

    for cycle in cycles:
        chain = " → ".join(cycle)
        issues.append({
            "severity": "warning",
            "message": f"Circular FK dependency: {chain}. Will use ALTER TABLE ADD CONSTRAINT for deferred creation.",
            "code": "CIRCULAR_FK",
        })

    return issues
```

---

## 5. Constraint Conflict Detection

```python
def validate_constraint_conflicts(schema: dict) -> list[dict]:
    """Detect conflicting constraints on the same column."""
    issues = []

    for table in schema["tables"]:
        for col in table["columns"]:
            # Identity + DEFAULT conflict
            if col.get("identity") and col.get("defaultValue"):
                issues.append({
                    "severity": "error",
                    "table": table["name"],
                    "column": col["name"],
                    "message": f"Column '{col['name']}' has both IDENTITY and DEFAULT — these are mutually exclusive",
                    "code": "IDENTITY_DEFAULT_CONFLICT",
                })

            # NOT NULL + nullable conflict (shouldn't happen with good UI, but validate)
            if col.get("isPrimaryKey") and col.get("nullable", False):
                issues.append({
                    "severity": "error",
                    "table": table["name"],
                    "column": col["name"],
                    "message": f"Column '{col['name']}' is PRIMARY KEY but marked nullable — PKs cannot be NULL",
                    "code": "PK_NULLABLE_CONFLICT",
                })

        # Multiple PKs on same table
        pk_constraints = [c for c in table.get("constraints", []) if c["type"] == "pk"]
        if len(pk_constraints) > 1:
            issues.append({
                "severity": "error",
                "table": table["name"],
                "message": f"Table '{table['name']}' has {len(pk_constraints)} PRIMARY KEY constraints — only one allowed",
                "code": "MULTIPLE_PK",
            })

        # PK columns must exist
        for pk in pk_constraints:
            col_names = {c["name"] for c in table["columns"]}
            for pk_col in pk["columns"]:
                if pk_col not in col_names:
                    issues.append({
                        "severity": "error",
                        "table": table["name"],
                        "message": f"PK constraint references non-existent column '{pk_col}'",
                        "code": "PK_MISSING_COLUMN",
                    })

    return issues
```

---

## 6. CHECK Expression Safety

CHECK expressions are the highest injection risk. Validate strictly.

```python
import re

CHECK_BANNED_KEYWORDS = {
    "drop", "alter", "insert", "update", "delete", "execute",
    "copy", "create", "grant", "revoke", "truncate", "call",
}

CHECK_BANNED_PATTERNS = re.compile(
    r';\s*|--|\\/\*|\*\\/|\\\\|pg_|information_schema|pg_catalog'
)

MAX_CHECK_LENGTH = 500

def validate_check_expression(expression: str, table_name: str, constraint_name: str) -> list[dict]:
    """Validate a CHECK constraint expression for safety."""
    issues = []

    if not expression.strip():
        issues.append({
            "severity": "error",
            "table": table_name,
            "constraint": constraint_name,
            "message": "CHECK expression cannot be empty",
            "code": "EMPTY_CHECK",
        })
        return issues

    if len(expression) > MAX_CHECK_LENGTH:
        issues.append({
            "severity": "error",
            "table": table_name,
            "constraint": constraint_name,
            "message": f"CHECK expression exceeds {MAX_CHECK_LENGTH} character limit",
            "code": "CHECK_TOO_LONG",
        })

    if CHECK_BANNED_PATTERNS.search(expression.lower()):
        issues.append({
            "severity": "error",
            "table": table_name,
            "constraint": constraint_name,
            "message": "CHECK expression contains suspicious patterns (semicolons, comments, system catalogs)",
            "code": "CHECK_INJECTION_RISK",
        })

    # Check for banned SQL keywords
    words = re.findall(r'\b\w+\b', expression.lower())
    found_banned = [w for w in words if w in CHECK_BANNED_KEYWORDS]
    if found_banned:
        issues.append({
            "severity": "error",
            "table": table_name,
            "constraint": constraint_name,
            "message": f"CHECK expression contains banned keyword(s): {', '.join(found_banned)}",
            "code": "CHECK_BANNED_KEYWORD",
        })

    # Check balanced parentheses
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
            "severity": "error",
            "table": table_name,
            "constraint": constraint_name,
            "message": "CHECK expression has unbalanced parentheses",
            "code": "CHECK_UNBALANCED_PARENS",
        })

    return issues
```

---

## 7. DEFAULT Value Safety

```python
# Whitelisted function calls for DEFAULT values
DEFAULT_ALLOWED_FUNCTIONS = {
    "now()", "current_timestamp", "current_date", "current_time",
    "gen_random_uuid()", "true", "false", "null",
}

def validate_default_value(
    value: str, col_type: str, table_name: str, col_name: str,
) -> list[dict]:
    """Validate a DEFAULT value against column type and safety rules."""
    issues = []
    val_lower = value.strip().lower()

    # Check for injection patterns
    if re.search(r';\s*|--|\\/\*', value):
        issues.append({
            "severity": "error",
            "table": table_name,
            "column": col_name,
            "message": f"DEFAULT value contains suspicious characters",
            "code": "DEFAULT_INJECTION_RISK",
        })
        return issues

    # Check if it's a known safe function
    if val_lower in DEFAULT_ALLOWED_FUNCTIONS:
        return issues

    # Check if it's a numeric literal
    try:
        float(value)
        return issues
    except ValueError:
        pass

    # Check if it's a quoted string literal
    if value.startswith("'") and value.endswith("'"):
        inner = value[1:-1]
        if "'" in inner.replace("''", ""):  # allow escaped quotes
            issues.append({
                "severity": "error",
                "table": table_name,
                "column": col_name,
                "message": "DEFAULT string contains unescaped single quotes",
                "code": "DEFAULT_BAD_QUOTES",
            })
        return issues

    # Unknown expression — warn
    issues.append({
        "severity": "warning",
        "table": table_name,
        "column": col_name,
        "message": f"DEFAULT value '{value}' is not a recognized safe expression — verify manually",
        "code": "DEFAULT_UNKNOWN_EXPR",
    })

    return issues
```

---

## 8. Table-Level Validation

```python
def validate_table(table: dict) -> list[dict]:
    """Validate a single table definition."""
    issues = []

    # Table must have at least one column
    if not table.get("columns"):
        issues.append({
            "severity": "error",
            "table": table["name"],
            "message": f"Table '{table['name']}' has no columns",
            "code": "EMPTY_TABLE",
        })

    # Warn if no PK
    has_pk = any(c.get("isPrimaryKey") for c in table.get("columns", []))
    pk_constraints = [c for c in table.get("constraints", []) if c["type"] == "pk"]
    if not has_pk and not pk_constraints:
        issues.append({
            "severity": "warning",
            "table": table["name"],
            "message": f"Table '{table['name']}' has no PRIMARY KEY — this is valid but unusual",
            "code": "NO_PRIMARY_KEY",
        })

    # Unlogged table warning
    if table.get("tableType") == "unlogged":
        issues.append({
            "severity": "warning",
            "table": table["name"],
            "message": f"Table '{table['name']}' is UNLOGGED — data will be lost on crash and not replicated",
            "code": "UNLOGGED_WARNING",
        })

    return issues
```

---

## 9. Enum Validation

```python
def validate_enums(schema: dict) -> list[dict]:
    """Validate enum type definitions."""
    issues = []

    for enum in schema.get("enums", []):
        # Enum must have values
        if not enum.get("values"):
            issues.append({
                "severity": "error",
                "message": f"Enum '{enum['name']}' has no values",
                "code": "EMPTY_ENUM",
            })

        # Duplicate values
        vals = enum.get("values", [])
        if len(vals) != len(set(vals)):
            issues.append({
                "severity": "error",
                "message": f"Enum '{enum['name']}' has duplicate values",
                "code": "DUPLICATE_ENUM_VALUE",
            })

        # Validate enum values don't contain injection patterns
        for val in vals:
            if re.search(r"[;'\"]", val.replace("''", "")):
                issues.append({
                    "severity": "error",
                    "message": f"Enum value '{val}' in '{enum['name']}' contains dangerous characters",
                    "code": "ENUM_VALUE_INJECTION",
                })

    return issues
```

---

## Master Validation Runner

```python
def validate_schema(schema: dict) -> list[dict]:
    """Run all validations on a schema. Returns combined issue list."""
    issues = []

    # Identifier validation (all names)
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

    # Structural validations
    issues.extend(validate_no_duplicates(schema))
    issues.extend(validate_fk_targets(schema))
    issues.extend(validate_fk_types(schema))
    issues.extend(detect_circular_fks(schema))
    issues.extend(validate_constraint_conflicts(schema))
    issues.extend(validate_enums(schema))

    # Per-table validations
    for table in schema.get("tables", []):
        issues.extend(validate_table(table))

        # CHECK expression safety
        for c in table.get("constraints", []):
            if c["type"] == "check":
                issues.extend(validate_check_expression(
                    c.get("expression", ""), table["name"], c["name"],
                ))

        # DEFAULT value safety
        for col in table.get("columns", []):
            if col.get("defaultValue"):
                issues.extend(validate_default_value(
                    col["defaultValue"], col.get("type", ""), table["name"], col["name"],
                ))

    return issues
```

---

## Error Code Reference

| Code | Severity | Description |
|------|----------|-------------|
| `EMPTY_NAME` | error | Identifier is empty |
| `NAME_TOO_LONG` | error | Exceeds 63 char limit |
| `INJECTION_RISK` | error | Contains `;`, `--`, `/*`, `"`, or `\` |
| `NONSTANDARD_NAME` | warning | Contains non-alphanumeric characters |
| `RESERVED_WORD` | warning | PG reserved word (auto-quoted) |
| `NAMING_CONVENTION` | info | Not snake_case |
| `DUPLICATE_TABLE` | error | Two tables with same name |
| `DUPLICATE_COLUMN` | error | Two columns with same name in one table |
| `DUPLICATE_CONSTRAINT` | error | Two constraints with same name |
| `FK_MISSING_TABLE` | error | FK references non-existent table |
| `FK_MISSING_COLUMN` | error | FK references non-existent column |
| `FK_MISSING_SOURCE_COLUMN` | error | FK source column doesn't exist |
| `FK_TYPE_MISMATCH` | warning | FK and PK column types differ |
| `CIRCULAR_FK` | warning | Circular FK chain detected |
| `IDENTITY_DEFAULT_CONFLICT` | error | Column has both IDENTITY and DEFAULT |
| `PK_NULLABLE_CONFLICT` | error | PK column marked nullable |
| `MULTIPLE_PK` | error | Table has multiple PK constraints |
| `PK_MISSING_COLUMN` | error | PK references non-existent column |
| `EMPTY_TABLE` | error | Table has no columns |
| `NO_PRIMARY_KEY` | warning | Table has no PK |
| `UNLOGGED_WARNING` | warning | Data lost on crash |
| `EMPTY_CHECK` | error | CHECK expression is empty |
| `CHECK_TOO_LONG` | error | CHECK exceeds 500 chars |
| `CHECK_INJECTION_RISK` | error | Suspicious patterns in CHECK |
| `CHECK_BANNED_KEYWORD` | error | DDL keywords in CHECK |
| `CHECK_UNBALANCED_PARENS` | error | Mismatched parentheses |
| `DEFAULT_INJECTION_RISK` | error | Suspicious patterns in DEFAULT |
| `DEFAULT_BAD_QUOTES` | error | Unescaped quotes in DEFAULT |
| `DEFAULT_UNKNOWN_EXPR` | warning | Unrecognized DEFAULT expression |
| `EMPTY_ENUM` | error | Enum has no values |
| `DUPLICATE_ENUM_VALUE` | error | Enum has duplicate values |
| `ENUM_VALUE_INJECTION` | error | Dangerous characters in enum value |
