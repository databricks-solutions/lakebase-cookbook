"""Tests for database utility functions."""

import pytest

import backend.services.db as db
from backend.services.db import (
    _convert_params,
    _ensure_lakebase_host_configured,
    is_schema_ownership_error,
)


class TestConvertParams:
    """Tests for :name → %(name)s parameter conversion."""

    def test_no_params(self):
        sql, params = _convert_params("SELECT 1", None)
        assert sql == "SELECT 1"
        assert params is None

    def test_empty_dict(self):
        sql, params = _convert_params("SELECT 1", {})
        assert sql == "SELECT 1"
        assert params == {}

    def test_single_param(self):
        sql, params = _convert_params(
            "SELECT * FROM t WHERE id = :id",
            {"id": "abc"},
        )
        assert sql == "SELECT * FROM t WHERE id = %(id)s"
        assert params == {"id": "abc"}

    def test_multiple_params(self):
        sql, params = _convert_params(
            "SELECT * FROM t WHERE a = :a AND b = :b",
            {"a": 1, "b": 2},
        )
        assert sql == "SELECT * FROM t WHERE a = %(a)s AND b = %(b)s"

    def test_param_with_underscore(self):
        sql, _ = _convert_params(
            "WHERE user_id = :user_id", {"user_id": "u1"},
        )
        assert sql == "WHERE user_id = %(user_id)s"

    def test_does_not_replace_double_colon(self):
        sql, _ = _convert_params(
            "SELECT :val::jsonb", {"val": "{}"},
        )
        assert "%(val)s" in sql
        assert "::jsonb" in sql

    def test_does_not_replace_inside_string_literals(self):
        sql, _ = _convert_params(
            "SELECT * FROM t WHERE x = :x",
            {"x": "value:with:colons"},
        )
        assert sql == "SELECT * FROM t WHERE x = %(x)s"

    def test_repeated_param_name(self):
        sql, _ = _convert_params(
            "WHERE a = :val OR b = :val",
            {"val": 42},
        )
        assert sql == "WHERE a = %(val)s OR b = %(val)s"

    def test_vector_cast_preserved(self):
        sql, _ = _convert_params(
            "SELECT 1 - (query_embedding <=> :embedding::vector)",
            {"embedding": "[0.1,0.2]"},
        )
        assert "%(embedding)s" in sql
        assert "::vector" in sql


class TestLakebaseHostValidation:
    def test_raises_before_libpq_socket_fallback(self):
        with pytest.raises(RuntimeError, match="Lakebase host is not configured"):
            _ensure_lakebase_host_configured(host="", autoscaling=False, endpoint="")

    def test_allows_resolved_host(self):
        _ensure_lakebase_host_configured(
            host="ep-example.database.cloud.databricks.net",
            autoscaling=True,
            endpoint="projects/demo/branches/production/endpoints/primary",
        )


class TestSchemaOwnershipErrors:
    def test_detects_not_owner_errors(self):
        assert is_schema_ownership_error(Exception("must be owner of table cache_entries"))

    def test_ignores_unrelated_errors(self):
        assert not is_schema_ownership_error(Exception("syntax error at or near SELECT"))
