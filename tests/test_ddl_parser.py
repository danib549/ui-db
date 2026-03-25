"""Tests for ddl_parser.py"""
import pytest
from ddl_parser import (
    parse_ddl, strip_comments, split_statements, classify_statement,
    parse_create_table, parse_create_type, parse_create_index, normalize_pg_type,
)


def test_strip_single_line_comment():
    result = strip_comments("SELECT 1; -- comment\nSELECT 2;")
    assert "--" not in result
    assert "SELECT 2" in result


def test_strip_multi_line_comment():
    result = strip_comments("SELECT /* comment */ 1;")
    assert "/*" not in result
    assert "SELECT" in result


def test_strip_preserves_strings():
    result = strip_comments("SELECT 'hello -- world';")
    assert "hello -- world" in result


def test_split_statements():
    stmts = split_statements("CREATE TABLE a (x int); CREATE TABLE b (y int);")
    assert len(stmts) == 2


def test_split_respects_parens():
    stmts = split_statements("CREATE TABLE a (x int; y int);")
    # Semicolon inside parens should NOT split
    assert len(stmts) == 1


def test_classify_create_table():
    assert classify_statement("CREATE TABLE users (id int)") == "create_table"
    assert classify_statement("CREATE TEMP TABLE t (x int)") == "create_table"
    assert classify_statement("CREATE UNLOGGED TABLE t (x int)") == "create_table"


def test_classify_create_type():
    assert classify_statement("CREATE TYPE status AS ENUM ('a')") == "create_type"


def test_classify_alter_table():
    assert classify_statement("ALTER TABLE users ADD CONSTRAINT pk PRIMARY KEY (id)") == "alter_table"


def test_classify_set():
    assert classify_statement("SET client_encoding = 'UTF8'") == "set"


def test_parse_create_table_basic():
    sql = 'CREATE TABLE "users" ("id" BIGINT NOT NULL, "name" TEXT)'
    table = parse_create_table(sql)
    assert table["name"] == "users"
    assert len(table["columns"]) == 2
    assert table["columns"][0]["name"] == "id"
    assert table["columns"][0]["nullable"] is False


def test_parse_create_table_with_constraints():
    sql = '''CREATE TABLE "orders" (
        "id" INTEGER NOT NULL,
        "user_id" INTEGER,
        CONSTRAINT "orders_pkey" PRIMARY KEY ("id"),
        CONSTRAINT "orders_user_fkey" FOREIGN KEY ("user_id") REFERENCES "users" ("id") ON DELETE CASCADE
    )'''
    table = parse_create_table(sql)
    assert table["name"] == "orders"
    assert len(table["constraints"]) == 2
    pk = [c for c in table["constraints"] if c["type"] == "pk"][0]
    assert pk["columns"] == ["id"]
    fk = [c for c in table["constraints"] if c["type"] == "fk"][0]
    assert fk["refTable"] == "users"
    assert fk["onDelete"] == "CASCADE"


def test_parse_create_type_enum():
    sql = "CREATE TYPE \"status\" AS ENUM ('active', 'inactive')"
    enum = parse_create_type(sql)
    assert enum["name"] == "status"
    assert enum["values"] == ["active", "inactive"]


def test_parse_create_index():
    sql = 'CREATE INDEX "users_email_idx" ON "users" ("email")'
    idx = parse_create_index(sql)
    assert idx["name"] == "users_email_idx"
    assert idx["table"] == "users"
    assert idx["columns"] == ["email"]
    assert idx["type"] == "btree"


def test_parse_create_unique_index():
    sql = 'CREATE UNIQUE INDEX "idx" ON "t" USING GIN ("data")'
    idx = parse_create_index(sql)
    assert idx["unique"] is True
    assert idx["type"] == "gin"


def test_normalize_pg_type():
    assert normalize_pg_type("character varying(255)") == "varchar(255)"
    assert normalize_pg_type("timestamp with time zone") == "timestamptz"
    assert normalize_pg_type("integer") == "integer"


def test_full_parse_pipeline():
    sql = """
    SET client_encoding = 'UTF8';
    BEGIN;
    CREATE TYPE "status" AS ENUM ('a', 'b');
    CREATE TABLE "users" (
        "id" BIGINT NOT NULL,
        "email" VARCHAR(255)
    );
    ALTER TABLE "users" ADD CONSTRAINT "users_pkey" PRIMARY KEY ("id");
    CREATE INDEX "users_email_idx" ON "users" ("email");
    COMMIT;
    """
    result = parse_ddl(sql)
    assert len(result["enums"]) == 1
    assert len(result["tables"]) == 1
    assert result["tables"][0]["name"] == "users"
    assert len(result["tables"][0]["constraints"]) == 1
    assert len(result["tables"][0]["indexes"]) == 1
    assert len(result["warnings"]) == 0


def test_pg_dump_format():
    sql = """
    SET statement_timeout = 0;
    CREATE TABLE public.users (
        id bigint NOT NULL,
        email character varying(320)
    );
    ALTER TABLE ONLY public.users
        ADD CONSTRAINT users_pkey PRIMARY KEY (id);
    """
    result = parse_ddl(sql)
    assert len(result["tables"]) == 1
    assert result["tables"][0]["name"] == "users"
    assert len(result["tables"][0]["constraints"]) == 1


# ---- Issue 7: Escaped single quotes ----

def test_split_statements_escaped_quotes():
    sql = "INSERT INTO t VALUES ('it''s'); INSERT INTO t VALUES ('ok')"
    stmts = split_statements(sql)
    assert len(stmts) == 2
    assert "it''s" in stmts[0]


def test_split_statements_multiple_escaped_quotes():
    sql = "INSERT INTO t VALUES ('it''s a ''test'''); SELECT 1"
    stmts = split_statements(sql)
    assert len(stmts) == 2
    assert "it''s a ''test'''" in stmts[0]


def test_parse_column_with_escaped_default():
    sql = '''CREATE TABLE "t" ("name" VARCHAR(100) DEFAULT 'it''s a test' NOT NULL)'''
    table = parse_create_table(sql)
    assert table["name"] == "t"
    assert len(table["columns"]) == 1
    assert "it''s" in table["columns"][0].get("defaultValue", "")


# ---- Additional parser tests ----

def test_parse_create_table_if_not_exists():
    sql = 'CREATE TABLE IF NOT EXISTS "t" ("id" INTEGER)'
    table = parse_create_table(sql)
    assert table["name"] == "t"
    assert table["ifNotExists"] is True


def test_parse_unlogged_table():
    sql = 'CREATE UNLOGGED TABLE "t" ("id" INTEGER)'
    table = parse_create_table(sql)
    assert table["tableType"] == "unlogged"


def test_parse_identity_always():
    sql = 'CREATE TABLE "t" ("id" BIGINT GENERATED ALWAYS AS IDENTITY)'
    table = parse_create_table(sql)
    assert table["columns"][0]["identity"] == "ALWAYS"


def test_parse_identity_by_default():
    sql = 'CREATE TABLE "t" ("id" BIGINT GENERATED BY DEFAULT AS IDENTITY)'
    table = parse_create_table(sql)
    assert table["columns"][0]["identity"] == "BY DEFAULT"


def test_parse_inline_fk_reference():
    sql = 'CREATE TABLE "t" ("user_id" INTEGER REFERENCES "users" ("id"))'
    from ddl_parser import merge_inline_fks
    table = parse_create_table(sql)
    table = merge_inline_fks([table])[0]
    fk_constraints = [c for c in table["constraints"] if c["type"] == "fk"]
    assert len(fk_constraints) == 1
    assert fk_constraints[0]["refTable"] == "users"


def test_parse_check_constraint():
    sql = 'CREATE TABLE "t" ("age" INTEGER, CONSTRAINT "t_check" CHECK ("age" >= 0))'
    table = parse_create_table(sql)
    checks = [c for c in table["constraints"] if c["type"] == "check"]
    assert len(checks) == 1
    assert '"age" >= 0' in checks[0]["expression"]


def test_parse_multi_column_pk():
    sql = 'CREATE TABLE "t" ("a" INTEGER, "b" INTEGER, CONSTRAINT "t_pk" PRIMARY KEY ("a", "b"))'
    table = parse_create_table(sql)
    pks = [c for c in table["constraints"] if c["type"] == "pk"]
    assert len(pks) == 1
    assert pks[0]["columns"] == ["a", "b"]
