"""Tests for the Phase 3 reliability fixes.

Covers behaviour that used to fail silently: background task errors, cache
outages reported as ordinary misses, non-atomic promotion claims, and
unbounded session growth.
"""

import asyncio
import logging

import pytest

from backend.models import CacheStatus


# ── Background tasks report their failures ──


@pytest.mark.asyncio
async def test_spawn_logs_a_failing_task(caplog):
    """A failed fire-and-forget write must not look like a success."""
    from backend.services.background import spawn

    async def _boom():
        raise RuntimeError("write failed")

    with caplog.at_level(logging.ERROR):
        task = spawn(_boom(), name="session.add_message")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    assert task.done()
    assert "session.add_message" in caplog.text
    assert "write failed" in caplog.text


@pytest.mark.asyncio
async def test_spawn_keeps_a_strong_reference_until_done():
    """Without a strong reference the loop can collect the task mid-flight."""
    from backend.services import background

    started = asyncio.Event()

    async def _slow():
        started.set()
        await asyncio.sleep(0.05)

    background.spawn(_slow(), name="slow")
    await started.wait()
    assert background.pending_count() >= 1

    await asyncio.sleep(0.1)
    assert background.pending_count() == 0


@pytest.mark.asyncio
async def test_spawn_success_is_not_logged_as_an_error(caplog):
    from backend.services.background import spawn

    async def _ok():
        return 42

    with caplog.at_level(logging.ERROR):
        spawn(_ok(), name="fine")
        await asyncio.sleep(0.01)

    assert "fine" not in caplog.text


# ── Cache outage is distinct from a cache miss ──


def test_cache_status_has_an_unavailable_state():
    assert CacheStatus.UNAVAILABLE.value == "unavailable"
    assert CacheStatus.UNAVAILABLE != CacheStatus.MISS


@pytest.mark.asyncio
async def test_cache_search_failure_reports_unavailable_not_miss():
    """A Lakebase outage previously emitted 'cache_miss', hiding the failure."""
    from unittest.mock import AsyncMock, patch

    from backend.services.graph import node_cache_search

    state = {
        "question": "What is revenue by region?",
        "current_task": "What is revenue by region?",
        "current_space_id": "space-1",
        "start_time": 0.0,
        "events": [],
    }

    with patch(
        "backend.services.graph._dual_cache_search",
        new_callable=AsyncMock,
        side_effect=RuntimeError("connection refused"),
    ):
        result = await node_cache_search(state)

    assert result["cache_hit"] is False
    assert result["cache_status"] == CacheStatus.UNAVAILABLE.value

    events = [e["event"] for e in result["events"]]
    assert "cache_unavailable" in events
    assert "cache_miss" not in events


# ── Promotion claims are atomic ──


@pytest.mark.asyncio
async def test_claim_promotion_returns_true_only_for_the_winner():
    """Two overlapping runs must not both promote the same trace."""
    from unittest.mock import AsyncMock, patch

    from backend.services.cache_store import cache_store

    # First INSERT returns the row (claim won); the second conflicts (no rows).
    with patch(
        "backend.services.cache_store.execute_raw",
        new_callable=AsyncMock,
        side_effect=[[{"trace_id": "tr-1"}], []],
    ) as mock_exec:
        first = await cache_store.claim_promotion("tr-1")
        second = await cache_store.claim_promotion("tr-1")

    assert first is True
    assert second is False

    sql = mock_exec.call_args_list[0].args[0]
    assert "ON CONFLICT" in sql
    assert "RETURNING" in sql


# ── Session eviction ──


@pytest.mark.asyncio
async def test_session_evict_rejects_zero_days():
    """max_age_days=0 would delete every session, including live ones."""
    from backend.services.session_store import session_store

    with pytest.raises(ValueError):
        await session_store.evict(0)


@pytest.mark.asyncio
async def test_session_evict_binds_the_interval_as_a_parameter():
    from unittest.mock import AsyncMock, patch

    from backend.services.session_store import session_store

    with patch(
        "backend.services.session_store.execute_raw",
        new_callable=AsyncMock,
        side_effect=[[{"session_id": "s-1"}], [], [{"session_id": "s-1"}]],
    ) as mock_exec:
        count = await session_store.evict(30)

    assert count == 1
    select_sql, select_params = mock_exec.call_args_list[0].args
    assert "INTERVAL '1 day' * :age_days" in select_sql
    assert select_params == {"age_days": 30}


@pytest.mark.asyncio
async def test_session_evict_is_a_noop_when_nothing_is_stale():
    from unittest.mock import AsyncMock, patch

    from backend.services.session_store import session_store

    with patch(
        "backend.services.session_store.execute_raw",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_exec:
        count = await session_store.evict(30)

    assert count == 0
    # Only the SELECT ran; no DELETE was issued.
    assert mock_exec.await_count == 1


# ── Timeouts are configurable ──


def test_no_hardcoded_llm_timeouts_remain():
    """Timeouts belong in config so latency is tunable in one place."""
    import re
    from pathlib import Path

    graph = Path(__file__).resolve().parents[1] / "backend" / "services" / "graph.py"
    numeric = re.findall(r"timeout=\d+", graph.read_text())
    assert not numeric, f"hardcoded timeouts remain: {numeric}"


def test_timeout_config_exposes_the_expected_knobs():
    from backend.config import config

    assert config.timeouts.classifier_llm > 0
    assert config.timeouts.assistant_llm > 0
    assert config.timeouts.supervisor_llm > 0


# ── Checkpointed A/B state must not leak into later queries ──


def _initial_state_keys(func_name: str) -> set[str]:
    """Keys the given pipeline entry point explicitly seeds into initial_state."""
    import ast
    import inspect
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "backend" / "services" / "graph.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Dict) and any(
                    isinstance(k, ast.Constant) and k.value == "question" for k in sub.keys
                ):
                    return {
                        k.value for k in sub.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)
                    }
    raise AssertionError(f"initial_state not found in {func_name}")


def test_run_pipeline_resets_bypass_cache():
    """Regression: a stale checkpointed bypass_cache disabled the cache entirely.

    Found on the deployed app. run_pipeline_stream sets bypass_cache=True for the
    A/B comparison's uncached side. Because the Lakebase checkpointer persists
    state per thread_id, and run_pipeline did not reset the flag, every later
    normal question from that user logged "Cache search skipped (A/B bypass)" and
    went to Genie -- the cache appeared broken.
    """
    assert "bypass_cache" in _initial_state_keys("run_pipeline")


def test_both_entry_points_seed_the_same_state_keys():
    """The two entry points must not drift; a key missing from one leaks state."""
    batch = _initial_state_keys("run_pipeline")
    stream = _initial_state_keys("run_pipeline_stream")

    missing_from_batch = stream - batch
    assert not missing_from_batch, (
        "run_pipeline does not reset keys that run_pipeline_stream sets, so stale "
        f"checkpointed values can bleed through: {sorted(missing_from_batch)}"
    )


def test_trace_user_id_tag_is_the_caller_not_the_thread_id():
    """The user_id trace tag must identify a person, not a session.

    Both entry points call _set_trace_metadata, but the batch path used to pass
    thread_id (`session_id or user_id`), so for any session-based query the
    user_id tag held a session UUID. That makes traces unattributable to a user
    -- which breaks feedback authorization and per-user memory extraction in the
    offline pipeline.
    """
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "backend" / "services" / "graph.py").read_text()
    tree = ast.parse(src)

    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_set_trace_metadata"
    ]
    assert len(calls) == 2, f"expected both entry points to tag traces, found {len(calls)}"

    for call in calls:
        second = call.args[1]
        assert isinstance(second, ast.Name) and second.id == "user_id", (
            "_set_trace_metadata must receive user_id, not "
            f"{ast.unparse(second)} -- a thread_id is a session, not a person"
        )
