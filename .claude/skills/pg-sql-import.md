# Skill: PostgreSQL SQL Import — DDL Parsing and Schema Extraction

## When to Use

Apply this skill when working on `ddl_parser.py` or the SQL import feature in the builder. Covers parsing `.sql` files (pg_dump output, hand-written DDL, migration files) into the builder's schema state format. Handles CREATE TABLE, CREATE TYPE, CREATE INDEX, ALTER TABLE ADD CONSTRAINT, comments, quoted identifiers, and multi-statement files.

---

## Architecture

### Module: `ddl_parser.py`

Pure functions, no HTTP, no state. Takes a SQL string, returns a schema dict matching the builder state shape.

```python
def parse_ddl(sql: str) -> dict:
    """Parse a PostgreSQL DDL string into a builder-compatible schema dict.

    Args:
        sql: Full SQL text (may contain multiple statements, comments, etc.)

    Returns:
        {
            "tables": [...],      # list of table dicts (same shape as builder state)
            "enums": [...],       # list of enum dicts
            "warnings": [...],    # list of parse warnings (unsupported syntax, etc.)
        }
    """
```

### Parse Pipeline

```
Raw SQL string
  → strip_comments()          # remove -- and /* */ comments
  → split_statements()        # split by ; into individual statements
  → classify_statement()      # determine type: CREATE TABLE, CREATE TYPE, etc.
  → parse_<type>()            # type-specific parser
  → merge_alter_constraints() # fold ALTER TABLE ADD CONSTRAINT into parent table
  → build_schema_dict()       # assemble into builder state format
```

---

## Step 1: Comment Stripping

```python
import re


def strip_comments(sql: str) -> str:
    """Remove SQL comments while preserving string literals.

    Handles:
      -- single line comments
      /* multi-line comments */ (including nested)
    Does NOT strip inside single-quoted string literals.
    """
    result = []
    i = 0
    in_string = False

    while i < len(sql):
        # Track string literals (single quotes)
        if sql[i] == "'" and not in_string:
            in_string = True
            result.append(sql[i])
            i += 1
        elif sql[i] == "'" and in_string:
            # Handle escaped quotes ''
            if i + 1 < len(sql) and sql[i + 1] == "'":
                result.append("''")
                i += 2
            else:
                in_string = False
                result.append(sql[i])
                i += 1
        elif in_string:
            result.append(sql[i])
            i += 1
        # Single-line comment
        elif sql[i:i+2] == '--':
            while i < len(sql) and sql[i] != '\n':
                i += 1
        # Multi-line comment
        elif sql[i:i+2] == '/*':
            depth = 1
            i += 2
            while i < len(sql) and depth > 0:
                if sql[i:i+2] == '/*':
                    depth += 1
                    i += 2
                elif sql[i:i+2] == '*/':
                    depth -= 1
                    i += 2
                else:
                    i += 1
        else:
            result.append(sql[i])
            i += 1

    return ''.join(result)
```

---

## Step 2: Statement Splitting

```python
def split_statements(sql: str) -> list[str]:
    """Split SQL into individual statements by semicolons.

    Respects:
      - Single-quoted string literals (don't split inside 'hello; world')
      - Parenthesized blocks (don't split inside function bodies)
    Returns list of trimmed, non-empty statements WITHOUT trailing semicolons.
    """
    statements = []
    current = []
    paren_depth = 0
    in_string = False

    for char in sql:
        if char == "'" and not in_string:
            in_string = True
            current.append(char)
        elif char == "'" and in_string:
            in_string = False
            current.append(char)
        elif in_string:
            current.append(char)
        elif char == '(':
            paren_depth += 1
            current.append(char)
        elif char == ')':
            paren_depth -= 1
            current.append(char)
        elif char == ';' and paren_depth == 0:
            stmt = ''.join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
        else:
            current.append(char)

    # Handle trailing statement without semicolon
    remaining = ''.join(current).strip()
    if remaining:
        statements.append(remaining)

    return statements
```

---

## Step 3: Statement Classification

```python
def classify_statement(stmt: str) -> str | None:
    """Classify a SQL statement by its type.

    Returns: 'create_table', 'create_type', 'create_index', 'alter_table',
             'set', 'begin', 'commit', or None (unsupported/skipped).
    """
    normalized = ' '.join(stmt.split()).upper()

    if normalized.startswith('CREATE TABLE') or normalized.startswith('CREATE TEMP TABLE') \
       or normalized.startswith('CREATE UNLOGGED TABLE'):
        return 'create_table'
    if normalized.startswith('CREATE TYPE'):
        return 'create_type'
    if normalized.startswith('CREATE INDEX') or normalized.startswith('CREATE UNIQUE INDEX'):
        return 'create_index'
    if normalized.startswith('ALTER TABLE'):
        return 'alter_table'
    if normalized.startswith('SET '):
        return 'set'
    if normalized in ('BEGIN', 'COMMIT', 'ROLLBACK'):
        return 'transaction'

    return None  # Skip unsupported statements (INSERT, GRANT, etc.)
```

---

## Step 4: CREATE TABLE Parser

The most complex parser. Handles columns, inline constraints, and table-level constraints.

```python
def parse_create_table(stmt: str) -> dict:
    """Parse a CREATE TABLE statement into a table dict.

    Handles:
      - CREATE TABLE / CREATE TEMP TABLE / CREATE UNLOGGED TABLE
      - IF NOT EXISTS
      - Quoted and unquoted identifiers
      - Column definitions with types, NOT NULL, DEFAULT, PRIMARY KEY, UNIQUE, REFERENCES
      - Table-level constraints: PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK
      - GENERATED ALWAYS/BY DEFAULT AS IDENTITY

    Returns table dict matching builder state shape.
    """
    table = {
        "name": "",
        "tableType": "permanent",
        "columns": [],
        "constraints": [],
        "indexes": [],
        "comment": None,
        "ifNotExists": False,
    }

    # Extract table type
    upper = stmt.upper()
    if 'CREATE TEMP TABLE' in upper or 'CREATE TEMPORARY TABLE' in upper:
        table["tableType"] = "temp"
    elif 'CREATE UNLOGGED TABLE' in upper:
        table["tableType"] = "unlogged"

    # Extract IF NOT EXISTS
    if 'IF NOT EXISTS' in upper:
        table["ifNotExists"] = True

    # Extract table name (between TABLE [IF NOT EXISTS] and opening paren)
    table["name"] = _extract_table_name(stmt)

    # Extract body (between outermost parens)
    body = _extract_paren_body(stmt)
    if not body:
        return table

    # Split body into definitions (columns and constraints)
    definitions = _split_definitions(body)

    for defn in definitions:
        defn_stripped = defn.strip()
        defn_upper = defn_stripped.upper()

        # Table-level constraint?
        if _is_table_constraint(defn_upper):
            constraint = _parse_table_constraint(defn_stripped)
            if constraint:
                table["constraints"].append(constraint)
        else:
            # Column definition
            column = _parse_column_def(defn_stripped)
            if column:
                table["columns"].append(column)

    return table
```

### Identifier Extraction

```python
def _unquote_identifier(name: str) -> str:
    """Remove surrounding double quotes from a PostgreSQL identifier.

    '"users"' → 'users'
    'users' → 'users'
    """
    name = name.strip()
    if name.startswith('"') and name.endswith('"'):
        return name[1:-1]
    return name.lower()  # Unquoted identifiers are case-insensitive in PG


def _extract_table_name(stmt: str) -> str:
    """Extract table name from a CREATE TABLE statement.

    Handles: CREATE TABLE "users" (...
             CREATE TABLE IF NOT EXISTS public."users" (...
             CREATE TEMP TABLE session_data (...
    """
    # Remove CREATE [TEMP|UNLOGGED] TABLE [IF NOT EXISTS]
    pattern = re.compile(
        r'CREATE\s+(?:TEMP(?:ORARY)?\s+|UNLOGGED\s+)?TABLE\s+'
        r'(?:IF\s+NOT\s+EXISTS\s+)?'
        r'(?:(\w+|"[^"]+")\.)?'   # optional schema prefix
        r'(\w+|"[^"]+")',          # table name
        re.IGNORECASE,
    )
    match = pattern.search(stmt)
    if not match:
        return ""
    return _unquote_identifier(match.group(2))
```

### Column Definition Parser

```python
def _parse_column_def(defn: str) -> dict | None:
    """Parse a single column definition line.

    Handles:
      "id" BIGINT GENERATED ALWAYS AS IDENTITY
      "email" VARCHAR(320) NOT NULL
      "created_at" TIMESTAMPTZ NOT NULL DEFAULT NOW()
      "status" "user_status" NOT NULL DEFAULT 'active'
      name TEXT UNIQUE
    """
    tokens = _tokenize_column(defn)
    if len(tokens) < 2:
        return None

    col = {
        "name": _unquote_identifier(tokens[0]),
        "type": "",
        "identity": None,
        "nullable": True,  # default in PG
        "defaultValue": None,
        "isPrimaryKey": False,
        "isUnique": False,
        "checkExpression": None,
        "comment": None,
    }

    # Extract type (second token, may include params like VARCHAR(255))
    col["type"] = _extract_column_type(tokens[1:])

    # Scan remaining tokens for modifiers
    upper_defn = defn.upper()

    if 'NOT NULL' in upper_defn:
        col["nullable"] = False

    if 'GENERATED ALWAYS AS IDENTITY' in upper_defn:
        col["identity"] = "ALWAYS"
    elif 'GENERATED BY DEFAULT AS IDENTITY' in upper_defn:
        col["identity"] = "BY DEFAULT"

    if 'PRIMARY KEY' in upper_defn:
        col["isPrimaryKey"] = True
        col["nullable"] = False

    # Inline UNIQUE (not table-level)
    if re.search(r'\bUNIQUE\b', upper_defn):
        col["isUnique"] = True

    # DEFAULT value
    default_match = re.search(r'\bDEFAULT\s+(.+?)(?:\s+NOT\s+NULL|\s+NULL|\s+CHECK|\s+UNIQUE|\s+PRIMARY|\s+REFERENCES|$)',
                               defn, re.IGNORECASE)
    if default_match:
        col["defaultValue"] = default_match.group(1).strip()

    # Inline REFERENCES (FK shorthand)
    ref_match = re.search(
        r'REFERENCES\s+(?:"([^"]+)"|(\w+))\s*\(\s*(?:"([^"]+)"|(\w+))\s*\)',
        defn, re.IGNORECASE,
    )
    if ref_match:
        ref_table = ref_match.group(1) or ref_match.group(2)
        ref_col = ref_match.group(3) or ref_match.group(4)
        # Store as inline FK hint — merge into table constraints later
        col["_inline_fk"] = {"refTable": ref_table, "refColumn": ref_col}

    return col
```

---

## Step 5: CREATE TYPE Parser (Enums)

```python
def parse_create_type(stmt: str) -> dict | None:
    """Parse CREATE TYPE ... AS ENUM (...) statement.

    Returns: {"name": "user_status", "values": ["active", "inactive", "banned"]}
    """
    pattern = re.compile(
        r"CREATE\s+TYPE\s+(?:(\w+|\"[^\"]+\")\.)?(\w+|\"[^\"]+\")\s+AS\s+ENUM\s*\((.+)\)",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(stmt)
    if not match:
        return None

    name = _unquote_identifier(match.group(2))
    values_str = match.group(3)

    # Extract single-quoted values
    values = re.findall(r"'([^']*(?:''[^']*)*)'", values_str)
    # Unescape doubled quotes
    values = [v.replace("''", "'") for v in values]

    return {"name": name, "values": values}
```

---

## Step 6: CREATE INDEX Parser

```python
def parse_create_index(stmt: str) -> dict | None:
    """Parse CREATE [UNIQUE] INDEX ... ON ... [USING method] (...) statement.

    Returns: {
        "name": "users_email_idx",
        "table": "users",
        "columns": ["email"],
        "type": "btree",
        "unique": False,
    }
    """
    pattern = re.compile(
        r"CREATE\s+(UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        r"(?:(\w+|\"[^\"]+\")\s+)?"  # index name (optional in some contexts)
        r"ON\s+(?:(\w+|\"[^\"]+\")\.)?(\w+|\"[^\"]+\")\s*"  # table name
        r"(?:USING\s+(\w+)\s*)?"     # optional method
        r"\((.+?)\)",                  # column list
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(stmt)
    if not match:
        return None

    is_unique = match.group(1) is not None
    index_name = _unquote_identifier(match.group(2)) if match.group(2) else ""
    table_name = _unquote_identifier(match.group(4))
    method = (match.group(5) or "btree").lower()
    columns_str = match.group(6)

    # Parse column list (may include expressions, ASC/DESC)
    columns = [_unquote_identifier(c.strip().split()[0]) for c in columns_str.split(',')]

    return {
        "name": index_name,
        "table": table_name,
        "columns": columns,
        "type": method,
        "unique": is_unique,
    }
```

---

## Step 7: ALTER TABLE Parser

```python
def parse_alter_table(stmt: str) -> dict | None:
    """Parse ALTER TABLE ... ADD CONSTRAINT ... statement.

    Only handles ADD CONSTRAINT (the most common ALTER in DDL dumps).
    Returns: {"table": "users", "constraint": {...}}
    """
    # Extract table name
    table_match = re.search(
        r"ALTER\s+TABLE\s+(?:ONLY\s+)?(?:(\w+|\"[^\"]+\")\.)?(\w+|\"[^\"]+\")",
        stmt, re.IGNORECASE,
    )
    if not table_match:
        return None

    table_name = _unquote_identifier(table_match.group(2))

    # ADD CONSTRAINT
    constraint_match = re.search(
        r"ADD\s+CONSTRAINT\s+(\w+|\"[^\"]+\")\s+(.+)",
        stmt, re.IGNORECASE | re.DOTALL,
    )
    if not constraint_match:
        return None

    constraint_name = _unquote_identifier(constraint_match.group(1))
    constraint_body = constraint_match.group(2).strip()

    constraint = _parse_constraint_body(constraint_name, constraint_body)
    if constraint:
        return {"table": table_name, "constraint": constraint}

    return None


def _parse_constraint_body(name: str, body: str) -> dict | None:
    """Parse the body of a constraint definition (after CONSTRAINT name)."""
    upper = body.upper()

    # PRIMARY KEY
    if upper.startswith('PRIMARY KEY'):
        cols = _extract_paren_columns(body)
        return {"type": "pk", "columns": cols, "name": name}

    # FOREIGN KEY
    fk_match = re.search(
        r"FOREIGN\s+KEY\s*\((.+?)\)\s*REFERENCES\s+"
        r"(?:(\w+|\"[^\"]+\")\.)?(\w+|\"[^\"]+\")\s*\((.+?)\)",
        body, re.IGNORECASE,
    )
    if fk_match:
        src_cols = [_unquote_identifier(c.strip()) for c in fk_match.group(1).split(',')]
        ref_table = _unquote_identifier(fk_match.group(3))
        ref_cols = [_unquote_identifier(c.strip()) for c in fk_match.group(4).split(',')]

        on_delete = "NO ACTION"
        on_update = "NO ACTION"
        del_match = re.search(r"ON\s+DELETE\s+(CASCADE|SET\s+NULL|SET\s+DEFAULT|RESTRICT|NO\s+ACTION)",
                               body, re.IGNORECASE)
        if del_match:
            on_delete = del_match.group(1).upper().replace('  ', ' ')
        upd_match = re.search(r"ON\s+UPDATE\s+(CASCADE|SET\s+NULL|SET\s+DEFAULT|RESTRICT|NO\s+ACTION)",
                               body, re.IGNORECASE)
        if upd_match:
            on_update = upd_match.group(1).upper().replace('  ', ' ')

        return {
            "type": "fk",
            "columns": src_cols,
            "refTable": ref_table,
            "refColumns": ref_cols,
            "onDelete": on_delete,
            "onUpdate": on_update,
            "name": name,
        }

    # UNIQUE
    if upper.startswith('UNIQUE'):
        cols = _extract_paren_columns(body)
        return {"type": "unique", "columns": cols, "name": name}

    # CHECK
    check_match = re.search(r"CHECK\s*\((.+)\)", body, re.IGNORECASE | re.DOTALL)
    if check_match:
        return {"type": "check", "expression": check_match.group(1).strip(), "name": name}

    return None
```

---

## Step 8: Merge and Assemble

```python
def merge_alter_constraints(tables: list[dict], alter_results: list[dict]) -> list[dict]:
    """Fold ALTER TABLE ADD CONSTRAINT results into their parent tables."""
    table_map = {t["name"]: t for t in tables}

    for alter in alter_results:
        table_name = alter["table"]
        if table_name in table_map:
            table_map[table_name]["constraints"].append(alter["constraint"])

    return tables


def merge_indexes(tables: list[dict], indexes: list[dict]) -> list[dict]:
    """Fold CREATE INDEX results into their parent tables."""
    table_map = {t["name"]: t for t in tables}

    for idx in indexes:
        table_name = idx.pop("table", "")
        if table_name in table_map:
            table_map[table_name]["indexes"].append(idx)

    return tables


def merge_inline_fks(tables: list[dict]) -> list[dict]:
    """Convert inline column-level FK references to table-level constraints."""
    for table in tables:
        for col in table["columns"]:
            fk_hint = col.pop("_inline_fk", None)
            if fk_hint:
                constraint_name = f"{table['name']}_{col['name']}_fkey"
                table["constraints"].append({
                    "type": "fk",
                    "columns": [col["name"]],
                    "refTable": fk_hint["refTable"],
                    "refColumns": [fk_hint["refColumn"]],
                    "onDelete": "NO ACTION",
                    "onUpdate": "NO ACTION",
                    "name": constraint_name,
                })
    return tables
```

---

## Full Parse Pipeline

```python
def parse_ddl(sql: str) -> dict:
    """Full parse pipeline: SQL string → builder schema dict."""
    cleaned = strip_comments(sql)
    statements = split_statements(cleaned)

    tables = []
    enums = []
    indexes = []
    alters = []
    warnings = []

    for stmt in statements:
        stmt_type = classify_statement(stmt)

        if stmt_type == 'create_table':
            table = parse_create_table(stmt)
            if table and table["name"]:
                tables.append(table)
            else:
                warnings.append(f"Could not parse CREATE TABLE: {stmt[:80]}...")

        elif stmt_type == 'create_type':
            enum = parse_create_type(stmt)
            if enum:
                enums.append(enum)
            else:
                warnings.append(f"Could not parse CREATE TYPE: {stmt[:80]}...")

        elif stmt_type == 'create_index':
            idx = parse_create_index(stmt)
            if idx:
                indexes.append(idx)

        elif stmt_type == 'alter_table':
            alter = parse_alter_table(stmt)
            if alter:
                alters.append(alter)

        elif stmt_type in ('set', 'transaction', None):
            pass  # Skip SET, BEGIN, COMMIT, unsupported statements

    # Merge ALTER constraints and indexes into tables
    tables = merge_alter_constraints(tables, alters)
    tables = merge_indexes(tables, indexes)
    tables = merge_inline_fks(tables)

    return {
        "tables": tables,
        "enums": enums,
        "warnings": warnings,
    }
```

---

## pg_dump Compatibility

`pg_dump --schema-only` output has specific patterns:

```sql
-- pg_dump adds SET statements at the top
SET statement_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

-- Tables are created WITHOUT constraints
CREATE TABLE public.users (
    id bigint NOT NULL,
    email character varying(320) NOT NULL,
    role_id bigint
);

-- PKs and FKs are added via ALTER TABLE later
ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id);

-- Sequences for SERIAL columns
CREATE SEQUENCE public.users_id_seq ...;
ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);
```

The parser handles this because:
1. SET statements are classified and skipped
2. CREATE TABLE without constraints is parsed normally
3. ALTER TABLE ADD CONSTRAINT is parsed and merged back
4. Schema prefixes (`public.`) are stripped via `_extract_table_name()`
5. Sequence-based defaults (`nextval(...)`) are preserved as-is in `defaultValue`

### pg_dump Type Normalization

pg_dump uses verbose type names. Normalize them:

```python
PG_DUMP_TYPE_MAP: dict[str, str] = {
    "character varying": "varchar",
    "character": "char",
    "integer": "integer",
    "bigint": "bigint",
    "smallint": "smallint",
    "double precision": "double precision",
    "boolean": "boolean",
    "timestamp without time zone": "timestamp",
    "timestamp with time zone": "timestamptz",
    "time without time zone": "time",
    "time with time zone": "timetz",
}

def normalize_pg_type(raw_type: str) -> str:
    """Normalize pg_dump verbose type names to standard short forms."""
    lower = raw_type.lower().strip()
    # Check for parameterized types: "character varying(255)"
    base = re.match(r'([a-z ]+?)(?:\(|$)', lower)
    if base:
        base_type = base.group(1).strip()
        if base_type in PG_DUMP_TYPE_MAP:
            return lower.replace(base_type, PG_DUMP_TYPE_MAP[base_type])
    return lower
```

---

## API Endpoint

```python
# In builder_routes.py
@builder_bp.route('/import-sql', methods=['POST'])
def import_sql():
    """Parse uploaded .sql file into builder schema.

    Accepts: multipart file upload OR JSON body with {"sql": "..."}.
    Returns: {"schema": {...}, "warnings": [...]}
    """
    from ddl_parser import parse_ddl

    sql = ""
    if request.files.get("file"):
        raw = request.files["file"].read()
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                sql = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
    else:
        data = request.get_json(silent=True) or {}
        sql = data.get("sql", "")

    if not sql.strip():
        return jsonify({"error": "No SQL provided"}), 400

    result = parse_ddl(sql)
    return jsonify({
        "schema": {
            "name": "public",
            "tables": result["tables"],
            "enums": result["enums"],
        },
        "warnings": result["warnings"],
    })
```

---

## Limitations (Documented, Not Hidden)

The parser handles the **common 90%** of PostgreSQL DDL. These are NOT supported and generate warnings:

| Feature | Status | Reason |
|---------|--------|--------|
| `CREATE FUNCTION` / `CREATE TRIGGER` | Skipped | Out of scope for schema builder |
| `CREATE VIEW` / `CREATE MATERIALIZED VIEW` | Skipped | Views are not tables |
| `CREATE SCHEMA` | Skipped | Builder assumes `public` schema |
| Partitioned table syntax (`PARTITION BY`) | Skipped | Deferred to v2 |
| `GRANT` / `REVOKE` | Skipped | Permissions out of scope |
| `CREATE SEQUENCE` (standalone) | Skipped | Handled implicitly via IDENTITY/SERIAL |
| Complex CHECK expressions with subqueries | Parsed as string | No semantic validation of imported CHECKs |
| `INHERITS` / table inheritance | Skipped | Rarely used |
| `EXCLUDE` constraints | Skipped | Deferred to v2 |

When a statement is skipped, a warning is added to the result so the user knows what was not imported.
