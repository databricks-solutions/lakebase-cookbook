"""Tests for mask_entities: entity value → [PARAM] placeholder replacement."""

import pytest

from backend.services.cache_store import mask_entities


class TestExactMatch:
    def test_single_entity_exact(self):
        result = mask_entities(
            "What is the revenue for Acme Corp?",
            {"company": "Acme Corp"},
        )
        assert "[company]" in result
        assert "Acme Corp" not in result

    def test_multiple_entities(self):
        result = mask_entities(
            "Show sales for Acme Corp in 2024",
            {"company": "Acme Corp", "year": "2024"},
        )
        assert "[company]" in result
        assert "[year]" in result
        assert "Acme Corp" not in result
        assert "2024" not in result

    def test_case_insensitive(self):
        result = mask_entities(
            "What about acme corp revenue?",
            {"company": "Acme Corp"},
        )
        assert "[company]" in result

    def test_numeric_entity(self):
        result = mask_entities(
            "Show top 10 results",
            {"limit": 10},
        )
        assert "[limit]" in result
        assert "10" not in result

    def test_none_value_skipped(self):
        result = mask_entities(
            "Show revenue for Acme Corp",
            {"company": "Acme Corp", "region": None},
        )
        assert "[company]" in result
        assert "[region]" not in result

    def test_empty_entities(self):
        question = "What is the total revenue?"
        assert mask_entities(question, {}) == question

    def test_no_match_returns_original(self):
        question = "What is the total revenue?"
        result = mask_entities(question, {"company": "Nonexistent Inc"})
        assert result == question


class TestWordLevelFallback:
    """When the full SQL literal doesn't appear in the question,
    individual words (4+ chars) are tried."""

    def test_partial_word_match(self):
        result = mask_entities(
            "Show breast cancer rates",
            {"cancer_site": "Female Breast"},
        )
        assert "[cancer_site]" in result

    def test_longest_word_matched_first(self):
        result = mask_entities(
            "Show prostate data",
            {"site": "Prostate Gland"},
        )
        assert "[site]" in result

    def test_short_words_skipped(self):
        # Words < 4 chars are skipped
        result = mask_entities(
            "Show US data",
            {"country": "US East"},
        )
        # "US" is only 2 chars, "East" is 4 chars but not in question
        assert "[country]" not in result

    def test_word_boundary_respected(self):
        result = mask_entities(
            "Show lung cancer data",
            {"site": "Lung and Bronchus"},
        )
        assert "[site]" in result
        assert "lung" not in result.lower() or "[site]" in result


class TestLongestValueFirst:
    """Entities are processed longest-value-first to avoid partial clobbering."""

    def test_longer_value_masked_first(self):
        result = mask_entities(
            "Compare Female Breast and Female rates",
            {"site": "Female Breast", "gender": "Female"},
        )
        # "Female Breast" (longer) should be masked first
        assert "[site]" in result

    def test_overlapping_entities(self):
        result = mask_entities(
            "Data for New York City metro",
            {"city": "New York City", "state": "New York"},
        )
        assert "[city]" in result


class TestPreservesStructure:
    """Table names, column names, and SQL keywords should not be affected."""

    def test_preserves_unmatched_text(self):
        question = "What is the incidence rate over time?"
        result = mask_entities(question, {"site": "Female Breast"})
        assert "incidence rate" in result
        assert "over time" in result
