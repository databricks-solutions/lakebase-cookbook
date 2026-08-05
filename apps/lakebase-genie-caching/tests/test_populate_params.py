"""Tests for _substitute_params — the parameterized SQL substitution helper."""

import pytest

from backend.services.graph import _substitute_params


class TestSubstituteParamsBasic:
    """Normal substitution: :param outside quotes gets wrapped in quotes."""

    def test_string_value_outside_quotes(self):
        sql = "SELECT * FROM t WHERE disease = :disease"
        result = _substitute_params(sql, {"disease": "cholangiocarcinoma"})
        assert result == "SELECT * FROM t WHERE disease = 'cholangiocarcinoma'"

    def test_numeric_value_no_quotes(self):
        sql = "SELECT * FROM t WHERE phase = :phase"
        result = _substitute_params(sql, {"phase": 3})
        assert result == "SELECT * FROM t WHERE phase = 3"

    def test_float_value_no_quotes(self):
        sql = "SELECT * FROM t WHERE score > :threshold"
        result = _substitute_params(sql, {"threshold": 0.95})
        assert result == "SELECT * FROM t WHERE score > 0.95"

    def test_empty_params_returns_unchanged(self):
        sql = "SELECT 1"
        assert _substitute_params(sql, {}) == "SELECT 1"

    def test_none_value_skipped(self):
        sql = "SELECT * FROM t WHERE x = :x AND y = :y"
        result = _substitute_params(sql, {"x": "hello", "y": None})
        assert result == "SELECT * FROM t WHERE x = 'hello' AND y = :y"


class TestSubstituteParamsInQuotes:
    """Placeholders already inside single-quoted strings skip outer quotes."""

    def test_ilike_pattern(self):
        sql = "SELECT * FROM t WHERE name ILIKE '%:disease%'"
        result = _substitute_params(sql, {"disease": "cholangiocarcinoma"})
        assert result == "SELECT * FROM t WHERE name ILIKE '%cholangiocarcinoma%'"

    def test_equals_quoted(self):
        sql = "SELECT * FROM t WHERE status = ':status'"
        result = _substitute_params(sql, {"status": "active"})
        assert result == "SELECT * FROM t WHERE status = 'active'"

    def test_mixed_quoted_and_unquoted(self):
        sql = "SELECT * FROM t WHERE a = :a AND b ILIKE '%:b%'"
        result = _substitute_params(sql, {"a": "foo", "b": "bar"})
        assert "'foo'" in result
        assert "'%bar%'" in result
        assert "'%'bar'%'" not in result


class TestSubstituteParamsEdgeCases:
    """Edge cases: escaping, prefix collisions, multiple occurrences."""

    def test_single_quote_in_value_escaped(self):
        sql = "SELECT * FROM t WHERE name = :name"
        result = _substitute_params(sql, {"name": "O'Brien"})
        assert result == "SELECT * FROM t WHERE name = 'O''Brien'"

    def test_longest_key_first(self):
        sql = "SELECT * FROM t WHERE phase_name = :phase_name AND phase = :phase"
        result = _substitute_params(sql, {"phase": 3, "phase_name": "Phase III"})
        assert ":phase_name" not in result
        assert ":phase" not in result
        assert "'Phase III'" in result
        assert "3" in result

    def test_multiple_occurrences(self):
        sql = "SELECT :x, :x FROM t"
        result = _substitute_params(sql, {"x": "val"})
        assert result == "SELECT 'val', 'val' FROM t"

    def test_no_matching_params_unchanged(self):
        sql = "SELECT * FROM t WHERE y = :y"
        result = _substitute_params(sql, {"x": "val"})
        assert result == "SELECT * FROM t WHERE y = :y"

    def test_word_boundary_prevents_partial(self):
        sql = "SELECT :disease_type FROM t"
        result = _substitute_params(sql, {"disease": "cancer"})
        assert result == "SELECT :disease_type FROM t"
