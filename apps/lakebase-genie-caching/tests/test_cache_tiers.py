"""Tests for the three-tier cache system and SQL adaptation (node_answer_morph).

Covers:
  1. node_cache_search — Tier 1 (direct hit), Tier 2 (SQL adaptation), Tier 3 (miss)
  2. node_cache_search — A/B bypass, DB unavailable
  3. node_answer_morph — successful SQL adaptation end-to-end
  4. node_answer_morph — failure modes (bad params, validation fail, execution fail)
  5. node_answer_morph — no parameterized SQL, feature disabled
  6. Routing — all cache/morph routing paths
  7. Multi-turn — state resets between supervisor iterations

All external services (LLM, DBSQL, cache store) are mocked.
"""

import json
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.config import config
from backend.models import CacheEntry, CacheSearchResult, CacheStatus
from backend.services.graph import (
    node_cache_search,
    node_answer_morph,
    route_cache,
    route_answer_morph,
    route_cache_fallback,
    _substitute_params,
)


# ============================================================================
# Fixtures
# ============================================================================

NOW = datetime(2025, 6, 1, tzinfo=timezone.utc)
SPACE_ID = list(config.genie.spaces)[0].space_id if config.genie.spaces else "test-space"


def _make_entry(
    *,
    query="What are the 5 rarest cancers?",
    sql="SELECT * FROM cancers ORDER BY incidence LIMIT 5",
    parameterized_sql=None,
    parameters=None,
    space_id=None,
):
    """Build a CacheEntry.

    The cache stores SQL only -- there is no `result` or `cached_answer` field
    any more, because nothing is replayed from storage.
    """
    return CacheEntry(
        id="entry-1",
        query_text=query,
        query_normalized=query.lower(),
        cached_sql=sql,
        genie_space_id=space_id or SPACE_ID,
        hit_count=3,
        created_at=NOW,
        updated_at=NOW,
        record_type="trace",
        parameterized_sql=parameterized_sql,
        parameters=parameters,
    )


def _base_state(**overrides):
    """Minimal state dict for node_cache_search / node_answer_morph."""
    state = {
        "question": "What are the 10 rarest cancers?",
        "rewritten": "What are the 10 rarest cancers?",
        "current_task": "What are the 10 rarest cancers?",
        "current_space_id": SPACE_ID,
        "user_id": "test-user",
        "events": [],
        "completed_results": [],
        "bypass_cache": False,
        "cache_result": None,
        "cache_hit": False,
        "answer_morph": False,
        "similarity_score": None,
        "conversation_history": [],
        "start_time": time.time(),
    }
    state.update(overrides)
    return state


# ============================================================================
# 1. node_cache_search — Tier routing
# ============================================================================


class TestCacheSearchTier1DirectHit:
    """Tier 1: similarity >= 0.90 → cache_hit=True, answer_morph=False."""

    @pytest.mark.asyncio
    async def test_high_similarity_sets_cache_hit(self):
        entry = _make_entry()
        result = CacheSearchResult(entry=entry, similarity_score=0.95)
        with (
            patch("backend.services.graph._dual_cache_search", new_callable=AsyncMock, return_value=result),
            patch("backend.services.db.db_available", return_value=True),
        ):
            state = _base_state()
            out = await node_cache_search(state)
            assert out["cache_hit"] is True
            assert out["answer_morph"] is False
            assert out["cache_result"] is not None
            assert out["cache_result"]["cached_sql"] == entry.cached_sql

    @pytest.mark.asyncio
    async def test_exact_threshold_is_hit(self):
        entry = _make_entry()
        result = CacheSearchResult(entry=entry, similarity_score=0.90)
        with (
            patch("backend.services.graph._dual_cache_search", new_callable=AsyncMock, return_value=result),
            patch("backend.services.db.db_available", return_value=True),
        ):
            out = await node_cache_search(_base_state())
            assert out["cache_hit"] is True


class TestCacheSearchTier2SqlAdaptation:
    """Tier 2: 0.75 <= similarity < 0.90 + parameterized_sql → answer_morph=True."""

    @pytest.mark.asyncio
    async def test_with_parameterized_sql_sets_answer_morph(self):
        entry = _make_entry(
            parameterized_sql="SELECT * FROM cancers ORDER BY incidence LIMIT :limit_val",
            parameters={"limit_val": 5},
        )
        result = CacheSearchResult(entry=entry, similarity_score=0.85)
        with (
            patch("backend.services.graph._dual_cache_search", new_callable=AsyncMock, return_value=result),
            patch("backend.services.db.db_available", return_value=True),
        ):
            out = await node_cache_search(_base_state())
            assert out["cache_hit"] is False
            assert out["answer_morph"] is True
            assert out["cache_result"]["parameterized_sql"] is not None

    @pytest.mark.asyncio
    async def test_without_parameterized_sql_is_miss(self):
        """0.85 similarity but no SQL template → miss.

        There is no text-morph fallback: the cache stores SQL only, so an entry
        without a parameterized template has nothing to adapt.
        """
        entry = _make_entry()
        result = CacheSearchResult(entry=entry, similarity_score=0.85)
        with (
            patch("backend.services.graph._dual_cache_search", new_callable=AsyncMock, return_value=result),
            patch("backend.services.db.db_available", return_value=True),
        ):
            out = await node_cache_search(_base_state())
            assert out["cache_hit"] is False
            assert out["answer_morph"] is False

    @pytest.mark.asyncio
    async def test_without_sql_or_answer_is_miss(self):
        """No parameterized SQL at 0.85 → miss (no text fallback exists)."""
        entry = _make_entry()
        result = CacheSearchResult(entry=entry, similarity_score=0.85)
        with (
            patch("backend.services.graph._dual_cache_search", new_callable=AsyncMock, return_value=result),
            patch("backend.services.db.db_available", return_value=True),
        ):
            out = await node_cache_search(_base_state())
            assert out["cache_hit"] is False
            assert out["answer_morph"] is False

    @pytest.mark.asyncio
    async def test_at_exact_morph_threshold(self):
        entry = _make_entry(
            parameterized_sql="SELECT * FROM t LIMIT :n",
            parameters={"n": 5},
        )
        result = CacheSearchResult(entry=entry, similarity_score=0.75)
        with (
            patch("backend.services.graph._dual_cache_search", new_callable=AsyncMock, return_value=result),
            patch("backend.services.db.db_available", return_value=True),
        ):
            out = await node_cache_search(_base_state())
            assert out["answer_morph"] is True


class TestCacheSearchTier3Miss:
    """Tier 3: similarity < 0.75 → miss."""

    @pytest.mark.asyncio
    async def test_low_similarity_is_miss(self):
        entry = _make_entry(
            parameterized_sql="SELECT * FROM t LIMIT :n",
            parameters={"n": 5},
        )
        result = CacheSearchResult(entry=entry, similarity_score=0.60)
        with (
            patch("backend.services.graph._dual_cache_search", new_callable=AsyncMock, return_value=result),
            patch("backend.services.db.db_available", return_value=True),
        ):
            out = await node_cache_search(_base_state())
            assert out["cache_hit"] is False
            assert out["answer_morph"] is False

    @pytest.mark.asyncio
    async def test_no_cache_match_is_miss(self):
        with (
            patch("backend.services.graph._dual_cache_search", new_callable=AsyncMock, return_value=None),
            patch("backend.services.db.db_available", return_value=True),
        ):
            out = await node_cache_search(_base_state())
            assert out["cache_hit"] is False
            assert out["answer_morph"] is False
            assert out["cache_result"] is None


# ============================================================================
# 2. node_cache_search — A/B bypass and DB unavailable
# ============================================================================


class TestCacheSearchBypass:

    @pytest.mark.asyncio
    async def test_ab_bypass_skips_cache(self):
        """bypass_cache=True should skip cache entirely → miss."""
        state = _base_state(bypass_cache=True)
        out = await node_cache_search(state)
        assert out["cache_hit"] is False
        assert out["answer_morph"] is False
        assert out["cache_result"] is None

    @pytest.mark.asyncio
    async def test_db_unavailable_skips_cache(self):
        with patch("backend.services.db.db_available", return_value=False):
            out = await node_cache_search(_base_state())
            assert out["cache_hit"] is False
            assert out["cache_result"] is None

    @pytest.mark.asyncio
    async def test_cache_search_exception_is_miss(self):
        with (
            patch("backend.services.graph._dual_cache_search", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
            patch("backend.services.db.db_available", return_value=True),
        ):
            out = await node_cache_search(_base_state())
            assert out["cache_hit"] is False
            assert out["cache_result"] is None


# ============================================================================
# 3. node_answer_morph — successful SQL adaptation
# ============================================================================


class TestAnswerMorphSuccess:
    """Full happy path: extract params → substitute → validate → execute → summarize."""

    @pytest.mark.asyncio
    async def test_sql_adaptation_returns_tabular_data(self):
        cache_dict = {
            "entry_id": "entry-1",
            "cached_sql": "SELECT * FROM cancers LIMIT 5",
            "cached_question": "What are the 5 rarest cancers?",
            "cached_answer": None,
            "similarity": 0.85,
            "record_type": "trace",
            "result": "SELECT * FROM cancers LIMIT 5",
            "parameterized_sql": "SELECT * FROM cancers ORDER BY incidence LIMIT :limit_val",
            "parameters": {"limit_val": 5},
        }
        state = _base_state(
            cache_result=cache_dict,
            answer_morph=True,
            question="What are the 10 rarest cancers?",
            current_task="What are the 10 rarest cancers?",
        )

        mock_columns = ["cancer_type", "incidence"]
        mock_data = [["Mesothelioma", 3200], ["Cholangiocarcinoma", 8000]]

        with (
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value='{"limit_val": 10}'),
            # Tier 2 now validates the adapted SQL before executing it; this test
            # covers the adaptation path, so assume validation passes.
            patch("backend.services.graph._validate_sql", new_callable=AsyncMock, return_value=True),
            patch("backend.services.graph.execute_cached_sql", new_callable=AsyncMock, return_value=(mock_columns, mock_data, 2)),
            patch("backend.services.graph._summarize_results", new_callable=AsyncMock, return_value="The 10 rarest cancers are..."),
            patch.object(config.cache, "populate_params_on_query", True),
            patch("backend.services.graph.cache_store") as mock_cs,
        ):
            mock_cs.increment_hit = AsyncMock()
            mock_cs.update_cached_answer = AsyncMock()

            out = await node_answer_morph(state)

            assert out["cache_status"] == CacheStatus.HIT.value
            assert len(out["completed_results"]) == 1

            sub = out["completed_results"][0]
            assert sub["cache_hit"] is True
            assert sub["source"] == "sql_adaptation"
            assert sub["columns"] == mock_columns
            assert sub["data"] == mock_data
            assert sub["row_count"] == 2
            assert "LIMIT 10" in sub["sql"]

    @pytest.mark.asyncio
    async def test_empty_results_calls_empty_summarizer(self):
        cache_dict = {
            "entry_id": "entry-1",
            "cached_sql": "SELECT * FROM t LIMIT 5",
            "cached_question": "rare cancers",
            "cached_answer": None,
            "similarity": 0.80,
            "record_type": "trace",
            "result": "SELECT * FROM t LIMIT 5",
            "parameterized_sql": "SELECT * FROM t WHERE disease = :disease",
            "parameters": {"disease": "cholangiocarcinoma"},
        }
        state = _base_state(cache_result=cache_dict, answer_morph=True)

        with (
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value='{"disease": "mesothelioma"}'),
            # Tier 2 now validates the adapted SQL first; this test covers the
            # empty-result path, so assume validation passes.
            patch("backend.services.graph._validate_sql", new_callable=AsyncMock, return_value=True),
            patch("backend.services.graph.execute_cached_sql", new_callable=AsyncMock, return_value=(["col"], [], 0)),
            patch("backend.services.graph._summarize_empty_results", new_callable=AsyncMock, return_value="No results found.") as mock_empty,
            patch("backend.services.graph._summarize_results", new_callable=AsyncMock) as mock_summary,
            patch.object(config.cache, "populate_params_on_query", True),
            patch("backend.services.graph.cache_store") as mock_cs,
        ):
            mock_cs.increment_hit = AsyncMock()
            mock_cs.update_cached_answer = AsyncMock()

            out = await node_answer_morph(state)

            mock_empty.assert_called_once()
            mock_summary.assert_not_called()
            assert out["completed_results"][0]["row_count"] == 0


# ============================================================================
# 4. node_answer_morph — failure modes
# ============================================================================


class TestAnswerMorphFailures:

    @pytest.mark.asyncio
    async def test_no_cache_result_returns_miss(self):
        state = _base_state(cache_result=None)
        out = await node_answer_morph(state)
        assert out["cache_hit"] is False
        assert out["answer_morph"] is False

    @pytest.mark.asyncio
    async def test_no_parameterized_sql_returns_miss(self):
        cache_dict = {
            "entry_id": "entry-1",
            "cached_sql": "SELECT 1",
            "cached_question": "test",
            "cached_answer": "answer text",
            "similarity": 0.85,
            "record_type": "trace",
            "result": "SELECT 1",
            "parameterized_sql": None,
            "parameters": None,
        }
        state = _base_state(cache_result=cache_dict, answer_morph=True)
        with patch.object(config.cache, "populate_params_on_query", True):
            out = await node_answer_morph(state)
            assert out["cache_status"] == CacheStatus.MISS.value
            assert out["cache_hit"] is False

    @pytest.mark.asyncio
    async def test_feature_disabled_returns_miss(self):
        cache_dict = {
            "entry_id": "entry-1",
            "cached_sql": "SELECT 1",
            "cached_question": "test",
            "cached_answer": None,
            "similarity": 0.85,
            "record_type": "trace",
            "result": "SELECT 1",
            "parameterized_sql": "SELECT * FROM t LIMIT :n",
            "parameters": {"n": 5},
        }
        state = _base_state(cache_result=cache_dict, answer_morph=True)
        with patch.object(config.cache, "populate_params_on_query", False):
            out = await node_answer_morph(state)
            assert out["cache_status"] == CacheStatus.MISS.value

    @pytest.mark.asyncio
    async def test_llm_returns_invalid_json_falls_to_genie(self):
        cache_dict = {
            "entry_id": "entry-1",
            "cached_sql": "SELECT 1",
            "cached_question": "test",
            "cached_answer": None,
            "similarity": 0.85,
            "record_type": "trace",
            "result": "SELECT 1",
            "parameterized_sql": "SELECT * FROM t LIMIT :n",
            "parameters": {"n": 5},
        }
        state = _base_state(cache_result=cache_dict, answer_morph=True)

        with (
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value="NOT VALID JSON"),
            patch.object(config.cache, "populate_params_on_query", True),
        ):
            out = await node_answer_morph(state)
            assert out["cache_status"] == CacheStatus.MISS.value
            assert out["cache_hit"] is False

    @pytest.mark.asyncio
    async def test_llm_returns_empty_dict_falls_to_genie(self):
        cache_dict = {
            "entry_id": "entry-1",
            "cached_sql": "SELECT 1",
            "cached_question": "test",
            "cached_answer": None,
            "similarity": 0.85,
            "record_type": "trace",
            "result": "SELECT 1",
            "parameterized_sql": "SELECT * FROM t LIMIT :n",
            "parameters": {"n": 5},
        }
        state = _base_state(cache_result=cache_dict, answer_morph=True)

        with (
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value="{}"),
            patch.object(config.cache, "populate_params_on_query", True),
        ):
            out = await node_answer_morph(state)
            assert out["cache_status"] == CacheStatus.MISS.value

    @pytest.mark.asyncio
    async def test_sql_execution_failure_falls_to_genie(self):
        cache_dict = {
            "entry_id": "entry-1",
            "cached_sql": "SELECT 1",
            "cached_question": "test",
            "cached_answer": None,
            "similarity": 0.85,
            "record_type": "trace",
            "result": "SELECT 1",
            "parameterized_sql": "SELECT * FROM t LIMIT :n",
            "parameters": {"n": 5},
        }
        state = _base_state(cache_result=cache_dict, answer_morph=True)

        with (
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value='{"n": 10}'),
            patch("backend.services.graph.execute_cached_sql", new_callable=AsyncMock, side_effect=RuntimeError("warehouse error")),
            patch.object(config.cache, "populate_params_on_query", True),
        ):
            out = await node_answer_morph(state)
            assert out["cache_status"] == CacheStatus.MISS.value

    @pytest.mark.asyncio
    async def test_unresolved_placeholders_fall_to_genie(self):
        """If LLM returns None for a param, and original is also None, placeholder stays."""
        cache_dict = {
            "entry_id": "entry-1",
            "cached_sql": "SELECT 1",
            "cached_question": "test",
            "cached_answer": None,
            "similarity": 0.85,
            "record_type": "trace",
            "result": "SELECT 1",
            "parameterized_sql": "SELECT * FROM t WHERE x = :x AND y = :y",
            "parameters": {"x": "a", "y": None},
        }
        state = _base_state(cache_result=cache_dict, answer_morph=True)

        with (
            patch("asyncio.to_thread", new_callable=AsyncMock, return_value='{"x": "b", "y": null}'),
            patch.object(config.cache, "populate_params_on_query", True),
        ):
            out = await node_answer_morph(state)
            assert out["cache_status"] == CacheStatus.MISS.value


# ============================================================================
# 5. Routing — cache tier routing and answer_morph routing
# ============================================================================


class TestCacheTierRouting:

    def test_tier1_hit_routes_to_populate_params(self):
        assert route_cache({"cache_hit": True, "answer_morph": False}) == "populate_params"

    def test_tier1_hit_takes_precedence_over_morph(self):
        assert route_cache({"cache_hit": True, "answer_morph": True}) == "populate_params"

    def test_tier2_sql_adaptation_routes_to_answer_morph(self):
        assert route_cache({"cache_hit": False, "answer_morph": True}) == "answer_morph"

    def test_tier3_miss_routes_to_genie(self):
        assert route_cache({"cache_hit": False, "answer_morph": False}) == "genie_dispatch"

    def test_sql_adaptation_success_routes_to_supervisor(self):
        assert route_answer_morph({"cache_status": CacheStatus.HIT.value}) == "supervisor"

    def test_sql_adaptation_failure_routes_to_genie(self):
        assert route_answer_morph({"cache_status": CacheStatus.MISS.value}) == "genie_dispatch"

    def test_execute_cached_success_routes_to_supervisor(self):
        assert route_cache_fallback({"cache_status": CacheStatus.HIT.value}) == "supervisor"

    def test_execute_cached_failure_routes_to_genie(self):
        assert route_cache_fallback({"cache_status": CacheStatus.MISS.value}) == "genie_dispatch"


# ============================================================================
# 6. Multi-turn — state resets between iterations
# ============================================================================


class TestMultiTurnStateReset:
    """The supervisor resets per-iteration cache state between sub-questions."""

    def test_state_flags_independent_per_iteration(self):
        iter1 = {"cache_hit": True, "answer_morph": False}
        assert route_cache(iter1) == "populate_params"

        iter2 = {"cache_hit": False, "answer_morph": True}
        assert route_cache(iter2) == "answer_morph"

        iter3 = {"cache_hit": False, "answer_morph": False}
        assert route_cache(iter3) == "genie_dispatch"

    @pytest.mark.asyncio
    async def test_ab_bypass_does_not_leak_across_iterations(self):
        """Each iteration should respect its own bypass_cache flag."""
        state_bypass = _base_state(bypass_cache=True)
        out1 = await node_cache_search(state_bypass)
        assert out1["cache_hit"] is False

        entry = _make_entry(
            parameterized_sql="SELECT 1 LIMIT :n",
            parameters={"n": 5},
        )
        result = CacheSearchResult(entry=entry, similarity_score=0.85)
        with (
            patch("backend.services.graph._dual_cache_search", new_callable=AsyncMock, return_value=result),
            patch("backend.services.db.db_available", return_value=True),
        ):
            state_normal = _base_state(bypass_cache=False)
            out2 = await node_cache_search(state_normal)
            assert out2["answer_morph"] is True


# ============================================================================
# 7. SQL substitution in adaptation context
# ============================================================================


class TestSqlSubstitutionForAdaptation:
    """Verify _substitute_params handles the patterns used in SQL adaptation."""

    def test_limit_substitution(self):
        sql = "SELECT * FROM cancers ORDER BY incidence LIMIT :limit_val"
        result = _substitute_params(sql, {"limit_val": 10})
        assert result == "SELECT * FROM cancers ORDER BY incidence LIMIT 10"

    def test_string_entity_substitution(self):
        sql = "SELECT * FROM t WHERE disease = :disease"
        result = _substitute_params(sql, {"disease": "lung cancer"})
        assert result == "SELECT * FROM t WHERE disease = 'lung cancer'"

    def test_multiple_params(self):
        sql = "SELECT * FROM t WHERE disease = :disease AND stage = :stage LIMIT :limit_val"
        result = _substitute_params(sql, {"disease": "breast cancer", "stage": "III", "limit_val": 20})
        assert "'breast cancer'" in result
        assert "'III'" in result
        assert "LIMIT 20" in result
        assert ":disease" not in result
        assert ":stage" not in result
        assert ":limit_val" not in result

    def test_ilike_pattern_in_quotes(self):
        sql = "SELECT * FROM t WHERE name ILIKE '%:disease%'"
        result = _substitute_params(sql, {"disease": "melanoma"})
        assert "'%melanoma%'" in result or "%melanoma%" in result

    def test_null_param_leaves_placeholder(self):
        sql = "SELECT * FROM t WHERE x = :x"
        result = _substitute_params(sql, {"x": None})
        assert ":x" in result


# ============================================================================
# 8. Cached answer is NOT used for routing decisions
# ============================================================================


class TestTier2Routing:
    """Tier 2 requires a parameterized SQL template; there is no text fallback."""

    @pytest.mark.asyncio
    async def test_parameterized_sql_triggers_adaptation(self):
        """0.85 similarity + parameterized_sql → SQL adaptation."""
        entry = _make_entry(
            parameterized_sql="SELECT * FROM t LIMIT :n",
            parameters={"n": 5},
        )
        result = CacheSearchResult(entry=entry, similarity_score=0.85)
        with (
            patch("backend.services.graph._dual_cache_search", new_callable=AsyncMock, return_value=result),
            patch("backend.services.db.db_available", return_value=True),
        ):
            out = await node_cache_search(_base_state())
            assert out["answer_morph"] is True
            assert route_cache(out) == "answer_morph"

    @pytest.mark.asyncio
    async def test_no_template_is_miss(self):
        """0.85 similarity without a template → miss, routed to Genie.

        Previously an entry with only a stored answer entered a text-morph path.
        The cache no longer stores answers, so there is nothing to morph.
        """
        entry = _make_entry()
        result = CacheSearchResult(entry=entry, similarity_score=0.85)
        with (
            patch("backend.services.graph._dual_cache_search", new_callable=AsyncMock, return_value=result),
            patch("backend.services.db.db_available", return_value=True),
        ):
            out = await node_cache_search(_base_state())
            assert out["answer_morph"] is False
            assert out["cache_hit"] is False
            assert route_cache(out) == "genie_dispatch"

class TestTier2ValidatesAdaptedSql:
    """Tier 2 SQL adaptation must validate, not just substitute parameters.

    Regression test for a wrong-answer bug found on the deployed app: asking for
    the "3 rarest cancers" matched a cached "3 most common cancers" template at
    0.835 similarity, extracted top_count=3, reused the template's DESC sort, and
    returned the most common cancers presented as the rarest.

    Parameter extraction cannot catch that class of mismatch, because sort
    direction is not a parameter.
    """

    @staticmethod
    def _cache_dict(similarity=0.835):
        return {
            "entry_id": "e-1",
            "cached_question": "What are the 3 most common cancers by incidence?",
            "cached_sql": "SELECT site FROM t ORDER BY rate DESC LIMIT 3",
            "parameterized_sql": "SELECT site FROM t ORDER BY rate DESC LIMIT :top_count",
            "parameters": {"top_count": 3},
            "similarity": similarity,
        }

    @staticmethod
    def _state(question):
        return {
            "question": question,
            "current_task": question,
            "start_time": 0.0,
            "events": [],
            "completed_results": [],
        }

    @pytest.mark.asyncio
    async def test_adaptation_is_rejected_when_validation_fails(self):
        """The wrong SQL must never reach the warehouse."""
        from backend.services.graph import _try_sql_adaptation

        question = "What are the 3 rarest cancers by incidence?"

        with (
            # Parameter extraction happens inline via asyncio.to_thread; stub the
            # LLM's raw JSON reply instead.
            patch("backend.services.graph.asyncio.to_thread", new_callable=AsyncMock,
                  return_value='{"top_count": 3}'),
            patch("backend.services.graph._validate_sql", new_callable=AsyncMock,
                  return_value=False) as validate,
            patch("backend.services.graph.execute_cached_sql", new_callable=AsyncMock) as execute,
        ):
            result = await _try_sql_adaptation(
                self._state(question), self._cache_dict(), question,
                "space-1", "Cancer Incidence",
            )

        validate.assert_awaited_once()
        execute.assert_not_awaited()
        assert result is None

    @pytest.mark.asyncio
    async def test_adaptation_proceeds_when_validation_passes(self):
        from backend.services.graph import _try_sql_adaptation

        question = "What are the top 5 cancers by incidence?"

        with (
            patch("backend.services.graph.asyncio.to_thread", new_callable=AsyncMock,
                  return_value='{"top_count": 5}'),
            patch("backend.services.graph._validate_sql", new_callable=AsyncMock,
                  return_value=True),
            patch("backend.services.graph.execute_cached_sql", new_callable=AsyncMock,
                  return_value=(["site"], [["a"], ["b"], ["c"], ["d"], ["e"]], 5)) as execute,
            patch("backend.services.graph._summarize_results", new_callable=AsyncMock,
                  return_value="Top 5 cancers are ..."),
            patch("backend.services.graph.cache_store") as store,
        ):
            store.increment_hit = AsyncMock()
            store.update_cached_answer = AsyncMock()
            result = await _try_sql_adaptation(
                self._state(question), self._cache_dict(similarity=0.91), question,
                "space-1", "Cancer Incidence",
            )

        execute.assert_awaited_once()
        assert result is not None
        assert "LIMIT 5" in execute.await_args.args[0]
