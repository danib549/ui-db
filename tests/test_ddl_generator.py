"""Tests for ddl_generator.py"""
import pytest
from ddl_generator import (
    quote_identifier, generate_column_def, generate_constraint_def,
    generate_create_table, generate_full_ddl, topological_sort_tables,
    escape_enum_value,
)


def test_quote_identifier():
    assert quote_identifier("users") == '"users"'
    assert quote_identifier("order") == '"order"'


def test_quote_identifier_rejects_double_quote():
    with pytest.raises(ValueError):
        quote_identifier('bad"name')


def test_column_def_basic():
    col = {"name": "email", "type": "varchar(255)", "nullable": False}
    result = generate_column_def(col)
    assert '"email"' in result
    assert "NOT NULL" in result


def test_column_def_identity():
    col = {"name": "id", "type": "bigint", "nullable": False, "identity": "ALWAYS"}
    result = generate_column_def(col)
    assert "GENERATED ALWAYS AS IDENTITY" in result


def test_column_def_default():
    col = {"name": "created_at", "type": "timestamptz", "nullable": False, "defaultValue": "NOW()"}
    result = generate_column_def(col)
    assert "DEFAULT NOW()" in result


def test_create_table():
    table = {
        "name": "users",
        "tableType": "permanent",
        "columns": [
            {"name": "id", "type": "bigint", "nullable": False, "identity": "ALWAYS"},
        ],
        "constraints": [{"type": "pk", "columns": ["id"], "name": "users_pkey"}],
    }
    sql = generate_create_table(table)
    assert 'CREATE TABLE "users"' in sql
    assert '"id"' in sql
    assert 'PRIMARY KEY' in sql


def test_create_temp_table():
    table = {"name": "tmp", "tableType": "temp", "columns": [
        {"name": "x", "type": "int"},
    ], "constraints": []}
    sql = generate_create_table(table)
    assert "CREATE TEMP TABLE" in sql


def test_topological_sort_simple():
    tables = [
        {"name": "orders", "constraints": [
            {"type": "fk", "columns": ["user_id"], "refTable": "users", "refColumns": ["id"], "name": "fk"},
        ]},
        {"name": "users", "constraints": []},
    ]
    ordered, circular = topological_sort_tables(tables)
    names = [t["name"] for t in ordered]
    assert names.index("users") < names.index("orders")
    assert len(circular) == 0


def test_topological_sort_circular():
    tables = [
        {"name": "a", "constraints": [
            {"type": "fk", "columns": ["b_id"], "refTable": "b", "refColumns": ["id"], "name": "a_fk"},
        ]},
        {"name": "b", "constraints": [
            {"type": "fk", "columns": ["a_id"], "refTable": "a", "refColumns": ["id"], "name": "b_fk"},
        ]},
    ]
    ordered, circular = topological_sort_tables(tables)
    assert len(ordered) == 2
    assert len(circular) > 0


def test_full_ddl_structure():
    schema = {
        "name": "public",
        "tables": [{"name": "t", "tableType": "permanent", "columns": [
            {"name": "id", "type": "integer"},
        ], "constraints": [], "indexes": []}],
        "enums": [{"name": "status", "values": ["a", "b"]}],
    }
    ddl = generate_full_ddl(schema)
    assert "BEGIN;" in ddl
    assert "COMMIT;" in ddl
    assert "ENUM TYPES" in ddl
    assert 'CREATE TYPE "status"' in ddl
    assert 'CREATE TABLE "t"' in ddl


def test_full_ddl_quoted_identifiers():
    schema = {
        "name": "public",
        "tables": [{"name": "order", "tableType": "permanent", "columns": [
            {"name": "user", "type": "integer"},
        ], "constraints": [], "indexes": []}],
        "enums": [],
    }
    ddl = generate_full_ddl(schema)
    assert '"order"' in ddl
    assert '"user"' in ddl


# ---- Issue 1: Enum value escaping ----

def test_enum_value_with_single_quote():
    schema = {
        "name": "public", "tables": [],
        "enums": [{"name": "label", "values": ["don't", "won't"]}],
    }
    ddl = generate_full_ddl(schema)
    assert "'don''t'" in ddl
    assert "'won''t'" in ddl


def test_enum_value_with_multiple_quotes():
    schema = {
        "name": "public", "tables": [],
        "enums": [{"name": "x", "values": ["it's a 'test'"]}],
    }
    ddl = generate_full_ddl(schema)
    assert "'it''s a ''test'''" in ddl


def test_enum_value_empty_string():
    schema = {
        "name": "public", "tables": [],
        "enums": [{"name": "x", "values": [""]}],
    }
    ddl = generate_full_ddl(schema)
    assert "ENUM ('')" in ddl


def test_escape_enum_value_function():
    assert escape_enum_value("hello") == "hello"
    assert escape_enum_value("don't") == "don''t"
    assert escape_enum_value("''") == "''''"


# ---- Issue 3: CHECK expression safety ----

def test_check_expression_injection_blocked():
    constraint = {"type": "check", "expression": "1=1; DROP TABLE users", "name": "bad_check", "columns": []}
    with pytest.raises(ValueError, match="Unsafe CHECK"):
        generate_constraint_def(constraint)


def test_check_expression_valid_passes():
    constraint = {"type": "check", "expression": '"age" >= 0', "name": "age_check", "columns": []}
    result = generate_constraint_def(constraint)
    assert "CHECK" in result
    assert '"age" >= 0' in result


# ---- Issue 4: DEFAULT value safety ----

def test_default_injection_blocked():
    col = {"name": "x", "type": "text", "defaultValue": "1; DROP TABLE users"}
    with pytest.raises(ValueError, match="Unsafe DEFAULT"):
        generate_column_def(col)


def test_default_comment_injection_blocked():
    col = {"name": "x", "type": "text", "defaultValue": "'ok' -- drop"}
    with pytest.raises(ValueError, match="Unsafe DEFAULT"):
        generate_column_def(col)


def test_default_valid_passes():
    col = {"name": "x", "type": "timestamptz", "defaultValue": "NOW()"}
    result = generate_column_def(col)
    assert "DEFAULT NOW()" in result


# ---- FK action validation ----

def test_fk_valid_on_delete():
    constraint = {
        "type": "fk", "columns": ["user_id"], "refTable": "users", "refColumns": ["id"],
        "onDelete": "CASCADE", "onUpdate": "NO ACTION", "name": "fk_test",
    }
    result = generate_constraint_def(constraint)
    assert "ON DELETE CASCADE" in result


def test_fk_invalid_on_delete_blocked():
    constraint = {
        "type": "fk", "columns": ["user_id"], "refTable": "users", "refColumns": ["id"],
        "onDelete": "CASCADE; DROP TABLE users", "onUpdate": "NO ACTION", "name": "fk_test",
    }
    with pytest.raises(ValueError, match="Invalid ON DELETE"):
        generate_constraint_def(constraint)


def test_fk_invalid_on_update_blocked():
    constraint = {
        "type": "fk", "columns": ["user_id"], "refTable": "users", "refColumns": ["id"],
        "onDelete": "NO ACTION", "onUpdate": "INVALID", "name": "fk_test",
    }
    with pytest.raises(ValueError, match="Invalid ON UPDATE"):
        generate_constraint_def(constraint)


# ---- Index generation ----

from ddl_generator import generate_index


def test_generate_index_btree_no_using():
    sql = generate_index("t", {"name": "idx", "columns": ["a"], "type": "btree", "unique": False})
    assert "USING" not in sql
    assert 'CREATE INDEX "idx"' in sql


def test_generate_index_gin():
    sql = generate_index("t", {"name": "idx", "columns": ["data"], "type": "gin", "unique": False})
    assert "USING GIN" in sql


def test_generate_index_gist():
    sql = generate_index("t", {"name": "idx", "columns": ["geo"], "type": "gist", "unique": False})
    assert "USING GIST" in sql


def test_generate_index_hash():
    sql = generate_index("t", {"name": "idx", "columns": ["tok"], "type": "hash", "unique": False})
    assert "USING HASH" in sql


def test_generate_unique_index():
    sql = generate_index("t", {"name": "idx", "columns": ["email"], "type": "btree", "unique": True})
    assert "CREATE UNIQUE INDEX" in sql


def test_create_unlogged_table():
    table = {"name": "buf", "tableType": "unlogged", "columns": [
        {"name": "x", "type": "int"},
    ], "constraints": []}
    sql = generate_create_table(table)
    assert "CREATE UNLOGGED TABLE" in sql


def test_column_def_identity_by_default():
    col = {"name": "id", "type": "integer", "nullable": False, "identity": "BY DEFAULT"}
    result = generate_column_def(col)
    assert "GENERATED BY DEFAULT AS IDENTITY" in result


def test_full_ddl_with_column_comments():
    schema = {
        "name": "public",
        "tables": [{"name": "t", "tableType": "permanent", "columns": [
            {"name": "id", "type": "integer", "comment": "Primary key"},
        ], "constraints": [], "indexes": []}],
        "enums": [],
    }
    ddl = generate_full_ddl(schema)
    assert "COMMENT ON COLUMN" in ddl
    assert "Primary key" in ddl
