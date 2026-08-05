"""Tests for _strip_code_fences in cache_pipeline.py."""

import pytest

from backend.pipelines.cache_pipeline import _strip_code_fences


class TestStripCodeFences:
    def test_no_fences_unchanged(self):
        assert _strip_code_fences("SELECT 1") == "SELECT 1"

    def test_sql_fences_stripped(self):
        raw = "```sql\nSELECT 1\n```"
        assert _strip_code_fences(raw) == "SELECT 1"

    def test_no_language_tag(self):
        raw = "```\nsome content\n```"
        assert _strip_code_fences(raw) == "some content"

    def test_json_fences(self):
        raw = '```json\n{"key": "val"}\n```'
        assert _strip_code_fences(raw) == '{"key": "val"}'

    def test_whitespace_only(self):
        assert _strip_code_fences("   ") == ""

    def test_empty_string(self):
        assert _strip_code_fences("") == ""

    def test_leading_trailing_whitespace_trimmed(self):
        raw = "  ```sql\nSELECT 1\n```  "
        assert _strip_code_fences(raw) == "SELECT 1"

    def test_multiline_sql(self):
        raw = "```sql\nSELECT *\nFROM table\nWHERE x = 1\n```"
        result = _strip_code_fences(raw)
        assert result.startswith("SELECT *")
        assert "WHERE x = 1" in result

    def test_fences_only_no_content(self):
        raw = "```sql\n```"
        result = _strip_code_fences(raw)
        assert result == ""
