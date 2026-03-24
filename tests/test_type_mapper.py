"""Tests for type_mapper.py"""
import pytest
from type_mapper import suggest_pg_type


def test_int_default():
    result = suggest_pg_type("INT", "count")
    assert result["type"] == "integer"


def test_int_bigint_for_large_values():
    result = suggest_pg_type("INT", "big_id", sample_values=["3000000000"])
    assert result["type"] == "bigint"


def test_int_smallint_for_small_values():
    result = suggest_pg_type("INT", "age", sample_values=["25", "30", "18"])
    assert result["type"] == "smallint"


def test_int_identity_pk():
    result = suggest_pg_type("INT", "id", nullable=False, unique_count=100, total_count=100)
    assert result["type"] == "bigint"
    assert result["identity"] == "ALWAYS"
    assert result["confidence"] == "high"


def test_float_default():
    result = suggest_pg_type("FLOAT", "value")
    assert result["type"] == "double precision"


def test_float_currency():
    result = suggest_pg_type("FLOAT", "price", sample_values=["19.99", "5.00", "123.45"])
    assert result["type"] == "numeric(15,2)"
    assert result["confidence"] == "high"


def test_varchar_uuid():
    result = suggest_pg_type("VARCHAR", "external_id", sample_values=[
        "550e8400-e29b-41d4-a716-446655440000",
        "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
    ])
    assert result["type"] == "uuid"


def test_varchar_email():
    result = suggest_pg_type("VARCHAR", "email", sample_values=[
        "user@example.com", "admin@test.org",
    ])
    assert result["type"] == "varchar(320)"


def test_varchar_json():
    result = suggest_pg_type("VARCHAR", "data", sample_values=['{"key": "val"}', '[1,2,3]'])
    assert result["type"] == "jsonb"


def test_varchar_ip():
    result = suggest_pg_type("VARCHAR", "ip_addr", sample_values=["192.168.1.1", "10.0.0.1"])
    assert result["type"] == "inet"


def test_varchar_short():
    result = suggest_pg_type("VARCHAR", "code", sample_values=["AB", "CD", "EF"])
    assert result["type"] == "varchar(50)"


def test_varchar_enum_suggestion():
    result = suggest_pg_type("VARCHAR", "status", unique_count=3, total_count=100,
                             sample_values=["active", "inactive", "pending"])
    assert result["type"] == "enum"


def test_boolean():
    result = suggest_pg_type("BOOLEAN", "is_active")
    assert result["type"] == "boolean"


def test_timestamp():
    result = suggest_pg_type("TIMESTAMP", "created_at")
    assert result["type"] == "timestamptz"


def test_text():
    result = suggest_pg_type("TEXT", "description")
    assert result["type"] == "text"
