"""Tests for pipeline routing functions (pure logic, no LLM/DB calls)."""

import pytest

from backend.services.graph import (
    route_cache,
    route_cache_fallback,
    route_answer_morph,
    route_fast_path,
    route_supervisor,
    _fix_inline_bullets,
    _tag,
    MAX_CALLS_PER_SPACE,
)


class TestRouteCache:
    def test_direct_hit_routes_to_populate_params(self):
        state = {"cache_hit": True, "answer_morph": False}
        assert route_cache(state) == "populate_params"

    def test_sql_adaptation_routes_to_answer_morph(self):
        state = {"cache_hit": False, "answer_morph": True}
        assert route_cache(state) == "answer_morph"

    def test_miss_routes_to_genie_dispatch(self):
        state = {"cache_hit": False, "answer_morph": False}
        assert route_cache(state) == "genie_dispatch"


class TestRouteSupervisor:
    def test_empty_plan_routes_to_end(self):
        from langgraph.graph import END
        assert route_supervisor({"supervisor_plan": []}) == END

    def test_single_data_space_first_call(self):
        """First call: current_step=0, plan has 1 item -> cache_search."""
        state = {
            "supervisor_plan": [{"agent": "space-1", "task": "get data"}],
            "intent": "data_query",
            "current_step": 0,
        }
        assert route_supervisor(state) == "cache_search"

    def test_single_space_done_routes_to_end(self):
        """Loop-back: single-space plan, step >= len(plan) -> END."""
        from langgraph.graph import END
        state = {
            "supervisor_plan": [{"agent": "space-1", "task": "get data"}],
            "intent": "data_query",
            "current_step": 1,
        }
        assert route_supervisor(state) == END

    def test_multi_space_first_step(self):
        """First call: multi-space plan, step 0 -> cache_search."""
        state = {
            "supervisor_plan": [
                {"agent": "space-1", "task": "q1"},
                {"agent": "space-2", "task": "q2"},
            ],
            "intent": "data_query",
            "current_step": 0,
        }
        assert route_supervisor(state) == "cache_search"

    def test_multi_space_second_step(self):
        """Second iteration: multi-space plan, step 1 -> cache_search."""
        state = {
            "supervisor_plan": [
                {"agent": "space-1", "task": "q1"},
                {"agent": "space-2", "task": "q2"},
            ],
            "intent": "data_query",
            "current_step": 1,
        }
        assert route_supervisor(state) == "cache_search"

    def test_multi_space_done_routes_to_summarizer(self):
        """All steps complete, multi-space -> summarizer."""
        state = {
            "supervisor_plan": [
                {"agent": "space-1", "task": "q1"},
                {"agent": "space-2", "task": "q2"},
            ],
            "intent": "data_query",
            "current_step": 2,
        }
        assert route_supervisor(state) == "summarizer"


class TestRouteAnswerMorph:
    def test_success_routes_to_supervisor(self):
        assert route_answer_morph({"cache_status": "hit"}) == "supervisor"

    def test_failure_routes_to_genie_dispatch(self):
        assert route_answer_morph({"cache_status": "miss"}) == "genie_dispatch"


class TestRouteCacheFallback:
    def test_hit_loops_back_to_supervisor(self):
        assert route_cache_fallback({"cache_status": "hit"}) == "supervisor"

    def test_non_hit_routes_to_genie_dispatch(self):
        assert route_cache_fallback({"cache_status": "miss"}) == "genie_dispatch"
        assert route_cache_fallback({"cache_status": "rejected"}) == "genie_dispatch"


class TestMaxCallsPerSpace:
    def test_limit_is_2(self):
        assert MAX_CALLS_PER_SPACE == 2


class TestFixInlineBullets:
    def test_no_bullets(self):
        assert _fix_inline_bullets("Hello world") == "Hello world"

    def test_converts_inline_bullets(self):
        text = "• item1 • item2 • item3"
        result = _fix_inline_bullets(text)
        assert "- item1" in result
        assert "- item2" in result
        assert "- item3" in result

    def test_single_bullet_converted(self):
        text = "• single item"
        result = _fix_inline_bullets(text)
        assert "- single item" in result

    def test_preserves_multiline_bullets(self):
        text = "- already formatted\n- second item"
        assert _fix_inline_bullets(text) == text


class TestTag:
    def test_short_string_unchanged(self):
        assert _tag("hello") == "hello"

    def test_truncation_at_250(self):
        long_val = "x" * 300
        result = _tag(long_val)
        assert len(result) == 250

    def test_custom_max_len(self):
        assert _tag("abcdef", max_len=3) == "abc"

    def test_empty_string(self):
        assert _tag("") == ""

    def test_none_returns_empty(self):
        assert _tag(None) == ""


class TestRouteFastPath:
    def test_greeting_result(self):
        assert route_fast_path({"fast_path_result": "greeting"}) == "greeting"

    def test_echo_result(self):
        assert route_fast_path({"fast_path_result": "echo_result"}) == "echo_result"

    def test_assistant_result(self):
        assert route_fast_path({"fast_path_result": "assistant"}) == "assistant"

    def test_data_query_result(self):
        assert route_fast_path({"fast_path_result": "data_query"}) == "data_query"

    def test_missing_defaults_to_data_query(self):
        assert route_fast_path({}) == "data_query"
