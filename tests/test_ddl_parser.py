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
