"""Tests for the query preprocessor: normalization and key term extraction."""

import pytest

from backend.services.preprocessor import extract_key_terms, normalize_query


class TestNormalizeQuery:
    def test_basic_normalization(self):
        assert normalize_query("Show me the revenue") == "revenue"

    def test_removes_punctuation(self):
        assert normalize_query("What's the revenue?") == "whats revenue"

    def test_lowercases(self):
        assert normalize_query("TOTAL Revenue BY Quarter") == "total revenue quarter"

    def test_removes_stop_words(self):
        result = normalize_query("please show me the top 10 patients")
        assert "please" not in result
        assert "show" not in result
        assert "me" not in result
        assert "the" not in result
        assert "top" in result
        assert "10" in result
        assert "patients" in result

    def test_collapses_whitespace(self):
        result = normalize_query("revenue   by    quarter")
        assert "  " not in result

    def test_empty_input(self):
        assert normalize_query("") == ""

    def test_only_stop_words(self):
        assert normalize_query("show me the") == ""

    def test_preserves_numbers(self):
        result = normalize_query("top 5 trials in phase 3")
        assert "5" in result
        assert "trials" in result
        assert "phase" in result
        assert "3" in result

    def test_preserves_domain_terms(self):
        result = normalize_query("total enrollment for clinical trials")
        assert "total" in result
        assert "enrollment" in result
        assert "clinical" in result
        assert "trials" in result

    def test_strips_leading_trailing_spaces(self):
        assert normalize_query("  revenue  ") == "revenue"

    def test_complex_query(self):
        result = normalize_query(
            "What are the top 3 countries with the highest vaccine stockout rates?"
        )
        assert "top" in result
        assert "3" in result
        assert "countries" in result
        assert "highest" in result
        assert "vaccine" in result
        assert "stockout" in result
        assert "rates" in result


class TestExtractKeyTerms:
    def test_basic(self):
        terms = extract_key_terms("Show me the revenue by quarter")
        assert "revenue" in terms
        assert "quarter" in terms

    def test_empty_string(self):
        assert extract_key_terms("") == []

    def test_only_stop_words(self):
        assert extract_key_terms("the and or") == []

    def test_returns_list(self):
        terms = extract_key_terms("total revenue by quarter")
        assert isinstance(terms, list)
        assert all(isinstance(t, str) for t in terms)

    def test_no_duplicates_from_whitespace(self):
        terms = extract_key_terms("revenue  revenue")
        # Both instances survive since we don't deduplicate
        assert terms.count("revenue") == 2
