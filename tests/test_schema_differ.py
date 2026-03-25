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


# ---- Issue 1: Enum escaping in differ ----

def test_diff_add_enum_value_with_quote():
    original = _base_schema()
    original["enums"] = [{"name": "status", "values": ["active"]}]
    modified = copy.deepcopy(original)
    modified["enums"][0]["values"].append("it's complicated")
    ops = diff_schemas(original, modified)
    add_ops = [o for o in ops if o["type"] == "add_enum_value"]
    assert len(add_ops) == 1
    assert "it''s complicated" in add_ops[0]["sql"]


def test_diff_add_enum_with_quotes():
    original = _base_schema()
    modified = copy.deepcopy(original)
    modified["enums"] = [{"name": "x", "values": ["don't", "won't"]}]
    ops = diff_schemas(original, modified)
    add_ops = [o for o in ops if o["type"] == "add_enum"]
    assert len(add_ops) == 1
    assert "don''t" in add_ops[0]["sql"]


# ---- Issue 2: Transaction handling ----

def test_migration_enum_value_outside_transaction():
    original = _base_schema()
    original["enums"] = [{"name": "status", "values": ["active"]}]
    modified = copy.deepcopy(original)
    modified["enums"][0]["values"].append("inactive")
    ddl = generate_migration_ddl(original, modified)
    add_value_pos = ddl.find("ADD VALUE")
    begin_pos = ddl.find("BEGIN;")
    assert add_value_pos >= 0
    # ADD VALUE must come before BEGIN, or no BEGIN at all
    assert begin_pos == -1 or add_value_pos < begin_pos


def test_migration_enum_only_no_transaction():
    original = _base_schema()
    original["enums"] = [{"name": "status", "values": ["active"]}]
    modified = copy.deepcopy(original)
    modified["enums"][0]["values"].append("inactive")
    ddl = generate_migration_ddl(original, modified)
    # Only enum value adds — no transaction needed
    assert "ADD VALUE" in ddl
    assert "BEGIN;" not in ddl
    assert "COMMIT;" not in ddl


def test_migration_mixed_ops_correct_order():
    original = _base_schema()
    original["enums"] = [{"name": "status", "values": ["active"]}]
    modified = copy.deepcopy(original)
    modified["enums"][0]["values"].append("inactive")
    modified["tables"][0]["columns"].append({"name": "phone", "type": "text", "nullable": True})
    ddl = generate_migration_ddl(original, modified)
    assert "ADD VALUE" in ddl
    assert "BEGIN;" in ddl
    assert "COMMIT;" in ddl
    assert "ADD COLUMN" in ddl
    # ADD VALUE before BEGIN
    assert ddl.find("ADD VALUE") < ddl.find("BEGIN;")


# ---- Issue 5: USING clause ----

def test_type_change_adds_using_clause():
    original = _base_schema()
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"][1]["type"] = "integer"  # varchar -> integer
    ops = diff_schemas(original, modified)
    alter_ops = [o for o in ops if o["type"] == "alter_column_type"]
    assert len(alter_ops) == 1
    assert "USING" in alter_ops[0]["sql"]


def test_compatible_type_change_no_using():
    original = _base_schema()
    original["tables"][0]["columns"][0]["type"] = "integer"
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"][0]["type"] = "bigint"
    ops = diff_schemas(original, modified)
    alter_ops = [o for o in ops if o["type"] == "alter_column_type"]
    assert len(alter_ops) == 1
    assert "USING" not in alter_ops[0]["sql"]


def test_type_change_text_to_integer():
    original = _base_schema()
    original["tables"][0]["columns"][1]["type"] = "text"
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"][1]["type"] = "integer"
    ops = diff_schemas(original, modified)
    alter_ops = [o for o in ops if o["type"] == "alter_column_type"]
    assert "USING" in alter_ops[0]["sql"]
    assert "::integer" in alter_ops[0]["sql"]


# ---- Issue 8: Index modification ----

def test_diff_index_columns_changed():
    original = _base_schema()
    original["tables"][0]["indexes"] = [{"name": "idx", "columns": ["email"], "type": "btree", "unique": False}]
    modified = copy.deepcopy(original)
    modified["tables"][0]["indexes"][0]["columns"] = ["email", "id"]
    ops = diff_schemas(original, modified)
    drop_ops = [o for o in ops if o["type"] == "drop_index"]
    add_ops = [o for o in ops if o["type"] == "add_index"]
    assert len(drop_ops) == 1
    assert len(add_ops) == 1


def test_diff_index_type_changed():
    original = _base_schema()
    original["tables"][0]["indexes"] = [{"name": "idx", "columns": ["email"], "type": "btree", "unique": False}]
    modified = copy.deepcopy(original)
    modified["tables"][0]["indexes"][0]["type"] = "gin"
    ops = diff_schemas(original, modified)
    drop_ops = [o for o in ops if o["type"] == "drop_index"]
    add_ops = [o for o in ops if o["type"] == "add_index"]
    assert len(drop_ops) == 1
    assert len(add_ops) == 1


def test_diff_index_unchanged():
    original = _base_schema()
    original["tables"][0]["indexes"] = [{"name": "idx", "columns": ["email"], "type": "btree", "unique": False}]
    modified = copy.deepcopy(original)
    ops = diff_schemas(original, modified)
    idx_ops = [o for o in ops if "index" in o["type"]]
    assert len(idx_ops) == 0


# ---- Issue 9: Enum drop warning ----

def test_enum_drop_warns_if_dependent_columns():
    original = _base_schema()
    original["enums"] = [{"name": "status", "values": ["a", "b"]}]
    modified = copy.deepcopy(original)
    modified["enums"] = []
    modified["tables"][0]["columns"].append({"name": "status_col", "type": "status", "nullable": True})
    ops = diff_schemas(original, modified)
    warnings = [o for o in ops if o["type"] == "warning"]
    assert any("status" in w["sql"].lower() and "affects" in w["sql"].lower() for w in warnings)


# ---- Migration FK ordering for new tables ----

def test_migration_new_tables_fk_ordered():
    original = _base_schema()
    modified = copy.deepcopy(original)
    modified["tables"].append({
        "name": "orders",
        "tableType": "permanent",
        "columns": [{"name": "id", "type": "integer"}, {"name": "product_id", "type": "integer"}],
        "constraints": [{"type": "fk", "columns": ["product_id"], "refTable": "products",
                         "refColumns": ["id"], "onDelete": "NO ACTION", "onUpdate": "NO ACTION",
                         "name": "orders_product_fk"}],
        "indexes": [],
    })
    modified["tables"].append({
        "name": "products",
        "tableType": "permanent",
        "columns": [{"name": "id", "type": "integer"}],
        "constraints": [],
        "indexes": [],
    })
    ddl = generate_migration_ddl(original, modified)
    # products must be created before orders
    products_pos = ddl.find('"products"')
    orders_pos = ddl.find('"orders"')
    assert products_pos < orders_pos


# ---- Identity changes ----

def test_identity_added():
    original = _base_schema()
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"][0]["identity"] = "ALWAYS"
    ops = diff_schemas(original, modified)
    identity_ops = [o for o in ops if "IDENTITY" in o.get("sql", "")]
    assert len(identity_ops) == 1
    assert "ADD GENERATED ALWAYS AS IDENTITY" in identity_ops[0]["sql"]


def test_identity_dropped():
    original = _base_schema()
    original["tables"][0]["columns"][0]["identity"] = "ALWAYS"
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"][0]["identity"] = None
    ops = diff_schemas(original, modified)
    identity_ops = [o for o in ops if "IDENTITY" in o.get("sql", "")]
    assert len(identity_ops) == 1
    assert "DROP IDENTITY" in identity_ops[0]["sql"]


# ---- NOT NULL add column warning ----

def test_add_not_null_column_without_default_warns():
    original = _base_schema()
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"].append({
        "name": "required_field", "type": "text", "nullable": False,
    })
    ops = diff_schemas(original, modified)
    warnings = [o for o in ops if o["type"] == "warning"]
    assert any("NOT NULL" in w["sql"] and "required_field" in w["sql"] for w in warnings)


def test_add_not_null_column_with_default_no_warning():
    original = _base_schema()
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"].append({
        "name": "required_field", "type": "text", "nullable": False, "defaultValue": "'none'",
    })
    ops = diff_schemas(original, modified)
    warnings = [o for o in ops if o["type"] == "warning"]
    assert not any("required_field" in w.get("sql", "") for w in warnings)


# ---- ADD VALUE IF NOT EXISTS ----

def test_add_enum_value_uses_if_not_exists():
    original = _base_schema()
    original["enums"] = [{"name": "status", "values": ["active"]}]
    modified = copy.deepcopy(original)
    modified["enums"][0]["values"].append("inactive")
    ops = diff_schemas(original, modified)
    add_ops = [o for o in ops if o["type"] == "add_enum_value"]
    assert "IF NOT EXISTS" in add_ops[0]["sql"]


# ---- Constraint changes ----

def test_constraint_changed_fk_action():
    original = _base_schema()
    original["tables"][0]["constraints"].append(
        {"type": "fk", "columns": ["email"], "refTable": "emails", "refColumns": ["id"],
         "onDelete": "CASCADE", "onUpdate": "NO ACTION", "name": "users_email_fkey"})
    modified = copy.deepcopy(original)
    for c in modified["tables"][0]["constraints"]:
        if c["name"] == "users_email_fkey":
            c["onDelete"] = "SET NULL"
    ops = diff_schemas(original, modified)
    drop_c = [o for o in ops if o["type"] == "drop_constraint"]
    add_c = [o for o in ops if o["type"] == "add_constraint"]
    assert len(drop_c) >= 1
    assert len(add_c) >= 1
    assert "SET NULL" in add_c[0]["sql"]


def test_constraint_changed_check_expression():
    original = _base_schema()
    original["tables"][0]["constraints"].append(
        {"type": "check", "columns": [], "expression": '"id" > 0', "name": "check1"})
    modified = copy.deepcopy(original)
    for c in modified["tables"][0]["constraints"]:
        if c["name"] == "check1":
            c["expression"] = '"id" > 10'
    ops = diff_schemas(original, modified)
    drop_c = [o for o in ops if o["type"] == "drop_constraint"]
    add_c = [o for o in ops if o["type"] == "add_constraint"]
    assert len(drop_c) >= 1
    assert len(add_c) >= 1


def test_identity_swap_always_to_by_default():
    original = _base_schema()
    original["tables"][0]["columns"][0]["identity"] = "ALWAYS"
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"][0]["identity"] = "BY DEFAULT"
    ops = diff_schemas(original, modified)
    identity_ops = [o for o in ops if "IDENTITY" in o.get("sql", "")]
    assert len(identity_ops) == 2
    sqls = [o["sql"] for o in identity_ops]
    assert any("DROP IDENTITY" in s for s in sqls)
    assert any("BY DEFAULT" in s for s in sqls)


def test_nullable_to_not_null():
    original = _base_schema()
    original["tables"][0]["columns"][1]["nullable"] = True
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"][1]["nullable"] = False
    ops = diff_schemas(original, modified)
    null_ops = [o for o in ops if o["type"] == "alter_column_nullable"]
    assert len(null_ops) == 1
    assert "SET NOT NULL" in null_ops[0]["sql"]


def test_not_null_to_nullable():
    original = _base_schema()
    original["tables"][0]["columns"][1]["nullable"] = False
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"][1]["nullable"] = True
    ops = diff_schemas(original, modified)
    null_ops = [o for o in ops if o["type"] == "alter_column_nullable"]
    assert len(null_ops) == 1
    assert "DROP NOT NULL" in null_ops[0]["sql"]


def test_default_added():
    original = _base_schema()
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"][1]["defaultValue"] = "'default@test.com'"
    ops = diff_schemas(original, modified)
    assert any("SET DEFAULT" in o["sql"] for o in ops)


def test_default_removed():
    original = _base_schema()
    original["tables"][0]["columns"][1]["defaultValue"] = "'old@test.com'"
    modified = copy.deepcopy(original)
    modified["tables"][0]["columns"][1]["defaultValue"] = None
    ops = diff_schemas(original, modified)
    assert any("DROP DEFAULT" in o["sql"] for o in ops)
