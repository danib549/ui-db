"""Tests for ddl_generator.py"""
import pytest
from ddl_generator import (
    quote_identifier, generate_column_def, generate_create_table,
    generate_full_ddl, topological_sort_tables,
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
