"""Tests for pg_validator.py"""
import pytest
from pg_validator import (
    validate_identifier, validate_schema, validate_check_expression,
    validate_default_value, validate_no_duplicates, detect_circular_fks,
)


def test_empty_name():
    issues = validate_identifier("", "test")
    assert any(i["code"] == "EMPTY_NAME" for i in issues)


def test_long_name():
    issues = validate_identifier("a" * 64, "test")
    assert any(i["code"] == "NAME_TOO_LONG" for i in issues)


def test_injection_chars():
    issues = validate_identifier('table"name', "test")
    assert any(i["code"] == "INJECTION_RISK" for i in issues)


def test_reserved_word():
    issues = validate_identifier("user", "test")
    assert any(i["code"] == "RESERVED_WORD" for i in issues)


def test_valid_name():
    issues = validate_identifier("users", "test")
    assert not any(i["severity"] == "error" for i in issues)


def test_check_empty():
    issues = validate_check_expression("", "t", "c")
    assert any(i["code"] == "EMPTY_CHECK" for i in issues)


def test_check_banned_keyword():
    issues = validate_check_expression("drop table users", "t", "c")
    assert any(i["code"] == "CHECK_BANNED_KEYWORD" for i in issues)


def test_check_unbalanced_parens():
    issues = validate_check_expression("(age > 0", "t", "c")
    assert any(i["code"] == "CHECK_UNBALANCED_PARENS" for i in issues)


def test_check_valid():
    issues = validate_check_expression('"age" >= 0', "t", "c")
    assert not any(i["severity"] == "error" for i in issues)


def test_default_safe_function():
    issues = validate_default_value("NOW()", "timestamptz", "t", "c")
    assert len(issues) == 0


def test_default_numeric():
    issues = validate_default_value("0", "integer", "t", "c")
    assert len(issues) == 0


def test_default_string():
    issues = validate_default_value("'pending'", "varchar", "t", "c")
    assert len(issues) == 0


def test_duplicate_tables():
    schema = {"tables": [
        {"name": "users", "columns": [], "constraints": []},
        {"name": "users", "columns": [], "constraints": []},
    ], "enums": []}
    issues = validate_no_duplicates(schema)
    assert any(i["code"] == "DUPLICATE_TABLE" for i in issues)


def test_circular_fks():
    schema = {"tables": [
        {"name": "a", "columns": [{"name": "id", "type": "int"}], "constraints": [
            {"type": "fk", "columns": ["id"], "refTable": "b", "refColumns": ["id"], "name": "a_fk"},
        ]},
        {"name": "b", "columns": [{"name": "id", "type": "int"}], "constraints": [
            {"type": "fk", "columns": ["id"], "refTable": "a", "refColumns": ["id"], "name": "b_fk"},
        ]},
    ], "enums": []}
    issues = detect_circular_fks(schema)
    assert any(i["code"] == "CIRCULAR_FK" for i in issues)


def test_full_valid_schema():
    schema = {
        "tables": [{
            "name": "users",
            "tableType": "permanent",
            "columns": [
                {"name": "id", "type": "bigint", "nullable": False, "identity": "ALWAYS", "isPrimaryKey": True},
                {"name": "email", "type": "varchar(320)", "nullable": False},
            ],
            "constraints": [{"type": "pk", "columns": ["id"], "name": "users_pkey"}],
            "indexes": [],
        }],
        "enums": [],
    }
    issues = validate_schema(schema)
    errors = [i for i in issues if i["severity"] == "error"]
    assert len(errors) == 0


# ---- Issue 10: Enum/table name collision ----

def test_enum_table_name_collision_warning():
    schema = {
        "tables": [{
            "name": "status",
            "tableType": "permanent",
            "columns": [{"name": "id", "type": "integer", "nullable": False, "isPrimaryKey": True}],
            "constraints": [{"type": "pk", "columns": ["id"], "name": "status_pkey"}],
            "indexes": [],
        }],
        "enums": [{"name": "status", "values": ["active", "inactive"]}],
    }
    issues = validate_schema(schema)
    assert any(i.get("code") == "ENUM_TABLE_NAME_COLLISION" for i in issues)


# ---- Issue 11: FK type compatibility ----

def test_serial_to_integer_compatible():
    from pg_validator import validate_fk_types
    schema = {
        "tables": [
            {"name": "a", "columns": [{"name": "id", "type": "serial"}], "constraints": []},
            {"name": "b", "columns": [{"name": "a_id", "type": "integer"}], "constraints": [
                {"type": "fk", "columns": ["a_id"], "refTable": "a", "refColumns": ["id"], "name": "b_fk"},
            ]},
        ],
        "enums": [],
    }
    issues = validate_fk_types(schema)
    assert not any(i["code"] == "FK_TYPE_MISMATCH" for i in issues)


def test_bigserial_to_bigint_compatible():
    from pg_validator import validate_fk_types
    schema = {
        "tables": [
            {"name": "a", "columns": [{"name": "id", "type": "bigserial"}], "constraints": []},
            {"name": "b", "columns": [{"name": "a_id", "type": "bigint"}], "constraints": [
                {"type": "fk", "columns": ["a_id"], "refTable": "a", "refColumns": ["id"], "name": "b_fk"},
            ]},
        ],
        "enums": [],
    }
    issues = validate_fk_types(schema)
    assert not any(i["code"] == "FK_TYPE_MISMATCH" for i in issues)


def test_timestamptz_to_timestamp_compatible():
    from pg_validator import validate_fk_types
    schema = {
        "tables": [
            {"name": "a", "columns": [{"name": "ts", "type": "timestamptz"}], "constraints": []},
            {"name": "b", "columns": [{"name": "ts", "type": "timestamp"}], "constraints": [
                {"type": "fk", "columns": ["ts"], "refTable": "a", "refColumns": ["ts"], "name": "b_fk"},
            ]},
        ],
        "enums": [],
    }
    issues = validate_fk_types(schema)
    assert not any(i["code"] == "FK_TYPE_MISMATCH" for i in issues)
