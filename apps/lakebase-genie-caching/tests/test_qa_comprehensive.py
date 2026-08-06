"""Comprehensive QA test suite for the Lakebase Genie Caching.

Covers:
  1. Unit tests — pure functions, data transformations, config validation
  2. Integration tests — service layer with mocked DB/embedding
  3. Functional tests — API endpoint behaviour via FastAPI TestClient
  4. Edge-case / boundary tests

All external services (Lakebase, embedding API, LLM endpoints) are mocked.
"""

import json
import re
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from backend.services.cache_store import mask_entities, _row_to_entry as cache_row_to_entry
from backend.services.memory_store import _row_to_entry as memory_row_to_entry
from backend.services.graph import (
    _substitute_params, _fix_inline_bullets,
    _tag, _elapsed, _add_event, _build_response,
    _GREETING_PATTERNS,
    MAX_CALLS_PER_SPACE,
    route_cache, route_supervisor, route_answer_morph,
    route_cache_fallback,
)
from backend.services.preprocessor import normalize_query, extract_key_terms
from backend.services.db import _convert_params
from agent_server.utils import extract_user_id, extract_session_id, extract_question


# ============================================================================
# 1. UNIT TESTS — Pure functions
# ============================================================================


class TestMaskEntitiesAdvanced:

    def test_regex_special_chars_in_value(self):
        assert "[lang]" in mask_entities("Show data for C++ developers", {"lang": "C++"})

    def test_parentheses_in_value(self):
        r = mask_entities("Show rates for Female (age-adjusted)", {"metric": "Female (age-adjusted)"})
        assert "[metric]" in r

    def test_boolean_entity(self):
        assert "[flag]" in mask_entities("Show True positives", {"flag": True})

    def test_float_entity(self):
        assert "[threshold]" in mask_entities("Show rates above 3.5 per 100k", {"threshold": 3.5})

    def test_multiple_occurrences_replaced(self):
        r = mask_entities("Compare Lung cancer in males vs Lung cancer in females", {"site": "Lung"})
        assert "Lung" not in r or "[site]" in r


class TestSubstituteParamsAdvanced:

    def test_empty_string_value(self):
        assert _substitute_params("WHERE n = :n", {"n": ""}) == "WHERE n = ''"

    def test_negative_number(self):
        assert _substitute_params("WHERE d > :d", {"d": -5}) == "WHERE d > -5"

    def test_many_params(self):
        params = {f"p{i}": f"v{i}" for i in range(15)}
        placeholders = " AND ".join(f"c{i} = :p{i}" for i in range(15))
        result = _substitute_params(f"SELECT * FROM t WHERE {placeholders}", params)
        for i in range(15):
            assert f"'v{i}'" in result


class TestNormalizeQueryEdgeCases:

    def test_tabs_and_newlines(self):
        r = normalize_query("revenue\tby\nquarter")
        assert "revenue" in r and "quarter" in r and "\t" not in r

    def test_numbers_only(self):
        r = normalize_query("12345 67890")
        assert "12345" in r and "67890" in r

    def test_very_long_query(self):
        r = normalize_query("revenue " * 500)
        assert len(r) > 0 and "  " not in r

    def test_key_terms_order_preserved(self):
        terms = extract_key_terms("total revenue clinical trials")
        assert terms.index("total") < terms.index("revenue") < terms.index("clinical")


class TestFixInlineBullets:

    def test_empty_string(self):
        assert _fix_inline_bullets("") == ""

    def test_mixed_text_and_bullets(self):
        r = _fix_inline_bullets("Results:\n• a • b • c")
        assert "Results:" in r
        for item in ("- a", "- b", "- c"):
            assert item in r

    def test_preserves_normal_text(self):
        assert _fix_inline_bullets("No bullets here") == "No bullets here"


class TestTagFunction:

    def test_truncates_at_250(self):
        assert len(_tag("x" * 300)) == 250

    def test_none_returns_empty(self):
        assert _tag(None) == ""

    def test_short_unchanged(self):
        assert _tag("hello") == "hello"


# ============================================================================
# 2. CONFIG TESTS
# ============================================================================


class TestConfigDefaults:
    def test_cache_threshold_ordering(self):
        from backend.config import CacheConfig
        c = CacheConfig()
        assert c.answer_morph_threshold < c.similarity_threshold

    def test_memory_config_ranges(self):
        from backend.config import MemoryConfig
        m = MemoryConfig()
        assert m.top_k > 0
        assert 0 < m.decay_rate < 1
        assert 0 < m.score_threshold < 1
        assert m.blocklist_threshold > m.similarity_threshold

    def test_embedding_dimensions(self):
        from backend.config import EmbeddingConfig
        assert EmbeddingConfig().dimensions == 1024

    def test_genie_spaces_is_list(self):
        from backend.config import config
        assert isinstance(config.genie.spaces, list)

    def test_llm_config_has_endpoints(self):
        from backend.config import LLMConfig
        c = LLMConfig()
        assert c.classifier_endpoint
        assert c.assistant_endpoint

    def test_trace_archive_full_table_name(self):
        from backend.config import TraceArchiveConfig
        t = TraceArchiveConfig(catalog="c", schema="s", table_name="t")
        assert t.full_table_name == "`c`.`s`.`t`"


# ============================================================================
# 3. MODEL VALIDATION TESTS
# ============================================================================


class TestModelValidation:
    def test_ask_request_missing_question(self):
        from backend.models import AskRequest
        with pytest.raises(ValidationError):
            AskRequest()

    def test_ask_request_defaults(self):
        from backend.models import AskRequest
        r = AskRequest(question="Q")
        assert r.user_id == "unknown" and r.session_id is None

    def test_feedback_rating_bounds(self):
        from backend.models import FeedbackRequest
        for v in (-1, 0, 1):
            FeedbackRequest(trace_id="t", rating=v)
        for v in (-2, 2, 10):
            with pytest.raises(ValidationError):
                FeedbackRequest(trace_id="t", rating=v)

    def test_cache_status_enum(self):
        from backend.models import CacheStatus
        assert CacheStatus("hit") == CacheStatus.HIT

    def test_record_type_enum(self):
        from backend.models import RecordType
        assert RecordType.FAQ == "faq" and RecordType.TRACE == "trace"

    def test_memory_type_includes_identity(self):
        from backend.models import MemoryType
        assert MemoryType.IDENTITY == "identity"

    def test_ask_response_round_trip(self):
        from backend.models import AskResponse, CacheStatus
        r = AskResponse(question="q", cache_status="hit", latency_ms=50, trace_id="t", session_id="s")
        assert AskResponse(**r.model_dump()).cache_status == CacheStatus.HIT

    def test_cache_entry_defaults(self):
        from backend.models import CacheEntry
        now = datetime.now(timezone.utc)
        e = CacheEntry(id="e", query_text="q", query_normalized="q",
                       cached_sql="SQL", genie_space_id="s", created_at=now, updated_at=now)
        assert e.hit_count == 0 and e.record_type == "trace" and e.pinned is False

    def test_session_defaults(self):
        from backend.models import Session
        now = datetime.now(timezone.utc)
        s = Session(session_id="s", user_id="u", created_at=now, updated_at=now)
        assert s.title is None and s.genie_conversation_ids == {}

    def test_memory_entry_defaults(self):
        from backend.models import MemoryEntry
        now = datetime.now(timezone.utc)
        m = MemoryEntry(id="m", user_id="u", content="x", last_seen_at=now, created_at=now)
        assert m.score == 1.0 and m.recurrence_count == 1 and m.archived_at is None


# ============================================================================
# 4. ROUTING LOGIC TESTS
# ============================================================================


class TestRoutingLogic:

    def test_hit_routes_populate(self):
        assert route_cache({"cache_hit": True, "answer_morph": False}) == "populate_params"

    def test_hit_takes_precedence(self):
        assert route_cache({"cache_hit": True, "answer_morph": True}) == "populate_params"

    def test_sql_adaptation_routes_to_answer_morph(self):
        state = {"cache_hit": False, "answer_morph": True}
        assert route_cache(state) == "answer_morph"

    def test_miss_routes_genie(self):
        assert route_cache({"cache_hit": False, "answer_morph": False}) == "genie_dispatch"

    def test_empty_plan_routes_end(self):
        from langgraph.graph import END
        assert route_supervisor({"supervisor_plan": []}) == END

    def test_none_plan_routes_end(self):
        from langgraph.graph import END
        assert route_supervisor({"supervisor_plan": None}) == END

    def test_data_first_step(self):
        state = {"supervisor_plan": [{"agent": "s1", "task": "q"}], "intent": "data_query", "current_step": 0}
        assert route_supervisor(state) == "cache_search"

    def test_single_space_done(self):
        from langgraph.graph import END
        state = {"supervisor_plan": [{"agent": "s1", "task": "q"}], "intent": "data_query", "current_step": 1}
        assert route_supervisor(state) == END

    def test_multi_space_done_routes_summarizer(self):
        state = {"supervisor_plan": [{"agent": "a"}, {"agent": "b"}], "intent": "data_query", "current_step": 2}
        assert route_supervisor(state) == "summarizer"

    def test_sql_adaptation_success(self):
        assert route_answer_morph({"cache_status": "hit"}) == "supervisor"

    def test_sql_adaptation_fail(self):
        assert route_answer_morph({"cache_status": "miss"}) == "genie_dispatch"

    def test_fallback_hit(self):
        assert route_cache_fallback({"cache_status": "hit"}) == "supervisor"

    def test_fallback_miss(self):
        assert route_cache_fallback({"cache_status": "miss"}) == "genie_dispatch"

class TestGreetingPatterns:

    @pytest.mark.parametrize("g", [
        "hi", "Hi!", "hello", "hey", "thanks", "thank you", "ok",
        "good morning", "bye", "yes", "no", "help", "who are you",
        "how are you", "awesome", "got it", "sup", "yo",
    ])
    def test_greetings_match(self, g):
        assert _GREETING_PATTERNS.match(g.strip())

    @pytest.mark.parametrize("q", [
        "What is the revenue?", "Show me cancer rates",
        "top 5 trials", "hello world how is revenue",
    ])
    def test_data_questions_do_not_match(self, q):
        assert not _GREETING_PATTERNS.match(q.strip())


# ============================================================================
# 5. DB UTILITY TESTS
# ============================================================================


class TestConvertParamsExtra:

    def test_timestamp_colon_preserved(self):
        sql, _ = _convert_params("SELECT '2024-01-01T00:00:00'::timestamptz", {})
        assert "00:00:00" in sql

    def test_param_at_end(self):
        sql, _ = _convert_params("WHERE id = :id", {"id": 1})
        assert sql.endswith("%(id)s")


# ============================================================================
# 6. ROW-TO-ENTRY CONVERSION TESTS
# ============================================================================


def _cache_base_row(**overrides):
    now = datetime.now(timezone.utc)
    row = {"id": "e1", "query_text": "q", "query_normalized": "q",
           "cached_sql": "SQL", "genie_space_id": "s1", "hit_count": 0,
           "created_at": now, "updated_at": now, "record_type": "trace",
           "result": None, "parameterized_sql": None, "parameters": None, "metadata": None}
    row.update(overrides)
    return row


class TestCacheRowToEntry:

    def test_pinned_true(self):
        assert cache_row_to_entry(_cache_base_row(pinned=True)).pinned is True

    def test_pinned_missing_defaults_false(self):
        row = {"id": "x", "query_text": "q", "query_normalized": "q",
               "cached_sql": "SQL", "created_at": datetime.now(timezone.utc)}
        assert cache_row_to_entry(row).pinned is False

    def test_json_string_parameters(self):
        assert cache_row_to_entry(_cache_base_row(parameters='{"k":"v"}')).parameters == {"k": "v"}

    def test_invalid_json_parameters(self):
        assert cache_row_to_entry(_cache_base_row(parameters="bad")).parameters is None

    def test_updated_at_fallback(self):
        now = datetime.now(timezone.utc)
        assert cache_row_to_entry(_cache_base_row(updated_at=None, created_at=now)).updated_at == now


class TestMemoryRowToEntry:

    def test_basic(self):
        now = datetime.now(timezone.utc)
        e = memory_row_to_entry({"id": "m", "user_id": "u", "content": "c",
                                  "memory_type": "correction", "score": 2.0,
                                  "recurrence_count": 3, "last_seen_at": now,
                                  "created_at": now, "archived_at": None})
        assert e.memory_type.value == "correction" and e.archived_at is None

    def test_missing_type_defaults_preference(self):
        from backend.models import MemoryType
        now = datetime.now(timezone.utc)
        e = memory_row_to_entry({"id": "m", "user_id": "u", "content": "c",
                                  "score": 1.0, "recurrence_count": 1,
                                  "last_seen_at": now, "created_at": now})
        assert e.memory_type == MemoryType.PREFERENCE


# ============================================================================
# 7. CACHE STORE SERVICE TESTS (mocked DB + embedding)
# ============================================================================


class TestCacheStoreSearch:
    @pytest.mark.asyncio
    async def test_returns_none_on_empty(self):
        from backend.services.cache_store import LakebaseCacheStore
        with (patch("backend.services.cache_store.execute_raw", new_callable=AsyncMock) as db,
              patch("backend.services.cache_store.get_embedding", new_callable=AsyncMock) as emb):
            emb.return_value = [0.1] * 1024; db.return_value = []
            assert await LakebaseCacheStore().search("q") is None

    @pytest.mark.asyncio
    async def test_returns_best_match(self):
        from backend.services.cache_store import LakebaseCacheStore
        now = datetime.now(timezone.utc)
        with (patch("backend.services.cache_store.execute_raw", new_callable=AsyncMock) as db,
              patch("backend.services.cache_store.get_embedding", new_callable=AsyncMock) as emb):
            emb.return_value = [0.1] * 1024
            db.return_value = [{
                "id": "e1", "query_text": "q", "query_normalized": "q",
                "cached_sql": "SQL", "genie_space_id": "s", "hit_count": 5,
                "created_at": now, "updated_at": now, "record_type": "trace",
                "result": "SQL", "parameterized_sql": None,
                "parameters": None, "metadata": None, "similarity": 0.95,
            }]
            r = await LakebaseCacheStore().search("q")
            assert r is not None and r.similarity_score == 0.95


class TestCacheStoreOps:
    @pytest.mark.asyncio
    async def test_count(self):
        from backend.services.cache_store import LakebaseCacheStore
        with patch("backend.services.cache_store.execute_raw", new_callable=AsyncMock) as db:
            db.return_value = [{"cnt": 42}]
            assert await LakebaseCacheStore().count() == 42

    @pytest.mark.asyncio
    async def test_set_pinned_found(self):
        from backend.services.cache_store import LakebaseCacheStore
        with patch("backend.services.cache_store.execute_raw", new_callable=AsyncMock) as db:
            db.return_value = [{"id": "e1"}]
            assert await LakebaseCacheStore().set_pinned("e1", True) is True

    @pytest.mark.asyncio
    async def test_set_pinned_not_found(self):
        from backend.services.cache_store import LakebaseCacheStore
        with patch("backend.services.cache_store.execute_raw", new_callable=AsyncMock) as db:
            db.return_value = []
            assert await LakebaseCacheStore().set_pinned("x", True) is False

    @pytest.mark.asyncio
    async def test_is_promoted_true(self):
        from backend.services.cache_store import LakebaseCacheStore
        with patch("backend.services.cache_store.execute_raw", new_callable=AsyncMock) as db:
            db.return_value = [{"1": 1}]
            assert await LakebaseCacheStore().is_promoted("t1") is True

    @pytest.mark.asyncio
    async def test_is_promoted_false(self):
        from backend.services.cache_store import LakebaseCacheStore
        with patch("backend.services.cache_store.execute_raw", new_callable=AsyncMock) as db:
            db.return_value = []
            assert await LakebaseCacheStore().is_promoted("t2") is False

    @pytest.mark.asyncio
    async def test_clear_all(self):
        from backend.services.cache_store import LakebaseCacheStore
        with patch("backend.services.cache_store.execute_raw", new_callable=AsyncMock) as db:
            db.return_value = [{"id": "a"}, {"id": "b"}]
            assert await LakebaseCacheStore().clear_all() == 2

    @pytest.mark.asyncio
    async def test_evict_returns_stats(self):
        from backend.services.cache_store import LakebaseCacheStore
        with patch("backend.services.cache_store.execute_raw", new_callable=AsyncMock) as db:
            # TTL eviction, age eviction, stale eviction, count query (for overflow check)
            db.side_effect = [[], [{"id": "1"}], [], [{"cnt": 5}]]
            stats = await LakebaseCacheStore().evict()
            assert all(k in stats for k in ("ttl", "age", "stale", "overflow"))

    @pytest.mark.asyncio
    async def test_add_basic(self):
        from backend.services.cache_store import LakebaseCacheStore
        with (patch("backend.services.cache_store.execute_raw", new_callable=AsyncMock) as db,
              patch("backend.services.cache_store.get_embedding", new_callable=AsyncMock) as emb):
            emb.return_value = [0.1] * 1024; db.return_value = []
            e = await LakebaseCacheStore().add("q", "SQL", "s")
            assert e.query_text == "q" and e.record_type == "trace"

    @pytest.mark.asyncio
    async def test_add_with_params_calls_embedding_twice(self):
        from backend.services.cache_store import LakebaseCacheStore
        with (patch("backend.services.cache_store.execute_raw", new_callable=AsyncMock) as db,
              patch("backend.services.cache_store.get_embedding", new_callable=AsyncMock) as emb):
            emb.return_value = [0.1] * 1024; db.return_value = []
            await LakebaseCacheStore().add("revenue for Acme", "SQL", "s",
                                           parameterized_sql="SQL WHERE c = :c",
                                           parameters={"c": "Acme"})
            assert emb.call_count == 2

    @pytest.mark.asyncio
    async def test_add_faq_sets_pinned_and_type(self):
        from backend.services.cache_store import LakebaseCacheStore
        with (patch("backend.services.cache_store.execute_raw", new_callable=AsyncMock) as db,
              patch("backend.services.cache_store.get_embedding", new_callable=AsyncMock) as emb):
            emb.return_value = [0.1] * 1024; db.return_value = []
            e = await LakebaseCacheStore().add_faq("Q?", "SQL", "s")
            assert e.record_type == "faq" and e.pinned is True


# ============================================================================
# 8. MEMORY STORE SERVICE TESTS
# ============================================================================


class TestMemoryStoreOps:
    @pytest.mark.asyncio
    async def test_add_new(self):
        from backend.services.memory_store import UserMemoryStore
        mock_exec = AsyncMock(side_effect=[[], [], None])
        with (patch("backend.services.memory_store.execute_raw", mock_exec),
              patch("backend.services.memory_store.get_embedding", AsyncMock(return_value=[0.1] * 3))):
            e = await UserMemoryStore().add_or_update("u", "Prefers SQL")
        assert e is not None and e.score == 1.0

    @pytest.mark.asyncio
    async def test_boost_existing(self):
        from backend.services.memory_store import UserMemoryStore
        now = datetime.now(timezone.utc)
        mock_exec = AsyncMock(side_effect=[
            [],
            [{"id": "x", "score": 1.5, "recurrence_count": 2,
              "created_at": now, "memory_type": "preference", "similarity": 0.9}],
            None,
        ])
        with (patch("backend.services.memory_store.execute_raw", mock_exec),
              patch("backend.services.memory_store.get_embedding", AsyncMock(return_value=[0.1] * 3))):
            e = await UserMemoryStore().add_or_update("u", "Prefers SQL")
        assert e.score == 1.6 and e.recurrence_count == 3

    @pytest.mark.asyncio
    async def test_blocked_returns_none(self):
        from backend.services.memory_store import UserMemoryStore
        with (patch("backend.services.memory_store.execute_raw", AsyncMock(return_value=[{"1": 1}])),
              patch("backend.services.memory_store.get_embedding", AsyncMock(return_value=[0.1] * 3))):
            assert await UserMemoryStore().add_or_update("u", "x") is None

    @pytest.mark.asyncio
    async def test_score_capped_at_five(self):
        from backend.services.memory_store import UserMemoryStore
        now = datetime.now(timezone.utc)
        mock_exec = AsyncMock(side_effect=[
            [],
            [{"id": "x", "score": 4.95, "recurrence_count": 50,
              "created_at": now, "memory_type": "preference", "similarity": 0.99}],
            None,
        ])
        with (patch("backend.services.memory_store.execute_raw", mock_exec),
              patch("backend.services.memory_store.get_embedding", AsyncMock(return_value=[0.1] * 3))):
            e = await UserMemoryStore().add_or_update("u", "x")
        assert e.score == 5.0

    @pytest.mark.asyncio
    async def test_soft_delete(self):
        from backend.services.memory_store import UserMemoryStore
        mock_exec = AsyncMock(side_effect=[
            [{"user_id": "u", "content": "t", "embedding": "[0.1,0.2]"}], None, None])
        with patch("backend.services.memory_store.execute_raw", mock_exec):
            assert await UserMemoryStore().delete("e1") is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self):
        from backend.services.memory_store import UserMemoryStore
        with patch("backend.services.memory_store.execute_raw", AsyncMock(return_value=[])):
            assert await UserMemoryStore().delete("x") is False

    @pytest.mark.asyncio
    async def test_restore(self):
        from backend.services.memory_store import UserMemoryStore
        mock_exec = AsyncMock(side_effect=[[{"id": "e"}], [{"content": "c"}], None])
        with patch("backend.services.memory_store.execute_raw", mock_exec):
            assert await UserMemoryStore().restore("e") is True

    @pytest.mark.asyncio
    async def test_restore_not_archived(self):
        from backend.services.memory_store import UserMemoryStore
        with patch("backend.services.memory_store.execute_raw", AsyncMock(return_value=[])):
            assert await UserMemoryStore().restore("e") is False

    @pytest.mark.asyncio
    async def test_apply_decay(self):
        from backend.services.memory_store import UserMemoryStore
        with patch("backend.services.memory_store.execute_raw",
                    AsyncMock(return_value=[{"id": "a"}, {"id": "b"}])):
            assert await UserMemoryStore().apply_decay("u") == 2


# ============================================================================
# 9. AGENT UTILS TESTS
# ============================================================================


class TestAgentUtils:

    def test_user_from_context(self):
        r = MagicMock(); r.context.user_id = "me@corp"; r.custom_inputs = None
        assert extract_user_id(r) == "me@corp"

    def test_user_from_custom_inputs(self):
        r = MagicMock(); r.context = None; r.custom_inputs = {"user_id": "cu"}
        assert extract_user_id(r) == "cu"

    def test_user_fallback_anonymous(self):
        r = MagicMock(); r.context = None; r.custom_inputs = None
        assert extract_user_id(r) == "anonymous"

    def test_session_id_present(self):
        r = MagicMock(); r.custom_inputs = {"session_id": "s1"}
        assert extract_session_id(r) == "s1"

    def test_session_id_missing(self):
        r = MagicMock(); r.custom_inputs = {}
        assert extract_session_id(r) is None

    def test_question_from_input(self):
        r = MagicMock()
        r.input = [MagicMock(model_dump=lambda: {"role": "user", "content": "Hello?"})]
        assert extract_question(r) == "Hello?"

    def test_question_empty_input(self):
        r = MagicMock(); r.input = []
        assert extract_question(r) == ""

    def test_question_none_input(self):
        r = MagicMock(); r.input = None
        assert extract_question(r) == ""

    def test_question_last_user_message(self):
        r = MagicMock()
        r.input = [
            MagicMock(model_dump=lambda: {"role": "user", "content": "First"}),
            MagicMock(model_dump=lambda: {"role": "assistant", "content": "Reply"}),
            MagicMock(model_dump=lambda: {"role": "user", "content": "Second"}),
        ]
        assert extract_question(r) == "Second"

    def test_question_content_list(self):
        r = MagicMock()
        r.input = [MagicMock(model_dump=lambda: {
            "role": "user", "content": [{"type": "input_text", "text": "Complex"}],
        })]
        assert extract_question(r) == "Complex"


# ============================================================================
# 10. API ROUTE FUNCTIONAL TESTS
# ============================================================================


def _make_app():
    from fastapi import FastAPI
    from backend.routers.cache import router as cr
    from backend.routers.memory import router as mr
    from backend.routers.feedback import router as fr
    app = FastAPI()
    app.include_router(cr); app.include_router(mr); app.include_router(fr)
    return app


_app = _make_app()


class TestCacheAPI:
    def test_list_entries(self):
        from fastapi.testclient import TestClient
        from backend.models import CacheEntry
        now = datetime.now(timezone.utc)
        with patch("backend.routers.cache.cache_store") as cs:
            cs.list_entries = AsyncMock(return_value=[CacheEntry(
                id="e", query_text="q", query_normalized="q", cached_sql="SQL",
                genie_space_id="s", created_at=now, updated_at=now)])
            cs.count = AsyncMock(return_value=1)
            d = TestClient(_app).get("/api/cache/entries").json()
        assert d["total"] == 1 and len(d["entries"]) == 1

    def test_delete_entry(self):
        from fastapi.testclient import TestClient
        with patch("backend.routers.cache.cache_store") as cs:
            cs.delete = AsyncMock(return_value=True)
            d = TestClient(_app).delete("/api/cache/entries/e1").json()
        assert d == {"deleted": True, "id": "e1"}

    def test_clear_all(self):
        from fastapi.testclient import TestClient
        with patch("backend.routers.cache.cache_store") as cs:
            cs.clear_all = AsyncMock(return_value=10)
            d = TestClient(_app).delete("/api/cache/entries").json()
        assert d["cleared"] is True and d["count"] == 10

    def test_get_threshold(self):
        from fastapi.testclient import TestClient
        assert "threshold" in TestClient(_app).get("/api/cache/threshold").json()

    def test_pin_entry(self):
        from fastapi.testclient import TestClient
        with patch("backend.routers.cache.cache_store") as cs:
            cs.set_pinned = AsyncMock(return_value=True)
            d = TestClient(_app).put("/api/cache/entries/e1/pin", json={"pinned": True}).json()
        assert d == {"id": "e1", "pinned": True}

    def test_pin_not_found_404(self):
        from fastapi.testclient import TestClient
        with patch("backend.routers.cache.cache_store") as cs:
            cs.set_pinned = AsyncMock(return_value=False)
            r = TestClient(_app).put("/api/cache/entries/x/pin", json={"pinned": True})
        assert r.status_code == 404

    def test_evict(self):
        from fastapi.testclient import TestClient
        with patch("backend.routers.cache.cache_store") as cs:
            cs.evict = AsyncMock(return_value={"age": 1, "stale": 2, "overflow": 0})
            d = TestClient(_app).post("/api/cache/evict").json()
        assert d["age"] == 1 and d["total"] == 3

    def test_upload_faq(self):
        from fastapi.testclient import TestClient
        from backend.models import CacheEntry
        now = datetime.now(timezone.utc)
        entry = CacheEntry(id="f", query_text="Q", query_normalized="q", cached_sql="SQL",
                           genie_space_id="s", created_at=now, updated_at=now, record_type="faq", pinned=True)
        with (patch("backend.routers.cache.cache_store") as cs,
              patch("backend.routers.cache._parameterize_faq", new_callable=AsyncMock, return_value=(None, None))):
            cs.add_faq = AsyncMock(return_value=entry)
            d = TestClient(_app).post("/api/cache/faq", json={
                "question": "Q", "sql": "SQL", "genie_space_id": "s"}).json()
        assert d["entry"]["record_type"] == "faq"

    def test_trace_base_url(self):
        from fastapi.testclient import TestClient
        with patch("backend.routers.cache.get_mlflow_trace_base_url", return_value="http://x"):
            d = TestClient(_app).get("/api/cache/trace-base-url").json()
        assert d["base_url"] == "http://x"


class TestMemoryAPI:
    def test_get_sessions(self):
        from fastapi.testclient import TestClient
        from backend.models import Session
        now = datetime.now(timezone.utc)
        with patch("backend.routers.memory.session_store") as ss:
            ss.get_recent_sessions = AsyncMock(return_value=[
                Session(session_id="s1", user_id="u", created_at=now, updated_at=now)])
            d = TestClient(_app).get("/api/memory/sessions/u").json()
        assert len(d["sessions"]) == 1

    def test_get_session_history(self):
        from fastapi.testclient import TestClient
        from backend.models import Session, Message, MessageRole
        now = datetime.now(timezone.utc)
        with patch("backend.routers.memory.session_store") as ss:
            ss.get_session = AsyncMock(return_value=Session(
                session_id="s1", user_id="u", created_at=now, updated_at=now))
            ss.get_history = AsyncMock(return_value=[
                Message(id="m1", session_id="s1", role=MessageRole.USER, content="Hi", created_at=now)])
            d = TestClient(_app).get("/api/memory/sessions/u/s1").json()
        assert d["session"]["session_id"] == "s1" and len(d["messages"]) == 1

    def test_rename_session(self):
        from fastapi.testclient import TestClient
        from backend.models import Session
        now = datetime.now(timezone.utc)
        with patch("backend.routers.memory.session_store") as ss:
            ss.rename = AsyncMock(); ss.get_session = AsyncMock(return_value=Session(
                session_id="s1", user_id="u", title="New", created_at=now, updated_at=now))
            d = TestClient(_app).put("/api/memory/sessions/s1/rename", json={"title": "New"}).json()
        assert d["ok"] is True and d["session"]["title"] == "New"

    def test_delete_memory_entry(self):
        from fastapi.testclient import TestClient
        with patch("backend.routers.memory.memory_store") as ms:
            ms.delete = AsyncMock(return_value=True)
            d = TestClient(_app).delete("/api/memory/entries/u/e1").json()
        assert d == {"deleted": True, "id": "e1"}

    def test_restore_memory_entry(self):
        from fastapi.testclient import TestClient
        with patch("backend.routers.memory.memory_store") as ms:
            ms.restore = AsyncMock(return_value=True)
            d = TestClient(_app).post("/api/memory/entries/u/e1/restore").json()
        assert d == {"restored": True, "id": "e1"}

    def test_restore_not_found_404(self):
        from fastapi.testclient import TestClient
        with patch("backend.routers.memory.memory_store") as ms:
            ms.restore = AsyncMock(return_value=False)
            r = TestClient(_app).post("/api/memory/entries/u/x/restore")
        assert r.status_code == 404

    def test_clear_all_memories(self):
        from fastapi.testclient import TestClient
        with patch("backend.routers.memory.memory_store") as ms:
            ms.clear_all = AsyncMock(return_value=5)
            d = TestClient(_app).delete("/api/memory/entries/u").json()
        assert d["cleared"] is True and d["count"] == 5

    def test_delete_session(self):
        from fastapi.testclient import TestClient
        with patch("backend.routers.memory.session_store") as ss:
            ss.delete_session = AsyncMock()
            d = TestClient(_app).delete("/api/memory/sessions/u/s1").json()
        assert d == {"deleted": True, "session_id": "s1"}

    def test_clear_all_sessions(self):
        from fastapi.testclient import TestClient
        with patch("backend.routers.memory.session_store") as ss:
            ss.clear_all = AsyncMock(return_value=3)
            d = TestClient(_app).delete("/api/memory/sessions/u").json()
        assert d["cleared"] is True and d["count"] == 3

    def test_metrics(self):
        from fastapi.testclient import TestClient
        with (patch("backend.routers.memory.trace_store") as ts,
              patch("backend.services.cache_store.cache_store") as cs):
            ts.get_metrics = AsyncMock(return_value={
                "total_queries": 100, "cache_hits": 30, "cache_misses": 65,
                "cache_rejections": 5, "hit_rate": 0.3, "avg_latency_hit_ms": 50.0,
                "avg_latency_miss_ms": 500.0, "latency_savings_ms": 15000.0})
            cs.count = AsyncMock(return_value=42)
            d = TestClient(_app).get("/api/memory/metrics").json()
        assert d["total_queries"] == 100 and d["cache_size"] == 42


class TestFeedbackAPI:
    def test_thumbs_up(self):
        from fastapi.testclient import TestClient
        with patch("backend.routers.feedback._background_set_rating", new_callable=AsyncMock):
            d = TestClient(_app).post("/api/feedback", json={"trace_id": "t", "rating": 1}).json()
        assert d["rating"] == 1

    def test_thumbs_down(self):
        from fastapi.testclient import TestClient
        with patch("backend.routers.feedback._background_set_rating", new_callable=AsyncMock):
            d = TestClient(_app).post("/api/feedback", json={"trace_id": "t", "rating": -1}).json()
        assert d["rating"] == -1

    def test_invalid_rating_422(self):
        from fastapi.testclient import TestClient
        assert TestClient(_app).post("/api/feedback", json={"trace_id": "t", "rating": 5}).status_code == 422

    def test_missing_trace_id_422(self):
        from fastapi.testclient import TestClient
        assert TestClient(_app).post("/api/feedback", json={"rating": 1}).status_code == 422


# ============================================================================
# 11. PIPELINE HELPERS
# ============================================================================


class TestPipelineHelpers:
    def test_elapsed(self):
        assert 900 <= _elapsed({"start_time": time.time() - 1.0}) <= 1200

    def test_add_event_appends(self):
        u = _add_event({"start_time": time.time(), "events": []}, "x", {"k": "v"})
        assert len(u["events"]) == 1 and "elapsed_ms" in u["events"][0]["data"]

    def test_add_event_immutable(self):
        s = {"start_time": time.time(), "events": []}
        _add_event(s, "x", {})
        assert len(s["events"]) == 0


class TestBuildResponse:
    def test_minimal(self):
        from backend.models import CacheStatus
        r = _build_response("q", {"cache_status": "miss", "latency_ms": 100,
                                   "trace_id": "t", "resolved_session_id": "s"})
        assert r.question == "q" and r.cache_status == CacheStatus.MISS

    def test_rewritten_same_as_original_is_none(self):
        r = _build_response("q", {"rewritten": "q", "cache_status": "miss",
                                   "latency_ms": 0, "trace_id": "t", "resolved_session_id": "s"})
        assert r.rewritten_question is None

    def test_rewritten_different(self):
        r = _build_response("q", {"rewritten": "rq", "cache_status": "miss",
                                   "latency_ms": 0, "trace_id": "t", "resolved_session_id": "s"})
        assert r.rewritten_question == "rq"


# ============================================================================
# 12. SPACE NODE MAP CONSISTENCY
# ============================================================================


class TestSpaceMetaCache:
    def test_active_metas_populated(self):
        from backend.config import GenieSpaceConfig
        from backend.services.graph import _get_all_active_space_metas, update_space_metas

        update_space_metas([
            GenieSpaceConfig(space_id="space-a", title="Test Space", description="Test metadata"),
        ])

        metas = _get_all_active_space_metas()
        assert len(metas) >= 1
        for m in metas:
            assert "title" in m
            assert "space_id" in m
