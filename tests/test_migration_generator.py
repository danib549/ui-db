"""Tests for migration_generator.py"""
import pytest
from migration_generator import generate_migration_sql, generate_export_filename


def test_basic_migration():
    mapping = {
        "users.id": {"sourceTable": "src_users", "sourceColumn": "UserID", "transform": None},
        "users.email": {"sourceTable": "src_users", "sourceColumn": "Email", "transform": "LOWER"},
    }
    schema = {"tables": [{"name": "users", "columns": []}]}
    sql = generate_migration_sql(mapping, schema)
    assert "BEGIN;" in sql
    assert "COMMIT;" in sql
    assert 'INSERT INTO "users"' in sql
    assert 'FROM "src_users"' in sql
    assert 'LOWER("Email")' in sql


def test_cast_transform():
    mapping = {
        "t.col": {"sourceTable": "src", "sourceColumn": "x", "transform": "CAST_INT"},
    }
    sql = generate_migration_sql(mapping, {"tables": []})
    assert 'CAST("x" AS INTEGER)' in sql


def test_nullif_transform():
    mapping = {
        "t.col": {"sourceTable": "src", "sourceColumn": "x", "transform": "NULLIF_EMPTY"},
    }
    sql = generate_migration_sql(mapping, {"tables": []})
    assert "NULLIF(TRIM" in sql


def test_no_transform():
    mapping = {
        "t.col": {"sourceTable": "src", "sourceColumn": "x", "transform": None},
    }
    sql = generate_migration_sql(mapping, {"tables": []})
    assert '"x"' in sql


def test_export_filename():
    name = generate_export_filename("public", "ddl")
    assert name.startswith("public_ddl_")
    assert name.endswith(".sql")


def test_export_filename_json():
    name = generate_export_filename("my_schema", "schema")
    assert name.endswith(".json")


# ---- Issue 6: Multi-source migration ----

def test_multi_source_generates_separate_inserts():
    mapping = {
        "users.id": {"sourceTable": "src_users", "sourceColumn": "UserID", "transform": None},
        "users.email": {"sourceTable": "src_users", "sourceColumn": "Email", "transform": None},
        "users.phone": {"sourceTable": "src_phones", "sourceColumn": "Phone", "transform": None},
    }
    sql = generate_migration_sql(mapping, {"tables": []})
    assert sql.count("INSERT INTO") == 2
    assert 'FROM "src_users"' in sql
    assert 'FROM "src_phones"' in sql


def test_single_source_unchanged():
    mapping = {
        "users.id": {"sourceTable": "src_users", "sourceColumn": "UserID", "transform": None},
        "users.email": {"sourceTable": "src_users", "sourceColumn": "Email", "transform": None},
    }
    sql = generate_migration_sql(mapping, {"tables": []})
    assert sql.count("INSERT INTO") == 1
    assert 'FROM "src_users"' in sql
