"""DDL parser — parses .sql files into builder schema format."""

import re


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


def parse_ddl(sql: str) -> dict:
    """Full parse pipeline: SQL string → builder schema dict."""
    cleaned = strip_comments(sql)
    statements = split_statements(cleaned)

    tables: list[dict] = []
    enums: list[dict] = []
    indexes: list[dict] = []
    alters: list[dict] = []
    warnings: list[str] = []

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
            pass

    tables = merge_alter_constraints(tables, alters)
    tables = merge_indexes(tables, indexes)
    tables = merge_inline_fks(tables)

    return {
        "tables": tables,
        "enums": enums,
        "warnings": warnings,
    }


def strip_comments(sql: str) -> str:
    """Remove SQL comments while preserving string literals."""
    result: list[str] = []
    i = 0
    in_string = False

    while i < len(sql):
        if sql[i] == "'" and not in_string:
            in_string = True
            result.append(sql[i])
            i += 1
        elif sql[i] == "'" and in_string:
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
        elif sql[i:i+2] == '--':
            while i < len(sql) and sql[i] != '\n':
                i += 1
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


def split_statements(sql: str) -> list[str]:
    """Split SQL into individual statements by semicolons."""
    statements: list[str] = []
    current: list[str] = []
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

    remaining = ''.join(current).strip()
    if remaining:
        statements.append(remaining)

    return statements


def classify_statement(stmt: str) -> str | None:
    """Classify a SQL statement by its type."""
    normalized = ' '.join(stmt.split()).upper()

    if normalized.startswith('CREATE TABLE') or normalized.startswith('CREATE TEMP TABLE') \
       or normalized.startswith('CREATE TEMPORARY TABLE') \
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

    return None


def normalize_pg_type(raw_type: str) -> str:
    """Normalize pg_dump verbose type names to standard short forms."""
    lower = raw_type.lower().strip()
    base = re.match(r'([a-z ]+?)(?:\(|$)', lower)
    if base:
        base_type = base.group(1).strip()
        if base_type in PG_DUMP_TYPE_MAP:
            return lower.replace(base_type, PG_DUMP_TYPE_MAP[base_type])
    return lower


def parse_create_table(stmt: str) -> dict:
    """Parse a CREATE TABLE statement into a table dict."""
    table: dict = {
        "name": "",
        "tableType": "permanent",
        "columns": [],
        "constraints": [],
        "indexes": [],
        "comment": None,
        "ifNotExists": False,
    }

    upper = stmt.upper()
    if 'CREATE TEMP TABLE' in upper or 'CREATE TEMPORARY TABLE' in upper:
        table["tableType"] = "temp"
    elif 'CREATE UNLOGGED TABLE' in upper:
        table["tableType"] = "unlogged"

    if 'IF NOT EXISTS' in upper:
        table["ifNotExists"] = True

    table["name"] = _extract_table_name(stmt)

    body = _extract_paren_body(stmt)
    if not body:
        return table

    definitions = _split_definitions(body)

    for defn in definitions:
        defn_stripped = defn.strip()
        if not defn_stripped:
            continue
        defn_upper = defn_stripped.upper()

        if _is_table_constraint(defn_upper):
            constraint = _parse_table_constraint(defn_stripped)
            if constraint:
                table["constraints"].append(constraint)
        else:
            column = _parse_column_def(defn_stripped)
            if column:
                table["columns"].append(column)

    return table


def parse_create_type(stmt: str) -> dict | None:
    """Parse CREATE TYPE ... AS ENUM (...) statement."""
    pattern = re.compile(
        r"CREATE\s+TYPE\s+(?:(\w+|\"[^\"]+\")\.)?(\w+|\"[^\"]+\")\s+AS\s+ENUM\s*\((.+)\)",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(stmt)
    if not match:
        return None

    name = _unquote_identifier(match.group(2))
    values_str = match.group(3)

    values = re.findall(r"'([^']*(?:''[^']*)*)'", values_str)
    values = [v.replace("''", "'") for v in values]

    return {"name": name, "values": values}


def parse_create_index(stmt: str) -> dict | None:
    """Parse CREATE [UNIQUE] INDEX statement."""
    pattern = re.compile(
        r"CREATE\s+(UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        r"(?:(\w+|\"[^\"]+\")\s+)?"
        r"ON\s+(?:(\w+|\"[^\"]+\")\.)?(\w+|\"[^\"]+\")\s*"
        r"(?:USING\s+(\w+)\s*)?"
        r"\((.+?)\)",
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

    columns = [_unquote_identifier(c.strip().split()[0]) for c in columns_str.split(',')]

    return {
        "name": index_name,
        "table": table_name,
        "columns": columns,
        "type": method,
        "unique": is_unique,
    }


def parse_alter_table(stmt: str) -> dict | None:
    """Parse ALTER TABLE ... ADD CONSTRAINT ... statement."""
    table_match = re.search(
        r"ALTER\s+TABLE\s+(?:ONLY\s+)?(?:(\w+|\"[^\"]+\")\.)?(\w+|\"[^\"]+\")",
        stmt, re.IGNORECASE,
    )
    if not table_match:
        return None

    table_name = _unquote_identifier(table_match.group(2))

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


# ---- Internal helpers ----

def _unquote_identifier(name: str) -> str:
    """Remove surrounding double quotes from a PostgreSQL identifier."""
    name = name.strip()
    if name.startswith('"') and name.endswith('"'):
        return name[1:-1]
    return name.lower()


def _extract_table_name(stmt: str) -> str:
    """Extract table name from a CREATE TABLE statement."""
    pattern = re.compile(
        r'CREATE\s+(?:TEMP(?:ORARY)?\s+|UNLOGGED\s+)?TABLE\s+'
        r'(?:IF\s+NOT\s+EXISTS\s+)?'
        r'(?:(\w+|"[^"]+")\.)?'
        r'(\w+|"[^"]+")',
        re.IGNORECASE,
    )
    match = pattern.search(stmt)
    if not match:
        return ""
    return _unquote_identifier(match.group(2))


def _extract_paren_body(stmt: str) -> str:
    """Extract content between the outermost parentheses."""
    depth = 0
    start = -1
    for i, char in enumerate(stmt):
        if char == '(':
            if depth == 0:
                start = i + 1
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0 and start >= 0:
                return stmt[start:i]
    return ""


def _split_definitions(body: str) -> list[str]:
    """Split column/constraint definitions by commas at depth 0."""
    definitions: list[str] = []
    current: list[str] = []
    depth = 0
    in_string = False

    for char in body:
        if char == "'" and not in_string:
            in_string = True
            current.append(char)
        elif char == "'" and in_string:
            in_string = False
            current.append(char)
        elif in_string:
            current.append(char)
        elif char == '(':
            depth += 1
            current.append(char)
        elif char == ')':
            depth -= 1
            current.append(char)
        elif char == ',' and depth == 0:
            definitions.append(''.join(current).strip())
            current = []
        else:
            current.append(char)

    remaining = ''.join(current).strip()
    if remaining:
        definitions.append(remaining)

    return definitions


def _is_table_constraint(defn_upper: str) -> bool:
    """Check if a definition line is a table-level constraint."""
    return defn_upper.startswith('CONSTRAINT ') or \
           defn_upper.startswith('PRIMARY KEY') or \
           defn_upper.startswith('FOREIGN KEY') or \
           defn_upper.startswith('UNIQUE') or \
           defn_upper.startswith('CHECK')


def _parse_table_constraint(defn: str) -> dict | None:
    """Parse a table-level constraint definition."""
    upper = defn.upper().strip()

    name = ""
    body = defn

    if upper.startswith('CONSTRAINT '):
        name_match = re.match(r'CONSTRAINT\s+(\w+|"[^"]+")\s+(.*)', defn, re.IGNORECASE | re.DOTALL)
        if name_match:
            name = _unquote_identifier(name_match.group(1))
            body = name_match.group(2).strip()

    return _parse_constraint_body(name, body)


def _parse_constraint_body(name: str, body: str) -> dict | None:
    """Parse the body of a constraint definition."""
    upper = body.upper().strip()

    if upper.startswith('PRIMARY KEY'):
        cols = _extract_paren_columns(body)
        return {"type": "pk", "columns": cols, "name": name or "unnamed_pk"}

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
        del_match = re.search(
            r"ON\s+DELETE\s+(CASCADE|SET\s+NULL|SET\s+DEFAULT|RESTRICT|NO\s+ACTION)",
            body, re.IGNORECASE,
        )
        if del_match:
            on_delete = ' '.join(del_match.group(1).upper().split())
        upd_match = re.search(
            r"ON\s+UPDATE\s+(CASCADE|SET\s+NULL|SET\s+DEFAULT|RESTRICT|NO\s+ACTION)",
            body, re.IGNORECASE,
        )
        if upd_match:
            on_update = ' '.join(upd_match.group(1).upper().split())

        return {
            "type": "fk",
            "columns": src_cols,
            "refTable": ref_table,
            "refColumns": ref_cols,
            "onDelete": on_delete,
            "onUpdate": on_update,
            "name": name or "unnamed_fk",
        }

    if upper.startswith('UNIQUE'):
        cols = _extract_paren_columns(body)
        return {"type": "unique", "columns": cols, "name": name or "unnamed_unique"}

    check_match = re.search(r"CHECK\s*\((.+)\)", body, re.IGNORECASE | re.DOTALL)
    if check_match:
        return {"type": "check", "expression": check_match.group(1).strip(), "name": name or "unnamed_check"}

    return None


def _extract_paren_columns(text: str) -> list[str]:
    """Extract column names from parenthesized column list."""
    match = re.search(r'\((.+?)\)', text)
    if not match:
        return []
    return [_unquote_identifier(c.strip()) for c in match.group(1).split(',')]


def _parse_column_def(defn: str) -> dict | None:
    """Parse a single column definition line."""
    tokens = defn.split()
    if len(tokens) < 2:
        return None

    col: dict = {
        "name": _unquote_identifier(tokens[0]),
        "type": "",
        "identity": None,
        "nullable": True,
        "defaultValue": None,
        "isPrimaryKey": False,
        "isUnique": False,
        "checkExpression": None,
        "comment": None,
    }

    col["type"] = _extract_column_type(defn, tokens)

    upper_defn = defn.upper()

    if 'NOT NULL' in upper_defn:
        col["nullable"] = False

    if 'GENERATED ALWAYS AS IDENTITY' in upper_defn:
        col["identity"] = "ALWAYS"
    elif 'GENERATED BY DEFAULT AS IDENTITY' in upper_defn:
        col["identity"] = "BY DEFAULT"

    if re.search(r'\bPRIMARY\s+KEY\b', upper_defn):
        col["isPrimaryKey"] = True
        col["nullable"] = False

    if re.search(r'\bUNIQUE\b', upper_defn):
        col["isUnique"] = True

    default_match = re.search(
        r'\bDEFAULT\s+(.+?)(?:\s+NOT\s+NULL|\s+NULL\b|\s+CHECK\b|\s+UNIQUE\b|\s+PRIMARY\b|\s+REFERENCES\b|\s+CONSTRAINT\b|$)',
        defn, re.IGNORECASE,
    )
    if default_match:
        col["defaultValue"] = default_match.group(1).strip()

    ref_match = re.search(
        r'REFERENCES\s+(?:"([^"]+)"|(\w+))\s*\(\s*(?:"([^"]+)"|(\w+))\s*\)',
        defn, re.IGNORECASE,
    )
    if ref_match:
        ref_table = ref_match.group(1) or ref_match.group(2)
        ref_col = ref_match.group(3) or ref_match.group(4)
        col["_inline_fk"] = {"refTable": ref_table, "refColumn": ref_col}

    return col


def _extract_column_type(defn: str, tokens: list[str]) -> str:
    """Extract column type from definition, handling parameterized types."""
    # Skip the column name (first token)
    name_token = tokens[0]
    rest = defn[len(name_token):].strip()

    # Match type with optional parameters: VARCHAR(255), NUMERIC(10,2), etc.
    type_match = re.match(
        r'(?:"[^"]+"|\w[\w\s]*?)(?:\([^)]*\))?',
        rest,
    )
    if not type_match:
        return tokens[1] if len(tokens) > 1 else "text"

    raw_type = type_match.group(0).strip()

    # Stop at known keywords
    for keyword in ('NOT', 'NULL', 'DEFAULT', 'PRIMARY', 'UNIQUE', 'CHECK',
                    'REFERENCES', 'CONSTRAINT', 'GENERATED', 'COLLATE'):
        idx = raw_type.upper().find(f' {keyword}')
        if idx > 0:
            raw_type = raw_type[:idx].strip()
            break

    return normalize_pg_type(raw_type)
