"""Integration tests for /api/builder/* routes.

These tests hit the Flask API endpoints through the test client,
verifying the full pipeline: HTTP request → route → backend → response.
This is what the UI actually calls when building schemas.
"""
import io
import json
import pytest

from app import app


@pytest.fixture
def client():
    """Flask test client."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---- Helpers ----

def _post_json(client, url, payload):
    """POST JSON to a route, return parsed response."""
    resp = client.post(url, json=payload)
    return resp.status_code, resp.get_json()


def _simple_schema(tables=None, enums=None):
    """Build a minimal schema dict like the UI sends."""
    return {
        "name": "public",
        "tables": tables or [],
        "enums": enums or [],
    }


def _simple_table(name, columns, constraints=None, indexes=None, **kw):
    """Build a table dict matching the UI's state shape."""
    return {
        "name": name,
        "tableType": kw.get("tableType", "permanent"),
        "columns": columns,
        "constraints": constraints or [],
        "indexes": indexes or [],
        "comment": kw.get("comment"),
        "ifNotExists": kw.get("ifNotExists", False),
    }


def _simple_col(name, col_type="text", nullable=True, identity=None,
                default_value=None, is_pk=False, is_unique=False,
                check_expression=None, comment=None):
    """Build a column dict matching the UI's state shape."""
    return {
        "name": name,
        "type": col_type,
        "identity": identity,
        "nullable": nullable,
        "defaultValue": default_value,
        "isPrimaryKey": is_pk,
        "isUnique": is_unique,
        "checkExpression": check_expression,
        "comment": comment,
    }


# ============================================================
# POST /api/builder/validate
# ============================================================

class TestValidateEndpoint:

    def test_valid_schema_returns_no_errors(self, client):
        schema = _simple_schema(tables=[
            _simple_table("users", [
                _simple_col("id", "bigint", nullable=False, identity="ALWAYS"),
                _simple_col("email", "varchar(320)", nullable=False),
            ], constraints=[
                {"type": "pk", "columns": ["id"], "name": "users_pkey"},
            ]),
        ])
        status, body = _post_json(client, "/api/builder/validate", {"schema": schema})
        assert status == 200
        errors = [i for i in body["issues"] if i["severity"] == "error"]
        assert errors == []

    def test_missing_schema_returns_400(self, client):
        status, body = _post_json(client, "/api/builder/validate", {})
        assert status == 400
        assert "error" in body

    def test_duplicate_table_names_flagged(self, client):
        schema = _simple_schema(tables=[
            _simple_table("users", [_simple_col("id", "bigint")]),
            _simple_table("users", [_simple_col("id", "bigint")]),
        ])
        status, body = _post_json(client, "/api/builder/validate", {"schema": schema})
        assert status == 200
        errors = [i for i in body["issues"] if i["severity"] == "error"]
        assert any("duplicate" in e["message"].lower() or "users" in e["message"] for e in errors)

    def test_fk_to_nonexistent_table_flagged(self, client):
        schema = _simple_schema(tables=[
            _simple_table("orders", [
                _simple_col("id", "bigint", nullable=False),
                _simple_col("user_id", "bigint"),
            ], constraints=[
                {"type": "pk", "columns": ["id"], "name": "orders_pkey"},
                {"type": "fk", "columns": ["user_id"], "refTable": "nonexistent",
                 "refColumns": ["id"], "onDelete": "CASCADE", "onUpdate": "NO ACTION",
                 "name": "orders_user_id_fkey"},
            ]),
        ])
        status, body = _post_json(client, "/api/builder/validate", {"schema": schema})
        assert status == 200
        errors = [i for i in body["issues"] if i["severity"] == "error"]
        assert any("nonexistent" in e["message"].lower() for e in errors)

    def test_reserved_word_table_name_warns(self, client):
        schema = _simple_schema(tables=[
            _simple_table("order", [_simple_col("id", "bigint")]),
        ])
        status, body = _post_json(client, "/api/builder/validate", {"schema": schema})
        assert status == 200
        warnings = [i for i in body["issues"] if i["severity"] == "warning"]
        assert any("order" in w["message"].lower() or "reserved" in w["message"].lower()
                    for w in warnings)

    def test_injection_in_table_name_flagged(self, client):
        schema = _simple_schema(tables=[
            _simple_table('users"--drop', [_simple_col("id", "bigint")]),
        ])
        status, body = _post_json(client, "/api/builder/validate", {"schema": schema})
        assert status == 200
        errors = [i for i in body["issues"] if i["severity"] == "error"]
        assert len(errors) > 0

    def test_empty_enum_values_flagged(self, client):
        schema = _simple_schema(
            tables=[],
            enums=[{"name": "empty_enum", "values": []}],
        )
        status, body = _post_json(client, "/api/builder/validate", {"schema": schema})
        assert status == 200
        errors = [i for i in body["issues"] if i["severity"] == "error"]
        assert any("empty_enum" in e["message"] or "value" in e["message"].lower()
                    for e in errors)


# ============================================================
# POST /api/builder/generate-ddl
# ============================================================

class TestGenerateDDLEndpoint:

    def test_simple_table_generates_valid_ddl(self, client):
        schema = _simple_schema(tables=[
            _simple_table("products", [
                _simple_col("id", "bigint", nullable=False, identity="ALWAYS"),
                _simple_col("name", "varchar(200)", nullable=False),
                _simple_col("price", "numeric(10,2)", nullable=False, default_value="0"),
            ], constraints=[
                {"type": "pk", "columns": ["id"], "name": "products_pkey"},
            ]),
        ])
        status, body = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert status == 200
        sql = body["sql"]
        assert "BEGIN;" in sql
        assert "COMMIT;" in sql
        assert '"products"' in sql
        assert '"id"' in sql
        assert '"name"' in sql
        assert '"price"' in sql
        assert "GENERATED ALWAYS AS IDENTITY" in sql
        assert "NOT NULL" in sql

    def test_missing_schema_returns_400(self, client):
        status, body = _post_json(client, "/api/builder/generate-ddl", {})
        assert status == 400

    def test_multi_table_with_fk_ordering(self, client):
        """Tables are ordered so FK targets come before referencing tables."""
        schema = _simple_schema(tables=[
            _simple_table("orders", [
                _simple_col("id", "bigint", nullable=False, identity="ALWAYS"),
                _simple_col("user_id", "bigint", nullable=False),
            ], constraints=[
                {"type": "pk", "columns": ["id"], "name": "orders_pkey"},
                {"type": "fk", "columns": ["user_id"], "refTable": "users",
                 "refColumns": ["id"], "onDelete": "CASCADE", "onUpdate": "NO ACTION",
                 "name": "orders_user_id_fkey"},
            ]),
            _simple_table("users", [
                _simple_col("id", "bigint", nullable=False, identity="ALWAYS"),
                _simple_col("email", "varchar(320)", nullable=False),
            ], constraints=[
                {"type": "pk", "columns": ["id"], "name": "users_pkey"},
            ]),
        ])
        status, body = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert status == 200
        sql = body["sql"]
        # users must appear before orders
        assert sql.index('"users"') < sql.index('"orders"')

    def test_enum_created_before_table(self, client):
        schema = _simple_schema(
            tables=[
                _simple_table("users", [
                    _simple_col("id", "bigint", nullable=False),
                    _simple_col("status", "user_status", nullable=False, default_value="'active'"),
                ], constraints=[
                    {"type": "pk", "columns": ["id"], "name": "users_pkey"},
                ]),
            ],
            enums=[{"name": "user_status", "values": ["active", "inactive", "banned"]}],
        )
        status, body = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert status == 200
        sql = body["sql"]
        assert sql.index("CREATE TYPE") < sql.index("CREATE TABLE")

    def test_all_identifiers_are_quoted(self, client):
        schema = _simple_schema(tables=[
            _simple_table("user", [
                _simple_col("order", "text"),
                _simple_col("group", "integer"),
            ]),
        ])
        status, body = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert status == 200
        sql = body["sql"]
        assert '"user"' in sql
        assert '"order"' in sql
        assert '"group"' in sql

    def test_indexes_in_ddl(self, client):
        schema = _simple_schema(tables=[
            _simple_table("users", [
                _simple_col("id", "bigint", nullable=False),
                _simple_col("email", "varchar(320)", nullable=False),
            ], constraints=[
                {"type": "pk", "columns": ["id"], "name": "users_pkey"},
            ], indexes=[
                {"name": "users_email_idx", "columns": ["email"], "type": "btree", "unique": False},
            ]),
        ])
        status, body = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert status == 200
        sql = body["sql"]
        assert "CREATE INDEX" in sql
        assert '"users_email_idx"' in sql

    def test_check_constraint_in_ddl(self, client):
        schema = _simple_schema(tables=[
            _simple_table("products", [
                _simple_col("id", "bigint", nullable=False),
                _simple_col("price", "numeric(10,2)", nullable=False),
            ], constraints=[
                {"type": "pk", "columns": ["id"], "name": "products_pkey"},
                {"type": "check", "columns": [], "expression": "price >= 0", "name": "products_price_check"},
            ]),
        ])
        status, body = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert status == 200
        sql = body["sql"]
        assert "price >= 0" in sql
        assert '"products_price_check"' in sql

    def test_check_constraint_without_columns_key(self, client):
        """CHECK constraints should work even without a 'columns' key (backend defensiveness)."""
        schema = _simple_schema(tables=[
            _simple_table("items", [
                _simple_col("id", "bigint", nullable=False),
                _simple_col("qty", "integer", nullable=False),
            ], constraints=[
                {"type": "pk", "columns": ["id"], "name": "items_pkey"},
                {"type": "check", "expression": "qty > 0", "name": "items_qty_check"},
            ]),
        ])
        status, body = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert status == 200
        assert "qty > 0" in body["sql"]

    def test_transaction_wrapping(self, client):
        schema = _simple_schema(tables=[
            _simple_table("t", [_simple_col("id", "bigint")]),
        ])
        status, body = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        sql = body["sql"]
        assert sql.index("BEGIN;") < sql.index("CREATE TABLE")
        assert sql.index("CREATE TABLE") < sql.index("COMMIT;")

    def test_realistic_5_table_schema(self, client):
        """Full e-commerce schema: roles → users → products → orders → order_items."""
        schema = _simple_schema(
            tables=[
                _simple_table("roles", [
                    _simple_col("id", "bigint", nullable=False, identity="ALWAYS"),
                    _simple_col("name", "varchar(100)", nullable=False),
                ], constraints=[
                    {"type": "pk", "columns": ["id"], "name": "roles_pkey"},
                    {"type": "unique", "columns": ["name"], "name": "roles_name_key"},
                ]),
                _simple_table("users", [
                    _simple_col("id", "bigint", nullable=False, identity="ALWAYS"),
                    _simple_col("email", "varchar(320)", nullable=False),
                    _simple_col("role_id", "bigint", nullable=False),
                    _simple_col("status", "user_status", nullable=False, default_value="'active'"),
                    _simple_col("created_at", "timestamptz", nullable=False, default_value="NOW()"),
                ], constraints=[
                    {"type": "pk", "columns": ["id"], "name": "users_pkey"},
                    {"type": "unique", "columns": ["email"], "name": "users_email_key"},
                    {"type": "fk", "columns": ["role_id"], "refTable": "roles",
                     "refColumns": ["id"], "onDelete": "RESTRICT", "onUpdate": "NO ACTION",
                     "name": "users_role_id_fkey"},
                ], indexes=[
                    {"name": "users_email_idx", "columns": ["email"], "type": "btree", "unique": False},
                ]),
                _simple_table("products", [
                    _simple_col("id", "bigint", nullable=False, identity="ALWAYS"),
                    _simple_col("name", "varchar(200)", nullable=False),
                    _simple_col("price", "numeric(10,2)", nullable=False),
                    _simple_col("sku", "varchar(50)", nullable=False),
                ], constraints=[
                    {"type": "pk", "columns": ["id"], "name": "products_pkey"},
                    {"type": "unique", "columns": ["sku"], "name": "products_sku_key"},
                    {"type": "check", "columns": [], "expression": "price >= 0", "name": "products_price_check"},
                ]),
                _simple_table("orders", [
                    _simple_col("id", "bigint", nullable=False, identity="ALWAYS"),
                    _simple_col("user_id", "bigint", nullable=False),
                    _simple_col("total", "numeric(12,2)", nullable=False, default_value="0"),
                    _simple_col("ordered_at", "timestamptz", nullable=False, default_value="NOW()"),
                ], constraints=[
                    {"type": "pk", "columns": ["id"], "name": "orders_pkey"},
                    {"type": "fk", "columns": ["user_id"], "refTable": "users",
                     "refColumns": ["id"], "onDelete": "CASCADE", "onUpdate": "NO ACTION",
                     "name": "orders_user_id_fkey"},
                    {"type": "check", "columns": [], "expression": "total >= 0", "name": "orders_total_check"},
                ]),
                _simple_table("order_items", [
                    _simple_col("id", "bigint", nullable=False, identity="ALWAYS"),
                    _simple_col("order_id", "bigint", nullable=False),
                    _simple_col("product_id", "bigint", nullable=False),
                    _simple_col("quantity", "integer", nullable=False),
                    _simple_col("unit_price", "numeric(10,2)", nullable=False),
                ], constraints=[
                    {"type": "pk", "columns": ["id"], "name": "order_items_pkey"},
                    {"type": "fk", "columns": ["order_id"], "refTable": "orders",
                     "refColumns": ["id"], "onDelete": "CASCADE", "onUpdate": "NO ACTION",
                     "name": "order_items_order_id_fkey"},
                    {"type": "fk", "columns": ["product_id"], "refTable": "products",
                     "refColumns": ["id"], "onDelete": "RESTRICT", "onUpdate": "NO ACTION",
                     "name": "order_items_product_id_fkey"},
                    {"type": "check", "columns": [], "expression": "quantity > 0", "name": "order_items_qty_check"},
                ]),
            ],
            enums=[{"name": "user_status", "values": ["active", "inactive", "banned"]}],
        )

        status, body = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert status == 200
        sql = body["sql"]

        # Structure
        assert "BEGIN;" in sql
        assert "COMMIT;" in sql

        # All tables present
        for tbl in ["roles", "users", "products", "orders", "order_items"]:
            assert f'"{tbl}"' in sql

        # FK ordering: roles before users, users before orders, orders before order_items
        assert sql.index('"roles"') < sql.index('"users"')
        assert sql.index('"users"') < sql.index('"orders"')
        assert sql.index('"orders"') < sql.index('"order_items"')

        # Enum before tables
        assert sql.index("CREATE TYPE") < sql.index("CREATE TABLE")

        # Constraints present
        assert "ON DELETE CASCADE" in sql
        assert "ON DELETE RESTRICT" in sql
        assert "quantity > 0" in sql
        assert "price >= 0" in sql


# ============================================================
# POST /api/builder/generate-migration
# ============================================================

class TestGenerateMigrationEndpoint:

    def test_create_mode_when_no_original(self, client):
        schema = _simple_schema(tables=[
            _simple_table("users", [
                _simple_col("id", "bigint", nullable=False),
                _simple_col("name", "text"),
            ]),
        ])
        status, body = _post_json(client, "/api/builder/generate-migration", {
            "modified": schema,
        })
        assert status == 200
        assert body["mode"] == "create"
        assert "CREATE TABLE" in body["schemaSql"]

    def test_alter_mode_with_original(self, client):
        original = _simple_schema(tables=[
            _simple_table("users", [
                _simple_col("id", "bigint", nullable=False),
                _simple_col("name", "text"),
            ]),
        ])
        modified = _simple_schema(tables=[
            _simple_table("users", [
                _simple_col("id", "bigint", nullable=False),
                _simple_col("name", "text"),
                _simple_col("email", "varchar(320)"),
            ]),
        ])
        status, body = _post_json(client, "/api/builder/generate-migration", {
            "original": original,
            "modified": modified,
        })
        assert status == 200
        assert body["mode"] == "alter"
        assert "ALTER TABLE" in body["schemaSql"]
        assert '"email"' in body["schemaSql"]

    def test_missing_modified_returns_400(self, client):
        status, body = _post_json(client, "/api/builder/generate-migration", {})
        assert status == 400

    def test_source_mapping_generates_data_sql(self, client):
        schema = _simple_schema(tables=[
            _simple_table("users", [
                _simple_col("id", "bigint", nullable=False),
                _simple_col("name", "text"),
            ]),
        ])
        status, body = _post_json(client, "/api/builder/generate-migration", {
            "modified": schema,
            "sourceMapping": {
                "users.id": {"sourceTable": "raw_users", "sourceColumn": "user_id", "transform": "cast_bigint"},
                "users.name": {"sourceTable": "raw_users", "sourceColumn": "full_name", "transform": None},
            },
        })
        assert status == 200
        assert "INSERT INTO" in body["dataSql"]
        assert '"users"' in body["dataSql"]

    def test_alter_drops_column(self, client):
        original = _simple_schema(tables=[
            _simple_table("users", [
                _simple_col("id", "bigint", nullable=False),
                _simple_col("name", "text"),
                _simple_col("legacy_field", "text"),
            ]),
        ])
        modified = _simple_schema(tables=[
            _simple_table("users", [
                _simple_col("id", "bigint", nullable=False),
                _simple_col("name", "text"),
            ]),
        ])
        status, body = _post_json(client, "/api/builder/generate-migration", {
            "original": original,
            "modified": modified,
        })
        assert status == 200
        assert "DROP COLUMN" in body["schemaSql"]
        assert '"legacy_field"' in body["schemaSql"]

    def test_alter_type_change(self, client):
        original = _simple_schema(tables=[
            _simple_table("users", [
                _simple_col("id", "bigint", nullable=False),
                _simple_col("age", "text"),
            ]),
        ])
        modified = _simple_schema(tables=[
            _simple_table("users", [
                _simple_col("id", "bigint", nullable=False),
                _simple_col("age", "integer"),
            ]),
        ])
        status, body = _post_json(client, "/api/builder/generate-migration", {
            "original": original,
            "modified": modified,
        })
        assert status == 200
        assert "ALTER" in body["schemaSql"]
        assert "TYPE" in body["schemaSql"]


# ============================================================
# POST /api/builder/import-sql
# ============================================================

class TestImportSQLEndpoint:

    def test_import_json_body(self, client):
        sql = """
        CREATE TABLE "users" (
            "id" BIGINT NOT NULL,
            "name" VARCHAR(100)
        );
        """
        status, body = _post_json(client, "/api/builder/import-sql", {"sql": sql})
        assert status == 200
        assert len(body["schema"]["tables"]) == 1
        assert body["schema"]["tables"][0]["name"] == "users"
        assert len(body["schema"]["tables"][0]["columns"]) == 2

    def test_import_file_upload(self, client):
        sql_content = b"""
        CREATE TYPE "status" AS ENUM ('active', 'inactive');
        CREATE TABLE "accounts" (
            "id" BIGINT NOT NULL,
            "status" "status" DEFAULT 'active'
        );
        """
        resp = client.post(
            "/api/builder/import-sql",
            data={"file": (io.BytesIO(sql_content), "schema.sql")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body["schema"]["tables"]) == 1
        assert len(body["schema"]["enums"]) == 1
        assert body["schema"]["enums"][0]["name"] == "status"

    def test_empty_sql_returns_400(self, client):
        status, body = _post_json(client, "/api/builder/import-sql", {"sql": ""})
        assert status == 400

    def test_import_complex_schema(self, client):
        sql = """
        CREATE TYPE "user_status" AS ENUM ('active', 'inactive', 'banned');

        CREATE TABLE "roles" (
            "id" BIGINT GENERATED ALWAYS AS IDENTITY,
            "name" VARCHAR(100) NOT NULL,
            CONSTRAINT "roles_pkey" PRIMARY KEY ("id")
        );

        CREATE TABLE "users" (
            "id" BIGINT GENERATED ALWAYS AS IDENTITY,
            "email" VARCHAR(320) NOT NULL,
            "role_id" BIGINT NOT NULL,
            "status" "user_status" NOT NULL DEFAULT 'active',
            CONSTRAINT "users_pkey" PRIMARY KEY ("id"),
            CONSTRAINT "users_role_id_fkey" FOREIGN KEY ("role_id") REFERENCES "roles" ("id") ON DELETE CASCADE
        );

        CREATE INDEX "users_email_idx" ON "users" ("email");
        """
        status, body = _post_json(client, "/api/builder/import-sql", {"sql": sql})
        assert status == 200
        schema = body["schema"]
        assert len(schema["tables"]) == 2
        assert len(schema["enums"]) == 1

        # Verify users table structure
        users = next(t for t in schema["tables"] if t["name"] == "users")
        assert len(users["columns"]) == 4
        col_names = [c["name"] for c in users["columns"]]
        assert "email" in col_names
        assert "role_id" in col_names

    def test_round_trip_generate_then_import(self, client):
        """Generate DDL from schema, then import it back — should be equivalent."""
        original_schema = _simple_schema(
            tables=[
                _simple_table("categories", [
                    _simple_col("id", "bigint", nullable=False, identity="ALWAYS"),
                    _simple_col("name", "varchar(100)", nullable=False),
                ], constraints=[
                    {"type": "pk", "columns": ["id"], "name": "categories_pkey"},
                ]),
                _simple_table("items", [
                    _simple_col("id", "bigint", nullable=False, identity="ALWAYS"),
                    _simple_col("title", "text", nullable=False),
                    _simple_col("category_id", "bigint"),
                ], constraints=[
                    {"type": "pk", "columns": ["id"], "name": "items_pkey"},
                    {"type": "fk", "columns": ["category_id"], "refTable": "categories",
                     "refColumns": ["id"], "onDelete": "SET NULL", "onUpdate": "NO ACTION",
                     "name": "items_category_id_fkey"},
                ]),
            ],
        )

        # Step 1: Generate DDL
        status1, body1 = _post_json(client, "/api/builder/generate-ddl", {"schema": original_schema})
        assert status1 == 200
        generated_sql = body1["sql"]

        # Step 2: Import it back
        status2, body2 = _post_json(client, "/api/builder/import-sql", {"sql": generated_sql})
        assert status2 == 200
        imported = body2["schema"]

        # Step 3: Verify structural equivalence
        assert len(imported["tables"]) == 2
        orig_names = sorted(t["name"] for t in original_schema["tables"])
        imported_names = sorted(t["name"] for t in imported["tables"])
        assert orig_names == imported_names

        # Verify column counts match
        for orig_tbl in original_schema["tables"]:
            imp_tbl = next(t for t in imported["tables"] if t["name"] == orig_tbl["name"])
            assert len(imp_tbl["columns"]) == len(orig_tbl["columns"])


# ============================================================
# POST /api/builder/type-suggest
# ============================================================

class TestTypeSuggestEndpoint:

    def test_integer_type(self, client):
        status, body = _post_json(client, "/api/builder/type-suggest", {
            "sourceType": "INT",
            "column": "user_id",
        })
        assert status == 200
        assert "type" in body
        assert body["type"] in ("integer", "bigint", "smallint")

    def test_varchar_email(self, client):
        status, body = _post_json(client, "/api/builder/type-suggest", {
            "sourceType": "VARCHAR",
            "column": "email",
            "sampleValues": ["alice@example.com", "bob@test.org"],
        })
        assert status == 200
        assert "type" in body

    def test_boolean_type(self, client):
        status, body = _post_json(client, "/api/builder/type-suggest", {
            "sourceType": "BOOLEAN",
            "column": "is_active",
        })
        assert status == 200
        assert body["type"] == "boolean"

    def test_timestamp_type(self, client):
        status, body = _post_json(client, "/api/builder/type-suggest", {
            "sourceType": "TIMESTAMP",
            "column": "created_at",
        })
        assert status == 200
        assert "timestamp" in body["type"].lower()


# ============================================================
# POST /api/builder/preview-table
# ============================================================

class TestPreviewTableEndpoint:

    def test_preview_single_table(self, client):
        table = _simple_table("users", [
            _simple_col("id", "bigint", nullable=False, identity="ALWAYS"),
            _simple_col("email", "varchar(320)", nullable=False),
        ], constraints=[
            {"type": "pk", "columns": ["id"], "name": "users_pkey"},
        ])
        status, body = _post_json(client, "/api/builder/preview-table", {"table": table})
        assert status == 200
        sql = body["sql"]
        assert "CREATE TABLE" in sql
        assert '"users"' in sql
        assert '"id"' in sql
        # Preview should NOT have BEGIN/COMMIT
        assert "BEGIN;" not in sql

    def test_missing_table_returns_400(self, client):
        status, body = _post_json(client, "/api/builder/preview-table", {})
        assert status == 400


# ============================================================
# GET /api/builder/source-tables
# ============================================================

class TestSourceTablesEndpoint:

    def test_returns_empty_when_no_csv_loaded(self, client):
        status, body = _post_json(client, "/api/builder/source-tables", {})
        # It's a GET endpoint, use get
        resp = client.get("/api/builder/source-tables")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "tables" in body
        assert isinstance(body["tables"], list)


# ============================================================
# End-to-end: validate → generate pipeline
# ============================================================

class TestValidateThenGenerate:

    def test_valid_schema_validates_and_generates(self, client):
        """Simulate the UI flow: validate first, then generate DDL."""
        schema = _simple_schema(tables=[
            _simple_table("departments", [
                _simple_col("id", "bigint", nullable=False, identity="ALWAYS"),
                _simple_col("name", "varchar(100)", nullable=False),
            ], constraints=[
                {"type": "pk", "columns": ["id"], "name": "departments_pkey"},
                {"type": "unique", "columns": ["name"], "name": "departments_name_key"},
            ]),
            _simple_table("employees", [
                _simple_col("id", "bigint", nullable=False, identity="ALWAYS"),
                _simple_col("first_name", "varchar(100)", nullable=False),
                _simple_col("last_name", "varchar(100)", nullable=False),
                _simple_col("dept_id", "bigint", nullable=False),
                _simple_col("salary", "numeric(12,2)", nullable=False),
            ], constraints=[
                {"type": "pk", "columns": ["id"], "name": "employees_pkey"},
                {"type": "fk", "columns": ["dept_id"], "refTable": "departments",
                 "refColumns": ["id"], "onDelete": "RESTRICT", "onUpdate": "NO ACTION",
                 "name": "employees_dept_id_fkey"},
                {"type": "check", "columns": [], "expression": "salary > 0", "name": "employees_salary_check"},
            ], indexes=[
                {"name": "employees_dept_idx", "columns": ["dept_id"], "type": "btree", "unique": False},
                {"name": "employees_name_idx", "columns": ["last_name", "first_name"],
                 "type": "btree", "unique": False},
            ]),
        ])

        # Step 1: Validate
        s1, b1 = _post_json(client, "/api/builder/validate", {"schema": schema})
        assert s1 == 200
        errors = [i for i in b1["issues"] if i["severity"] == "error"]
        assert errors == [], f"Unexpected validation errors: {errors}"

        # Step 2: Generate DDL
        s2, b2 = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert s2 == 200
        sql = b2["sql"]

        # Verify structure
        assert "BEGIN;" in sql
        assert "COMMIT;" in sql
        assert '"departments"' in sql
        assert '"employees"' in sql
        assert "salary > 0" in sql
        assert "ON DELETE RESTRICT" in sql
        assert "CREATE INDEX" in sql
        assert '"employees_dept_idx"' in sql
        assert '"employees_name_idx"' in sql

    def test_invalid_schema_caught_before_export(self, client):
        """Schema with errors should be caught by validate — UI would block export."""
        schema = _simple_schema(tables=[
            _simple_table('bad"--injection', [
                _simple_col("id", "bigint"),
            ]),
        ])

        s1, b1 = _post_json(client, "/api/builder/validate", {"schema": schema})
        assert s1 == 200
        errors = [i for i in b1["issues"] if i["severity"] == "error"]
        assert len(errors) > 0, "Injection in table name should be caught"

    def test_full_lifecycle_create_validate_generate_import(self, client):
        """Full lifecycle: build schema → validate → generate DDL → import back."""
        schema = _simple_schema(
            tables=[
                _simple_table("tags", [
                    _simple_col("id", "bigint", nullable=False, identity="ALWAYS"),
                    _simple_col("label", "varchar(50)", nullable=False),
                ], constraints=[
                    {"type": "pk", "columns": ["id"], "name": "tags_pkey"},
                    {"type": "unique", "columns": ["label"], "name": "tags_label_key"},
                ]),
                _simple_table("articles", [
                    _simple_col("id", "bigint", nullable=False, identity="ALWAYS"),
                    _simple_col("title", "text", nullable=False),
                    _simple_col("body", "text"),
                    _simple_col("published", "boolean", nullable=False, default_value="FALSE"),
                ], constraints=[
                    {"type": "pk", "columns": ["id"], "name": "articles_pkey"},
                ]),
                _simple_table("article_tags", [
                    _simple_col("article_id", "bigint", nullable=False),
                    _simple_col("tag_id", "bigint", nullable=False),
                ], constraints=[
                    {"type": "pk", "columns": ["article_id", "tag_id"], "name": "article_tags_pkey"},
                    {"type": "fk", "columns": ["article_id"], "refTable": "articles",
                     "refColumns": ["id"], "onDelete": "CASCADE", "onUpdate": "NO ACTION",
                     "name": "article_tags_article_id_fkey"},
                    {"type": "fk", "columns": ["tag_id"], "refTable": "tags",
                     "refColumns": ["id"], "onDelete": "CASCADE", "onUpdate": "NO ACTION",
                     "name": "article_tags_tag_id_fkey"},
                ]),
            ],
        )

        # Validate
        s1, b1 = _post_json(client, "/api/builder/validate", {"schema": schema})
        assert s1 == 200
        errors = [i for i in b1["issues"] if i["severity"] == "error"]
        assert errors == []

        # Generate
        s2, b2 = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert s2 == 200
        sql = b2["sql"]

        # Import back
        s3, b3 = _post_json(client, "/api/builder/import-sql", {"sql": sql})
        assert s3 == 200
        imported = b3["schema"]
        assert len(imported["tables"]) == 3
        imported_names = sorted(t["name"] for t in imported["tables"])
        assert imported_names == ["article_tags", "articles", "tags"]

        # Re-generate from imported and compare
        s4, b4 = _post_json(client, "/api/builder/generate-ddl", {"schema": imported})
        assert s4 == 200
        sql2 = b4["sql"]
        # Both should contain the same tables
        for tbl in ["tags", "articles", "article_tags"]:
            assert f'"{tbl}"' in sql2


# ============================================================
# Missing field validation — must return 400, never 500
# ============================================================

class TestMissingFieldValidation:
    """Routes must reject incomplete payloads with 400, not crash with 500.

    These test the route-level structural validation that guards against
    KeyError crashes in the backend generators.
    """

    def test_column_missing_name(self, client):
        schema = _simple_schema(tables=[
            _simple_table("t", [{"type": "text", "nullable": True}]),
        ])
        status, body = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert status == 400
        assert "details" in body

    def test_column_missing_type(self, client):
        schema = _simple_schema(tables=[
            _simple_table("t", [{"name": "id", "nullable": False, "identity": "ALWAYS"}]),
        ])
        status, body = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert status == 400
        assert any("type" in d for d in body["details"])

    def test_fk_missing_ref_columns(self, client):
        schema = _simple_schema(tables=[
            _simple_table("a", [_simple_col("id", "bigint")], constraints=[
                {"type": "fk", "columns": ["id"], "refTable": "b", "name": "a_fk",
                 "onDelete": "CASCADE", "onUpdate": "NO ACTION"},
            ]),
            _simple_table("b", [_simple_col("id", "bigint")]),
        ])
        status, body = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert status == 400
        assert any("refColumns" in d for d in body["details"])

    def test_fk_missing_ref_table(self, client):
        schema = _simple_schema(tables=[
            _simple_table("a", [_simple_col("id", "bigint")], constraints=[
                {"type": "fk", "columns": ["id"], "refColumns": ["id"], "name": "a_fk",
                 "onDelete": "CASCADE", "onUpdate": "NO ACTION"},
            ]),
        ])
        status, body = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert status == 400
        assert any("refTable" in d for d in body["details"])

    def test_fk_missing_name(self, client):
        schema = _simple_schema(tables=[
            _simple_table("a", [_simple_col("id", "bigint")], constraints=[
                {"type": "fk", "columns": ["id"], "refTable": "b", "refColumns": ["id"],
                 "onDelete": "CASCADE", "onUpdate": "NO ACTION"},
            ]),
            _simple_table("b", [_simple_col("id", "bigint")]),
        ])
        status, body = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert status == 400
        assert any("name" in d for d in body["details"])

    def test_check_missing_expression(self, client):
        schema = _simple_schema(tables=[
            _simple_table("t", [_simple_col("id", "bigint")], constraints=[
                {"type": "check", "name": "chk1"},
            ]),
        ])
        status, body = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert status == 400
        assert any("expression" in d for d in body["details"])

    def test_index_missing_name(self, client):
        schema = _simple_schema(tables=[
            _simple_table("t", [_simple_col("id", "bigint")], indexes=[
                {"columns": ["id"], "type": "btree", "unique": False},
            ]),
        ])
        status, body = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert status == 400
        assert any("name" in d for d in body["details"])

    def test_enum_missing_values(self, client):
        schema = _simple_schema(tables=[], enums=[{"name": "status"}])
        status, body = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert status == 400
        assert any("values" in d for d in body["details"])

    def test_enum_missing_name(self, client):
        schema = _simple_schema(tables=[], enums=[{"values": ["a", "b"]}])
        status, body = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert status == 400
        assert any("name" in d for d in body["details"])

    def test_table_missing_name(self, client):
        schema = _simple_schema(tables=[{
            "columns": [_simple_col("id", "bigint")],
            "constraints": [], "indexes": [],
            "tableType": "permanent", "ifNotExists": False,
        }])
        status, body = _post_json(client, "/api/builder/generate-ddl", {"schema": schema})
        assert status == 400
        assert any("name" in d for d in body["details"])

    def test_constraint_missing_name_in_validate(self, client):
        schema = _simple_schema(tables=[
            _simple_table("t", [_simple_col("id", "bigint")], constraints=[
                {"type": "pk", "columns": ["id"]},
            ]),
        ])
        status, body = _post_json(client, "/api/builder/validate", {"schema": schema})
        assert status == 400
        assert "details" in body

    def test_migration_skips_mapping_without_source_column(self, client):
        """Missing sourceColumn in mapping should be skipped, not crash."""
        schema = _simple_schema(tables=[
            _simple_table("users", [_simple_col("id", "bigint")]),
        ])
        status, body = _post_json(client, "/api/builder/generate-migration", {
            "modified": schema,
            "sourceMapping": {
                "users.id": {"sourceTable": "raw", "transform": None},
            },
        })
        assert status == 200
        # The mapping was skipped, so no INSERT generated
        assert "INSERT" not in body.get("dataSql", "")

    def test_migration_skips_mapping_without_source_table(self, client):
        """Missing sourceTable in mapping should be skipped, not crash."""
        schema = _simple_schema(tables=[
            _simple_table("users", [_simple_col("id", "bigint")]),
        ])
        status, body = _post_json(client, "/api/builder/generate-migration", {
            "modified": schema,
            "sourceMapping": {
                "users.id": {"sourceColumn": "user_id", "transform": None},
            },
        })
        assert status == 200
        assert "INSERT" not in body.get("dataSql", "")

    def test_preview_table_missing_name(self, client):
        table = {
            "columns": [_simple_col("id", "bigint")],
            "constraints": [], "indexes": [],
            "tableType": "permanent", "ifNotExists": False,
        }
        status, body = _post_json(client, "/api/builder/preview-table", {"table": table})
        assert status == 400

    def test_generate_migration_rejects_incomplete_modified(self, client):
        """Modified schema with missing fields should be caught."""
        schema = _simple_schema(tables=[{
            "columns": [_simple_col("id", "bigint")],
            "constraints": [], "indexes": [],
            "tableType": "permanent", "ifNotExists": False,
        }])
        status, body = _post_json(client, "/api/builder/generate-migration", {
            "modified": schema,
        })
        assert status == 400
