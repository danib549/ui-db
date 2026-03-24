"""Tests for schema_differ.py"""
import pytest
import copy
from schema_differ import diff_schemas, generate_migration_ddl


def _base_schema():
    return {
        "name": "public",
        "tables": [{
            "name": "users",
            "tableType": "permanent",
            "columns": [
                {"name": "id", "type": "bigint", "nullable": False},
                {"name": "email", "type": "varchar(255)", "nullable": False},
            ],
            "constraints": [{"type": "pk", "columns": ["id"], "name": "users_pkey"}],
            "indexes": [],
        }],
        "enums": [],
    }


def test_no_changes():
    schema = _base_schema()
    ops = diff_schemas(schema, copy.deepcopy(schema))
    assert len(ops) == 0


def test_add_column():
    original = _base_schema()
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"].append({"name": "phone", "type": "varchar(20)", "nullable": True})
    ops = diff_schemas(original, modified)
    add_ops = [o for o in ops if o["type"] == "add_column"]
    assert len(add_ops) == 1
    assert "phone" in add_ops[0]["sql"]


def test_drop_column():
    original = _base_schema()
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"] = [c for c in modified["tables"][0]["columns"] if c["name"] != "email"]
    ops = diff_schemas(original, modified)
    drop_ops = [o for o in ops if o["type"] == "drop_column"]
    assert len(drop_ops) == 1


def test_alter_column_type():
    original = _base_schema()
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"][1]["type"] = "varchar(320)"
    ops = diff_schemas(original, modified)
    alter_ops = [o for o in ops if o["type"] == "alter_column_type"]
    assert len(alter_ops) == 1
    assert "varchar(320)" in alter_ops[0]["sql"]


def test_add_table():
    original = _base_schema()
    modified = copy.deepcopy(original)
    modified["tables"].append({
        "name": "roles",
        "tableType": "permanent",
        "columns": [{"name": "id", "type": "integer"}],
        "constraints": [],
        "indexes": [],
    })
    ops = diff_schemas(original, modified)
    add_ops = [o for o in ops if o["type"] == "add_table"]
    assert len(add_ops) == 1


def test_drop_table():
    original = _base_schema()
    modified = copy.deepcopy(original)
    modified["tables"] = []
    ops = diff_schemas(original, modified)
    drop_ops = [o for o in ops if o["type"] == "drop_table"]
    assert len(drop_ops) == 1


def test_add_constraint():
    original = _base_schema()
    modified = copy.deepcopy(original)
    modified["tables"][0]["constraints"].append(
        {"type": "unique", "columns": ["email"], "name": "users_email_key"}
    )
    ops = diff_schemas(original, modified)
    add_ops = [o for o in ops if o["type"] == "add_constraint"]
    assert len(add_ops) == 1


def test_add_enum():
    original = _base_schema()
    modified = copy.deepcopy(original)
    modified["enums"] = [{"name": "status", "values": ["active", "inactive"]}]
    ops = diff_schemas(original, modified)
    add_ops = [o for o in ops if o["type"] == "add_enum"]
    assert len(add_ops) == 1


def test_add_enum_value():
    original = _base_schema()
    original["enums"] = [{"name": "status", "values": ["active"]}]
    modified = copy.deepcopy(original)
    modified["enums"][0]["values"].append("inactive")
    ops = diff_schemas(original, modified)
    add_ops = [o for o in ops if o["type"] == "add_enum_value"]
    assert len(add_ops) == 1


def test_migration_ddl_output():
    original = _base_schema()
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"].append({"name": "phone", "type": "text", "nullable": True})
    ddl = generate_migration_ddl(original, modified)
    assert "BEGIN;" in ddl
    assert "COMMIT;" in ddl
    assert "ADD COLUMN" in ddl


def test_no_changes_message():
    schema = _base_schema()
    ddl = generate_migration_ddl(schema, copy.deepcopy(schema))
    assert "No changes detected" in ddl
