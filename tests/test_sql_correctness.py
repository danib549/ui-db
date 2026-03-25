"""SQL correctness tests — end-to-end integration, structural validation, round-trips.

These tests verify the builder NEVER produces invalid PostgreSQL DDL.
"""
import re
import copy
import pytest

from schema_builder import create_column, create_table, create_empty_schema
from ddl_generator import generate_full_ddl, generate_create_table, generate_index, topological_sort_tables
from ddl_parser import parse_ddl, split_statements
from schema_differ import diff_schemas, generate_migration_ddl, order_operations
from pg_validator import validate_schema


# ---- Helpers ----

def _col(name, col_type="text", **kw):
    return create_column(name, col_type, **kw)


def _tbl(name, columns, constraints=None, indexes=None, **kw):
    return create_table(name, columns=columns, constraints=constraints or [],
                        indexes=indexes or [], **kw)


def _schema(tables, enums=None):
    return {"name": "public", "tables": tables, "enums": enums or []}


def _assert_valid_sql_structure(ddl):
    """Verify basic SQL structural integrity."""
    assert "BEGIN;" in ddl, "Missing BEGIN"
    assert "COMMIT;" in ddl, "Missing COMMIT"
    assert ddl.index("BEGIN;") < ddl.index("COMMIT;"), "BEGIN must come before COMMIT"
    assert ";;" not in ddl, "Double semicolons found"
    # Verify every statement (split by parser) is well-formed
    stmts = split_statements(ddl)
    sql_keywords = ("CREATE", "ALTER", "DROP", "COMMENT", "SET", "INSERT")
    for stmt in stmts:
        upper = stmt.strip().upper()
        if any(upper.startswith(kw) for kw in sql_keywords):
            # Statement should not be empty after the keyword
            assert len(stmt.strip()) > 5, f"Suspiciously short SQL statement: {stmt[:40]}"


def _assert_all_identifiers_quoted(ddl, names):
    """Verify all given names appear quoted in DDL."""
    for name in names:
        assert f'"{name}"' in ddl, f"Identifier '{name}' not quoted in DDL"


def _assert_order_in_ddl(ddl, first, second):
    """Assert first string appears before second in DDL."""
    pos1 = ddl.find(first)
    pos2 = ddl.find(second)
    assert pos1 >= 0, f"'{first}' not found in DDL"
    assert pos2 >= 0, f"'{second}' not found in DDL"
    assert pos1 < pos2, f"'{first}' must appear before '{second}'"


# ---- Realistic Schema Builders ----

def _build_5_table_schema():
    """Build a realistic 5-table schema: roles, users, products, orders, order_items."""
    return _schema(
        tables=[
            _tbl("roles", [
                _col("id", "bigint", nullable=False, identity="ALWAYS"),
                _col("name", "varchar(100)", nullable=False),
            ], constraints=[
                {"type": "pk", "columns": ["id"], "name": "roles_pkey"},
            ]),
            _tbl("users", [
                _col("id", "bigint", nullable=False, identity="ALWAYS"),
                _col("email", "varchar(320)", nullable=False),
                _col("role_id", "bigint", nullable=False),
                _col("status", "user_status", nullable=False, default_value="'active'"),
            ], constraints=[
                {"type": "pk", "columns": ["id"], "name": "users_pkey"},
                {"type": "fk", "columns": ["role_id"], "refTable": "roles", "refColumns": ["id"],
                 "onDelete": "CASCADE", "onUpdate": "NO ACTION", "name": "users_role_id_fkey"},
                {"type": "unique", "columns": ["email"], "name": "users_email_key"},
            ], indexes=[
                {"name": "users_email_idx", "columns": ["email"], "type": "btree", "unique": False},
            ]),
            _tbl("products", [
                _col("id", "bigint", nullable=False, identity="ALWAYS"),
                _col("name", "text", nullable=False),
                _col("price", "numeric(15,2)", nullable=False),
            ], constraints=[
                {"type": "pk", "columns": ["id"], "name": "products_pkey"},
                {"type": "check", "columns": [], "expression": '"price" > 0', "name": "products_price_check"},
            ]),
            _tbl("orders", [
                _col("id", "bigint", nullable=False, identity="ALWAYS"),
                _col("user_id", "bigint", nullable=False),
                _col("created_at", "timestamptz", nullable=False, default_value="NOW()"),
            ], constraints=[
                {"type": "pk", "columns": ["id"], "name": "orders_pkey"},
                {"type": "fk", "columns": ["user_id"], "refTable": "users", "refColumns": ["id"],
                 "onDelete": "CASCADE", "onUpdate": "NO ACTION", "name": "orders_user_id_fkey"},
            ]),
            _tbl("order_items", [
                _col("order_id", "bigint", nullable=False),
                _col("product_id", "bigint", nullable=False),
                _col("quantity", "integer", nullable=False, default_value="1"),
            ], constraints=[
                {"type": "pk", "columns": ["order_id", "product_id"], "name": "order_items_pkey"},
                {"type": "fk", "columns": ["order_id"], "refTable": "orders", "refColumns": ["id"],
                 "onDelete": "CASCADE", "onUpdate": "NO ACTION", "name": "order_items_order_fkey"},
                {"type": "fk", "columns": ["product_id"], "refTable": "products", "refColumns": ["id"],
                 "onDelete": "RESTRICT", "onUpdate": "NO ACTION", "name": "order_items_product_fkey"},
            ]),
        ],
        enums=[
            {"name": "user_status", "values": ["active", "inactive", "banned"]},
        ],
    )


# ============================================================
# P0 — Must Not Produce Broken SQL
# ============================================================

def test_realistic_schema_5_tables():
    schema = _build_5_table_schema()
    ddl = generate_full_ddl(schema)
    _assert_valid_sql_structure(ddl)
    _assert_all_identifiers_quoted(ddl, ["roles", "users", "products", "orders", "order_items"])
    assert 'CREATE TYPE' in ddl
    assert ddl.count("CREATE TABLE") == 5


def test_realistic_schema_10_tables():
    schema = _build_5_table_schema()
    for i in range(5):
        schema["tables"].append(_tbl(f"extra_{i}", [
            _col("id", "bigint", nullable=False, identity="ALWAYS"),
            _col("data", "jsonb"),
        ], constraints=[
            {"type": "pk", "columns": ["id"], "name": f"extra_{i}_pkey"},
        ]))
    ddl = generate_full_ddl(schema)
    _assert_valid_sql_structure(ddl)
    assert ddl.count("CREATE TABLE") == 10


def test_begin_commit_always_balanced():
    for n_tables in [0, 1, 5]:
        tables = [_tbl(f"t{i}", [_col("id", "integer")], constraints=[], indexes=[])
                  for i in range(n_tables)]
        ddl = generate_full_ddl(_schema(tables))
        assert ddl.count("BEGIN;") == 1
        assert ddl.count("COMMIT;") == 1


def test_every_statement_ends_with_semicolon():
    ddl = generate_full_ddl(_build_5_table_schema())
    stmts = split_statements(ddl)
    for stmt in stmts:
        stripped = stmt.strip()
        if stripped.startswith("--") or not stripped:
            continue


def test_no_duplicate_semicolons():
    ddl = generate_full_ddl(_build_5_table_schema())
    assert ";;" not in ddl


def test_all_identifiers_quoted():
    schema = _schema([
        _tbl("order", [_col("user", "integer"), _col("group", "text"), _col("select", "boolean")],
             constraints=[], indexes=[]),
    ])
    ddl = generate_full_ddl(schema)
    _assert_all_identifiers_quoted(ddl, ["order", "user", "group", "select"])


def test_enum_created_before_table_using_it():
    schema = _schema(
        tables=[_tbl("users", [_col("status", "user_status")], constraints=[], indexes=[])],
        enums=[{"name": "user_status", "values": ["a", "b"]}],
    )
    ddl = generate_full_ddl(schema)
    _assert_order_in_ddl(ddl, 'CREATE TYPE "user_status"', 'CREATE TABLE "users"')


def test_fk_target_created_before_referencing_table():
    schema = _schema([
        _tbl("orders", [_col("id", "integer"), _col("user_id", "integer")], constraints=[
            {"type": "pk", "columns": ["id"], "name": "orders_pkey"},
            {"type": "fk", "columns": ["user_id"], "refTable": "users", "refColumns": ["id"],
             "onDelete": "NO ACTION", "onUpdate": "NO ACTION", "name": "orders_user_fk"},
        ], indexes=[]),
        _tbl("users", [_col("id", "integer")], constraints=[
            {"type": "pk", "columns": ["id"], "name": "users_pkey"},
        ], indexes=[]),
    ])
    ddl = generate_full_ddl(schema)
    _assert_order_in_ddl(ddl, 'CREATE TABLE "users"', 'CREATE TABLE "orders"')


def test_all_fk_targets_exist_in_ddl():
    schema = _build_5_table_schema()
    ddl = generate_full_ddl(schema)
    parsed = parse_ddl(ddl)
    table_names = {t["name"] for t in parsed["tables"]}
    for table in parsed["tables"]:
        for c in table.get("constraints", []):
            if c["type"] == "fk":
                assert c["refTable"] in table_names, \
                    f"FK references '{c['refTable']}' which doesn't exist in DDL"


def test_migration_mixed_ops_valid_sql():
    original = _schema([
        _tbl("users", [
            _col("id", "bigint", nullable=False),
            _col("email", "varchar(255)", nullable=False),
            _col("old_col", "text"),
        ], constraints=[{"type": "pk", "columns": ["id"], "name": "users_pkey"}], indexes=[]),
    ])
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"] = [c for c in modified["tables"][0]["columns"] if c["name"] != "old_col"]
    modified["tables"][0]["columns"].append(_col("phone", "varchar(20)"))
    modified["tables"][0]["columns"][1]["type"] = "varchar(320)"
    ddl = generate_migration_ddl(original, modified)
    assert "DROP COLUMN" in ddl
    assert "ADD COLUMN" in ddl
    assert "ALTER COLUMN" in ddl


def test_round_trip_generate_parse_generate():
    schema = _schema(
        tables=[
            _tbl("roles", [_col("id", "bigint", nullable=False)],
                 constraints=[{"type": "pk", "columns": ["id"], "name": "roles_pkey"}], indexes=[]),
            _tbl("users", [
                _col("id", "bigint", nullable=False),
                _col("role_id", "bigint"),
            ], constraints=[
                {"type": "pk", "columns": ["id"], "name": "users_pkey"},
                {"type": "fk", "columns": ["role_id"], "refTable": "roles", "refColumns": ["id"],
                 "onDelete": "NO ACTION", "onUpdate": "NO ACTION", "name": "users_role_fkey"},
            ], indexes=[]),
        ],
        enums=[{"name": "status", "values": ["active", "inactive"]}],
    )
    ddl1 = generate_full_ddl(schema)
    parsed = parse_ddl(ddl1)
    assert len(parsed["tables"]) == len(schema["tables"])
    assert len(parsed["enums"]) == len(schema["enums"])
    assert {t["name"] for t in parsed["tables"]} == {t["name"] for t in schema["tables"]}


def test_round_trip_with_all_constraint_types():
    schema = _schema([_tbl("t", [
        _col("id", "bigint", nullable=False),
        _col("email", "varchar(320)", nullable=False),
        _col("ref_id", "bigint"),
        _col("age", "integer"),
    ], constraints=[
        {"type": "pk", "columns": ["id"], "name": "t_pkey"},
        {"type": "unique", "columns": ["email"], "name": "t_email_key"},
        {"type": "check", "columns": [], "expression": '"age" >= 0', "name": "t_age_check"},
    ], indexes=[])])
    ddl = generate_full_ddl(schema)
    parsed = parse_ddl(ddl)
    constraint_types = {c["type"] for c in parsed["tables"][0]["constraints"]}
    assert "pk" in constraint_types
    assert "unique" in constraint_types
    assert "check" in constraint_types


def test_round_trip_with_identity_columns():
    schema = _schema([_tbl("t", [
        _col("id", "bigint", nullable=False, identity="ALWAYS"),
        _col("seq", "integer", nullable=False, identity="BY DEFAULT"),
    ], constraints=[], indexes=[])])
    ddl = generate_full_ddl(schema)
    parsed = parse_ddl(ddl)
    cols = {c["name"]: c for c in parsed["tables"][0]["columns"]}
    assert cols["id"]["identity"] == "ALWAYS"
    assert cols["seq"]["identity"] == "BY DEFAULT"


def test_round_trip_with_indexes():
    schema = _schema([_tbl("t", [
        _col("id", "integer"),
        _col("data", "jsonb"),
    ], constraints=[], indexes=[
        {"name": "t_id_idx", "columns": ["id"], "type": "btree", "unique": False},
        {"name": "t_data_idx", "columns": ["data"], "type": "gin", "unique": False},
    ])])
    ddl = generate_full_ddl(schema)
    parsed = parse_ddl(ddl)
    idx_names = {i["name"] for i in parsed["tables"][0].get("indexes", [])}
    assert "t_id_idx" in idx_names
    assert "t_data_idx" in idx_names


def test_full_ddl_section_order():
    schema = _build_5_table_schema()
    schema["tables"][0]["columns"][0]["comment"] = "Primary key"
    ddl = generate_full_ddl(schema)
    sections = ["SET client_encoding", "BEGIN;", "ENUM TYPES", "TABLES", "INDEXES", "COMMIT;"]
    positions = []
    for s in sections:
        pos = ddl.find(s)
        if pos >= 0:
            positions.append(pos)
    # Verify monotonically increasing
    assert positions == sorted(positions), f"Section order violated: {sections}"


def test_validation_then_generation_pipeline():
    schema = _build_5_table_schema()
    issues = validate_schema(schema)
    errors = [i for i in issues if i["severity"] == "error"]
    assert len(errors) == 0, f"Unexpected validation errors: {errors}"
    ddl = generate_full_ddl(schema)
    assert "BEGIN;" in ddl


def test_invalid_schema_rejected_before_generation():
    schema = _schema([_tbl("orders", [
        _col("id", "integer"),
        _col("user_id", "integer"),
    ], constraints=[
        {"type": "fk", "columns": ["user_id"], "refTable": "nonexistent", "refColumns": ["id"],
         "onDelete": "NO ACTION", "onUpdate": "NO ACTION", "name": "bad_fk"},
    ], indexes=[])])
    issues = validate_schema(schema)
    assert any(i["code"] == "FK_MISSING_TABLE" for i in issues)


# ============================================================
# P1 — Every PG Feature
# ============================================================

def test_permanent_table_type():
    sql = generate_create_table(_tbl("t", [_col("id", "integer")]))
    assert sql.startswith("CREATE TABLE ")
    assert "TEMP" not in sql
    assert "UNLOGGED" not in sql


def test_temp_table_type():
    sql = generate_create_table(_tbl("t", [_col("id", "integer")], table_type="temp"))
    assert "CREATE TEMP TABLE" in sql


def test_unlogged_table_type():
    sql = generate_create_table(_tbl("t", [_col("id", "integer")], table_type="unlogged"))
    assert "CREATE UNLOGGED TABLE" in sql


def test_if_not_exists_option():
    sql = generate_create_table(_tbl("t", [_col("id", "integer")], if_not_exists=True))
    assert "IF NOT EXISTS" in sql


def test_composite_primary_key():
    tbl = _tbl("t", [_col("a", "integer"), _col("b", "integer")],
               constraints=[{"type": "pk", "columns": ["a", "b"], "name": "t_pkey"}])
    sql = generate_create_table(tbl)
    assert '"a"' in sql and '"b"' in sql
    assert "PRIMARY KEY" in sql


def test_multi_column_foreign_key():
    tbl = _tbl("t", [_col("a", "integer"), _col("b", "integer")],
               constraints=[{"type": "fk", "columns": ["a", "b"], "refTable": "ref",
                             "refColumns": ["x", "y"], "onDelete": "NO ACTION",
                             "onUpdate": "NO ACTION", "name": "t_fk"}])
    sql = generate_create_table(tbl)
    assert "FOREIGN KEY" in sql
    assert '"a", "b"' in sql or '"a","b"' in sql


def test_multi_column_unique():
    tbl = _tbl("t", [_col("a", "integer"), _col("b", "integer")],
               constraints=[{"type": "unique", "columns": ["a", "b"], "name": "t_ab_key"}])
    sql = generate_create_table(tbl)
    assert "UNIQUE" in sql


def test_self_referential_fk():
    tbl = _tbl("employees", [
        _col("id", "bigint", nullable=False),
        _col("manager_id", "bigint"),
    ], constraints=[
        {"type": "pk", "columns": ["id"], "name": "emp_pkey"},
        {"type": "fk", "columns": ["manager_id"], "refTable": "employees", "refColumns": ["id"],
         "onDelete": "SET NULL", "onUpdate": "NO ACTION", "name": "emp_mgr_fkey"},
    ])
    sql = generate_create_table(tbl)
    assert 'REFERENCES "employees"' in sql
    assert "ON DELETE SET NULL" in sql


def test_every_fk_on_delete_action():
    for action in ["CASCADE", "SET NULL", "SET DEFAULT", "RESTRICT"]:
        tbl = _tbl("t", [_col("id", "integer"), _col("ref_id", "integer")],
                   constraints=[{"type": "fk", "columns": ["ref_id"], "refTable": "r",
                                 "refColumns": ["id"], "onDelete": action,
                                 "onUpdate": "NO ACTION", "name": "fk"}])
        sql = generate_create_table(tbl)
        assert f"ON DELETE {action}" in sql


def test_every_fk_on_update_action():
    for action in ["CASCADE", "SET NULL", "SET DEFAULT", "RESTRICT"]:
        tbl = _tbl("t", [_col("id", "integer"), _col("ref_id", "integer")],
                   constraints=[{"type": "fk", "columns": ["ref_id"], "refTable": "r",
                                 "refColumns": ["id"], "onDelete": "NO ACTION",
                                 "onUpdate": action, "name": "fk"}])
        sql = generate_create_table(tbl)
        assert f"ON UPDATE {action}" in sql


def test_fk_no_action_omitted():
    tbl = _tbl("t", [_col("ref_id", "integer")],
               constraints=[{"type": "fk", "columns": ["ref_id"], "refTable": "r",
                             "refColumns": ["id"], "onDelete": "NO ACTION",
                             "onUpdate": "NO ACTION", "name": "fk"}])
    sql = generate_create_table(tbl)
    assert "ON DELETE" not in sql
    assert "ON UPDATE" not in sql


def test_identity_always_in_full_ddl():
    schema = _schema([_tbl("t", [
        _col("id", "bigint", nullable=False, identity="ALWAYS"),
    ], constraints=[], indexes=[])])
    ddl = generate_full_ddl(schema)
    assert "GENERATED ALWAYS AS IDENTITY" in ddl


def test_identity_by_default_in_full_ddl():
    schema = _schema([_tbl("t", [
        _col("id", "bigint", nullable=False, identity="BY DEFAULT"),
    ], constraints=[], indexes=[])])
    ddl = generate_full_ddl(schema)
    assert "GENERATED BY DEFAULT AS IDENTITY" in ddl


def test_check_constraint_in_full_table():
    tbl = _tbl("t", [_col("age", "integer")],
               constraints=[{"type": "check", "columns": [], "expression": '"age" >= 0',
                             "name": "t_age_check"}])
    sql = generate_create_table(tbl)
    assert 'CHECK ("age" >= 0)' in sql


def test_index_btree():
    sql = generate_index("t", {"name": "idx", "columns": ["a"], "type": "btree", "unique": False})
    assert "USING" not in sql  # btree is default, no USING clause


def test_index_gin():
    sql = generate_index("t", {"name": "idx", "columns": ["data"], "type": "gin", "unique": False})
    assert "USING GIN" in sql


def test_index_gist():
    sql = generate_index("t", {"name": "idx", "columns": ["geo"], "type": "gist", "unique": False})
    assert "USING GIST" in sql


def test_index_hash():
    sql = generate_index("t", {"name": "idx", "columns": ["token"], "type": "hash", "unique": False})
    assert "USING HASH" in sql


def test_unique_index():
    sql = generate_index("t", {"name": "idx", "columns": ["email"], "type": "btree", "unique": True})
    assert "CREATE UNIQUE INDEX" in sql


def test_table_comment():
    tbl = _tbl("users", [_col("id", "integer")], comment="User accounts")
    sql = generate_create_table(tbl)
    assert "COMMENT ON TABLE" in sql
    assert "User accounts" in sql


def test_column_comment_in_full_ddl():
    schema = _schema([_tbl("t", [
        _col("email", "text", comment="Email address"),
    ], constraints=[], indexes=[])])
    ddl = generate_full_ddl(schema)
    assert "COMMENT ON COLUMN" in ddl
    assert "Email address" in ddl


def test_comment_with_single_quote_escaped():
    tbl = _tbl("t", [_col("id", "integer")], comment="It's a table")
    sql = generate_create_table(tbl)
    assert "It''s a table" in sql


# ============================================================
# P2 — Migration Correctness
# ============================================================

def _base():
    return _schema([_tbl("users", [
        _col("id", "bigint", nullable=False),
        _col("email", "varchar(255)", nullable=False),
        _col("age", "integer"),
    ], constraints=[{"type": "pk", "columns": ["id"], "name": "users_pkey"}], indexes=[])])


def test_migration_add_and_drop_column_same_table():
    original = _base()
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"] = [c for c in modified["tables"][0]["columns"] if c["name"] != "age"]
    modified["tables"][0]["columns"].append(_col("phone", "varchar(20)"))
    ops = diff_schemas(original, modified)
    types = [o["type"] for o in ops]
    assert "drop_column" in types
    assert "add_column" in types
    # drop_column (order 2) must come before add_column (order 8)
    drop_idx = next(i for i, o in enumerate(ops) if o["type"] == "drop_column")
    add_idx = next(i for i, o in enumerate(ops) if o["type"] == "add_column")
    assert drop_idx < add_idx


def test_migration_constraint_modification():
    original = _base()
    original["tables"][0]["constraints"].append(
        {"type": "fk", "columns": ["age"], "refTable": "ages", "refColumns": ["id"],
         "onDelete": "CASCADE", "onUpdate": "NO ACTION", "name": "users_age_fkey"})
    modified = copy.deepcopy(original)
    # Change onDelete from CASCADE to SET NULL
    for c in modified["tables"][0]["constraints"]:
        if c["name"] == "users_age_fkey":
            c["onDelete"] = "SET NULL"
    ops = diff_schemas(original, modified)
    drop_ops = [o for o in ops if o["type"] == "drop_constraint"]
    add_ops = [o for o in ops if o["type"] == "add_constraint"]
    assert len(drop_ops) >= 1
    assert len(add_ops) >= 1
    assert "SET NULL" in add_ops[0]["sql"]


def test_migration_type_change_with_using():
    original = _base()
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"][1]["type"] = "integer"  # varchar -> integer
    ops = diff_schemas(original, modified)
    alter = [o for o in ops if o["type"] == "alter_column_type"]
    assert len(alter) == 1
    assert "USING" in alter[0]["sql"]


def test_migration_type_change_without_using():
    original = _base()
    original["tables"][0]["columns"][2]["type"] = "integer"
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"][2]["type"] = "bigint"
    ops = diff_schemas(original, modified)
    alter = [o for o in ops if o["type"] == "alter_column_type"]
    assert len(alter) == 1
    assert "USING" not in alter[0]["sql"]


def test_migration_identity_swap():
    original = _base()
    original["tables"][0]["columns"][0]["identity"] = "ALWAYS"
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"][0]["identity"] = "BY DEFAULT"
    ops = diff_schemas(original, modified)
    identity_ops = [o for o in ops if "IDENTITY" in o.get("sql", "")]
    assert len(identity_ops) == 2  # DROP + ADD
    assert any("DROP IDENTITY" in o["sql"] for o in identity_ops)
    assert any("BY DEFAULT" in o["sql"] for o in identity_ops)


def test_migration_identity_add():
    original = _base()
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"][0]["identity"] = "ALWAYS"
    ops = diff_schemas(original, modified)
    identity_ops = [o for o in ops if "IDENTITY" in o.get("sql", "")]
    assert len(identity_ops) == 1
    assert "ADD GENERATED ALWAYS AS IDENTITY" in identity_ops[0]["sql"]


def test_migration_identity_drop():
    original = _base()
    original["tables"][0]["columns"][0]["identity"] = "ALWAYS"
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"][0]["identity"] = None
    ops = diff_schemas(original, modified)
    identity_ops = [o for o in ops if "IDENTITY" in o.get("sql", "")]
    assert len(identity_ops) == 1
    assert "DROP IDENTITY" in identity_ops[0]["sql"]


def test_migration_enum_value_outside_transaction():
    original = _base()
    original["enums"] = [{"name": "st", "values": ["a"]}]
    modified = copy.deepcopy(original)
    modified["enums"][0]["values"].append("b")
    ddl = generate_migration_ddl(original, modified)
    assert "ADD VALUE" in ddl
    if "BEGIN;" in ddl:
        assert ddl.index("ADD VALUE") < ddl.index("BEGIN;")


def test_migration_new_table_fk_ordering():
    original = _base()
    modified = copy.deepcopy(original)
    modified["tables"].append(_tbl("products", [_col("id", "integer")], constraints=[
        {"type": "pk", "columns": ["id"], "name": "products_pkey"},
    ]))
    modified["tables"].append(_tbl("orders", [_col("id", "integer"), _col("product_id", "integer")],
        constraints=[
            {"type": "pk", "columns": ["id"], "name": "orders_pkey"},
            {"type": "fk", "columns": ["product_id"], "refTable": "products", "refColumns": ["id"],
             "onDelete": "NO ACTION", "onUpdate": "NO ACTION", "name": "orders_product_fk"},
        ]))
    ddl = generate_migration_ddl(original, modified)
    assert ddl.index('"products"') < ddl.index('"orders"')


def test_migration_multiple_tables_modified():
    original = _schema([
        _tbl("a", [_col("id", "integer"), _col("x", "text")], constraints=[], indexes=[]),
        _tbl("b", [_col("id", "integer"), _col("y", "text")], constraints=[], indexes=[]),
        _tbl("c", [_col("id", "integer"), _col("z", "text")], constraints=[], indexes=[]),
    ])
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"].append(_col("new_a", "integer"))
    modified["tables"][1]["columns"].append(_col("new_b", "integer"))
    modified["tables"][2]["columns"].append(_col("new_c", "integer"))
    ddl = generate_migration_ddl(original, modified)
    assert ddl.count("ADD COLUMN") == 3


def test_migration_drop_constraint_before_column():
    ops = [
        {"type": "drop_column", "sql": "x"},
        {"type": "drop_constraint", "sql": "y"},
        {"type": "add_column", "sql": "z"},
    ]
    ordered = order_operations(ops)
    types = [o["type"] for o in ordered]
    assert types.index("drop_constraint") < types.index("drop_column")
    assert types.index("drop_column") < types.index("add_column")


def test_migration_nullable_change():
    original = _base()
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"][2]["nullable"] = False  # age: nullable -> not null
    ops = diff_schemas(original, modified)
    null_ops = [o for o in ops if o["type"] == "alter_column_nullable"]
    assert len(null_ops) == 1
    assert "SET NOT NULL" in null_ops[0]["sql"]


def test_migration_default_add_drop_change():
    # Add default
    original = _base()
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"][2]["defaultValue"] = "0"
    ops = diff_schemas(original, modified)
    assert any("SET DEFAULT" in o["sql"] for o in ops)

    # Drop default
    original2 = copy.deepcopy(modified)
    modified2 = copy.deepcopy(original2)
    modified2["tables"][0]["columns"][2]["defaultValue"] = None
    ops2 = diff_schemas(original2, modified2)
    assert any("DROP DEFAULT" in o["sql"] for o in ops2)


# ============================================================
# P3 — Edge Cases
# ============================================================

def test_empty_schema():
    ddl = generate_full_ddl(_schema([]))
    assert "BEGIN;" in ddl
    assert "COMMIT;" in ddl
    assert "CREATE TABLE" not in ddl


def test_schema_with_only_enums():
    schema = _schema([], enums=[
        {"name": "color", "values": ["red", "green", "blue"]},
        {"name": "size", "values": ["s", "m", "l"]},
    ])
    ddl = generate_full_ddl(schema)
    assert ddl.count("CREATE TYPE") == 2
    assert "CREATE TABLE" not in ddl


def test_single_table_no_constraints():
    schema = _schema([_tbl("t", [_col("x", "text")])])
    ddl = generate_full_ddl(schema)
    _assert_valid_sql_structure(ddl)
    assert "CONSTRAINT" not in ddl


def test_table_with_30_columns():
    cols = [_col(f"col_{i}", "text") for i in range(30)]
    schema = _schema([_tbl("wide", cols, constraints=[], indexes=[])])
    ddl = generate_full_ddl(schema)
    for i in range(30):
        assert f'"col_{i}"' in ddl


def test_identifier_at_63_char_limit():
    long_name = "a" * 63
    schema = _schema([_tbl(long_name, [_col("id", "integer")], constraints=[], indexes=[])])
    ddl = generate_full_ddl(schema)
    assert f'"{long_name}"' in ddl


def test_reserved_word_identifiers():
    schema = _schema([_tbl("order", [
        _col("user", "integer"), _col("group", "text"),
        _col("table", "boolean"), _col("select", "integer"),
    ], constraints=[], indexes=[])])
    ddl = generate_full_ddl(schema)
    for name in ["order", "user", "group", "table", "select"]:
        assert f'"{name}"' in ddl


def test_circular_fk_3_tables():
    schema = _schema([
        _tbl("a", [_col("id", "integer"), _col("b_id", "integer")], constraints=[
            {"type": "pk", "columns": ["id"], "name": "a_pkey"},
            {"type": "fk", "columns": ["b_id"], "refTable": "b", "refColumns": ["id"],
             "onDelete": "NO ACTION", "onUpdate": "NO ACTION", "name": "a_b_fkey"},
        ], indexes=[]),
        _tbl("b", [_col("id", "integer"), _col("c_id", "integer")], constraints=[
            {"type": "pk", "columns": ["id"], "name": "b_pkey"},
            {"type": "fk", "columns": ["c_id"], "refTable": "c", "refColumns": ["id"],
             "onDelete": "NO ACTION", "onUpdate": "NO ACTION", "name": "b_c_fkey"},
        ], indexes=[]),
        _tbl("c", [_col("id", "integer"), _col("a_id", "integer")], constraints=[
            {"type": "pk", "columns": ["id"], "name": "c_pkey"},
            {"type": "fk", "columns": ["a_id"], "refTable": "a", "refColumns": ["id"],
             "onDelete": "NO ACTION", "onUpdate": "NO ACTION", "name": "c_a_fkey"},
        ], indexes=[]),
    ])
    ddl = generate_full_ddl(schema)
    assert "DEFERRED CONSTRAINTS" in ddl
    assert "ALTER TABLE" in ddl
    assert ddl.count("CREATE TABLE") == 3


def test_deep_fk_chain_5_levels():
    tables = []
    for i, name in enumerate(["e", "d", "c", "b", "a"]):
        cols = [_col("id", "integer")]
        constraints = [{"type": "pk", "columns": ["id"], "name": f"{name}_pkey"}]
        if i > 0:
            prev = ["e", "d", "c", "b", "a"][i - 1]
            cols.append(_col(f"{prev}_id", "integer"))
            constraints.append({"type": "fk", "columns": [f"{prev}_id"], "refTable": prev,
                                "refColumns": ["id"], "onDelete": "NO ACTION",
                                "onUpdate": "NO ACTION", "name": f"{name}_{prev}_fkey"})
        tables.append(_tbl(name, cols, constraints=constraints, indexes=[]))
    schema = _schema(tables)
    ddl = generate_full_ddl(schema)
    # e must be created first (no deps), then d, c, b, a
    _assert_order_in_ddl(ddl, 'CREATE TABLE "e"', 'CREATE TABLE "d"')
    _assert_order_in_ddl(ddl, 'CREATE TABLE "d"', 'CREATE TABLE "c"')


def test_validator_empty_table():
    from pg_validator import validate_table
    issues = validate_table({"name": "t", "columns": [], "constraints": []})
    assert any(i["code"] == "EMPTY_TABLE" for i in issues)


def test_validator_identity_plus_default():
    from pg_validator import validate_constraint_conflicts
    schema = _schema([_tbl("t", [
        _col("id", "bigint", identity="ALWAYS", default_value="0"),
    ], constraints=[])])
    issues = validate_constraint_conflicts(schema)
    assert any(i["code"] == "IDENTITY_DEFAULT_CONFLICT" for i in issues)


def test_validator_nullable_pk():
    from pg_validator import validate_constraint_conflicts
    schema = _schema([_tbl("t", [
        _col("id", "bigint", nullable=True, is_primary_key=True),
    ], constraints=[])])
    issues = validate_constraint_conflicts(schema)
    assert any(i["code"] == "PK_NULLABLE_CONFLICT" for i in issues)
