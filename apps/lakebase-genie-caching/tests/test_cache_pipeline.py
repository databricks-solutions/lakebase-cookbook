"""Tests for the offline cache pipeline logic."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from backend.models import CacheSearchResult, CacheEntry, CacheStatus, Trace


def _mock_cache_store():
    """Create a properly mocked cache_store with async methods."""
    mock = MagicMock()
    mock.search = AsyncMock(return_value=None)
    mock.add = AsyncMock(return_value=MagicMock())
    mock.is_promoted = AsyncMock(return_value=False)
    # True = this caller won the claim (the trace was not already promoted).
    mock.claim_promotion = AsyncMock(return_value=True)
    mock.record_promotion = AsyncMock()
    mock.evict = AsyncMock(return_value={"age": 0, "stale": 0, "overflow": 0})
    return mock


def _mock_memory_store():
    """Create a properly mocked memory_store with async methods."""
    mock = MagicMock()
    mock.add_or_update = AsyncMock(return_value=None)
    mock.apply_decay = AsyncMock()
    mock.evict = AsyncMock(return_value=0)
    return mock


class TestCachePipelineSingleSpace:
    """Test cache pipeline with single-space traces."""

    @pytest.mark.asyncio
    async def test_single_trace_promoted(self):
        now = datetime.now(timezone.utc)
        trace = Trace(
            id="t1", session_id="s1", user_id="u1",
            question="What is revenue?",
            rewritten_question="What is total revenue?",
            sql="SELECT SUM(revenue) FROM sales",
            cache_status=CacheStatus.MISS,
            latency_ms=500.0, created_at=now,
            genie_space_id="space-1",
        )

        mock_cs = _mock_cache_store()
        mock_ms = _mock_memory_store()

        with (
            patch("backend.pipelines.cache_pipeline.trace_store") as mock_ts,
            patch("backend.pipelines.cache_pipeline.cache_store", mock_cs),
            patch("backend.pipelines.cache_pipeline.memory_store", mock_ms),
            patch("backend.pipelines.cache_pipeline.config") as mock_config,
            patch("backend.pipelines.cache_pipeline._call_fast_llm", new_callable=AsyncMock) as mock_llm,
        ):
            mock_ts.get_thumbs_up_uncached = AsyncMock(return_value=[trace])
            mock_ts.get_recent_traces = AsyncMock(return_value=[])
            mock_config.cache.parameterize_on_ingest = False
            mock_config.genie.spaces = [MagicMock(space_id="space-1"), MagicMock(space_id="sp1"), MagicMock(space_id="sp2"), MagicMock(space_id="default-space"), MagicMock(space_id="space-incidence"), MagicMock(space_id="space-trials")]

            from backend.pipelines.cache_pipeline import run_cache_pipeline
            result = await run_cache_pipeline(limit=10)

            assert result["cache"]["added"] == 1
            assert result["cache"]["skipped"] == 0
            assert result["cache"]["total_traces"] == 1
            mock_cs.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_trace_skipped_no_sql(self):
        now = datetime.now(timezone.utc)
        trace = Trace(
            id="t1", session_id="s1", user_id="u1",
            question="Hello", sql=None,
            cache_status=CacheStatus.MISS,
            latency_ms=100.0, created_at=now,
        )

        mock_cs = _mock_cache_store()
        mock_ms = _mock_memory_store()

        with (
            patch("backend.pipelines.cache_pipeline.trace_store") as mock_ts,
            patch("backend.pipelines.cache_pipeline.cache_store", mock_cs),
            patch("backend.pipelines.cache_pipeline.memory_store", mock_ms),
            patch("backend.pipelines.cache_pipeline.config") as mock_config,
        ):
            mock_ts.get_thumbs_up_uncached = AsyncMock(return_value=[trace])
            mock_ts.get_recent_traces = AsyncMock(return_value=[])
            mock_config.cache.parameterize_on_ingest = False
            mock_config.genie.spaces = [MagicMock(space_id="space-1"), MagicMock(space_id="sp1"), MagicMock(space_id="sp2"), MagicMock(space_id="default-space"), MagicMock(space_id="space-incidence"), MagicMock(space_id="space-trials")]

            from backend.pipelines.cache_pipeline import run_cache_pipeline
            result = await run_cache_pipeline(limit=10)

            assert result["cache"]["added"] == 0
            assert result["cache"]["skipped"] == 1
            mock_cs.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_duplicate_skipped(self):
        now = datetime.now(timezone.utc)
        trace = Trace(
            id="t1", session_id="s1", user_id="u1",
            question="Revenue?", sql="SELECT 1",
            cache_status=CacheStatus.MISS,
            latency_ms=100.0, created_at=now,
            genie_space_id="space-1",
        )
        existing_entry = CacheEntry(
            id="existing", query_text="Revenue?", query_normalized="revenue",
            cached_sql="SELECT 1", genie_space_id="space-1",
            created_at=now, updated_at=now,
        )

        mock_cs = _mock_cache_store()
        mock_cs.search = AsyncMock(return_value=CacheSearchResult(
            entry=existing_entry, similarity_score=0.99,
        ))
        mock_ms = _mock_memory_store()

        with (
            patch("backend.pipelines.cache_pipeline.trace_store") as mock_ts,
            patch("backend.pipelines.cache_pipeline.cache_store", mock_cs),
            patch("backend.pipelines.cache_pipeline.memory_store", mock_ms),
            patch("backend.pipelines.cache_pipeline.config") as mock_config,
        ):
            mock_ts.get_thumbs_up_uncached = AsyncMock(return_value=[trace])
            mock_ts.get_recent_traces = AsyncMock(return_value=[])
            mock_config.cache.parameterize_on_ingest = False
            mock_config.genie.spaces = [MagicMock(space_id="space-1"), MagicMock(space_id="sp1"), MagicMock(space_id="sp2"), MagicMock(space_id="default-space"), MagicMock(space_id="space-incidence"), MagicMock(space_id="space-trials")]

            from backend.pipelines.cache_pipeline import run_cache_pipeline
            result = await run_cache_pipeline(limit=10)

            assert result["cache"]["added"] == 0
            assert result["cache"]["skipped"] == 1
            mock_cs.add.assert_not_called()


class TestCachePipelineMultiSpace:
    """Test cache pipeline with multi-space (supervisor) traces."""

    @pytest.mark.asyncio
    async def test_multi_space_decomposition(self):
        now = datetime.now(timezone.utc)
        trace = Trace(
            id="t1", session_id="s1", user_id="u1",
            question="What is X and Y?",
            sql="SELECT 1",
            cache_status=CacheStatus.MISS,
            latency_ms=500.0, created_at=now,
            genie_space_id="space-1",
            sub_results=[
                {"sub_question": "What is X?", "sql": "SELECT X", "space_id": "sp1", "cache_hit": False},
                {"sub_question": "What is Y?", "sql": "SELECT Y", "space_id": "sp2", "cache_hit": False},
            ],
        )

        mock_cs = _mock_cache_store()
        mock_ms = _mock_memory_store()

        with (
            patch("backend.pipelines.cache_pipeline.trace_store") as mock_ts,
            patch("backend.pipelines.cache_pipeline.cache_store", mock_cs),
            patch("backend.pipelines.cache_pipeline.memory_store", mock_ms),
            patch("backend.pipelines.cache_pipeline.config") as mock_config,
        ):
            mock_ts.get_thumbs_up_uncached = AsyncMock(return_value=[trace])
            mock_ts.get_recent_traces = AsyncMock(return_value=[])
            mock_cs.search = AsyncMock(return_value=None)
            mock_config.cache.parameterize_on_ingest = False
            mock_config.genie.spaces = [MagicMock(space_id="space-1"), MagicMock(space_id="sp1"), MagicMock(space_id="sp2"), MagicMock(space_id="default-space"), MagicMock(space_id="space-incidence"), MagicMock(space_id="space-trials")]

            from backend.pipelines.cache_pipeline import run_cache_pipeline
            result = await run_cache_pipeline(limit=10)

            assert result["cache"]["added"] == 2
            assert mock_cs.add.call_count == 2

    @pytest.mark.asyncio
    async def test_multi_space_skips_cache_hits(self):
        now = datetime.now(timezone.utc)
        trace = Trace(
            id="t1", session_id="s1", user_id="u1",
            question="Complex query",
            sql="SELECT 1",
            cache_status=CacheStatus.MISS,
            latency_ms=500.0, created_at=now,
            genie_space_id="space-1",
            sub_results=[
                {"sub_question": "Q1", "sql": "SELECT 1", "space_id": "sp1", "cache_hit": True},
                {"sub_question": "Q2", "sql": "SELECT 2", "space_id": "sp2", "cache_hit": False},
            ],
        )

        mock_cs = _mock_cache_store()
        mock_ms = _mock_memory_store()

        with (
            patch("backend.pipelines.cache_pipeline.trace_store") as mock_ts,
            patch("backend.pipelines.cache_pipeline.cache_store", mock_cs),
            patch("backend.pipelines.cache_pipeline.memory_store", mock_ms),
            patch("backend.pipelines.cache_pipeline.config") as mock_config,
        ):
            mock_ts.get_thumbs_up_uncached = AsyncMock(return_value=[trace])
            mock_ts.get_recent_traces = AsyncMock(return_value=[])
            mock_cs.search = AsyncMock(return_value=None)
            mock_config.cache.parameterize_on_ingest = False
            mock_config.genie.spaces = [MagicMock(space_id="space-1"), MagicMock(space_id="sp1"), MagicMock(space_id="sp2"), MagicMock(space_id="default-space"), MagicMock(space_id="space-incidence"), MagicMock(space_id="space-trials")]

            from backend.pipelines.cache_pipeline import run_cache_pipeline
            result = await run_cache_pipeline(limit=10)

            assert result["cache"]["added"] == 1
            assert mock_cs.add.call_count == 1


class TestCachePipelineMultiStep:
    """Test cache pipeline with multi-step sequential traces (same or different spaces).

    Regression tests for the bug where only the first sub-question was cached
    because sub_results were lost during MLflow trace round-trip.
    """

    @pytest.mark.asyncio
    async def test_sequential_same_space_both_cached(self):
        """Both steps of a sequential same-space query should be cached."""
        now = datetime.now(timezone.utc)
        trace = Trace(
            id="t-multi-step", session_id="s1", user_id="u1",
            question="What are the dates of clinical trials for the top 5 cancer types by incidence?",
            sql="-- [Cancer Incidence]\nSELECT cancer_type FROM incidence\n\n-- [Clinical Trials]\nSELECT trial_date FROM trials",
            cache_status=CacheStatus.MISS,
            latency_ms=8000.0, created_at=now,
            genie_space_id="space-incidence,space-trials",
            sub_results=[
                {
                    "sub_question": "What are the top 5 cancer types by incidence?",
                    "sql": "SELECT cancer_type, incidence_count FROM cancer_incidence ORDER BY incidence_count DESC LIMIT 5",
                    "space_id": "space-incidence",
                    "description": "The top 5 cancer types are: Prostate, Breast, Lung, Colon, Melanoma",
                    "cache_hit": False,
                    "row_count": 5,
                },
                {
                    "sub_question": "What are the dates of clinical trials for prostate, breast, lung and bronchus, colon and rectum cancers?",
                    "sql": "SELECT cancer_type, trial_date FROM clinical_trials WHERE cancer_type IN ('Prostate', 'Breast', 'Lung')",
                    "space_id": "space-trials",
                    "description": "Found 42 clinical trials across the specified cancer types",
                    "cache_hit": False,
                    "row_count": 42,
                },
            ],
        )

        mock_cs = _mock_cache_store()
        mock_ms = _mock_memory_store()

        with (
            patch("backend.pipelines.cache_pipeline.trace_store") as mock_ts,
            patch("backend.pipelines.cache_pipeline.cache_store", mock_cs),
            patch("backend.pipelines.cache_pipeline.memory_store", mock_ms),
            patch("backend.pipelines.cache_pipeline.config") as mock_config,
        ):
            mock_ts.get_thumbs_up_uncached = AsyncMock(return_value=[trace])
            mock_ts.get_recent_traces = AsyncMock(return_value=[])
            mock_cs.search = AsyncMock(return_value=None)
            mock_config.cache.parameterize_on_ingest = False
            mock_config.genie.spaces = [MagicMock(space_id="space-1"), MagicMock(space_id="sp1"), MagicMock(space_id="sp2"), MagicMock(space_id="default-space"), MagicMock(space_id="space-incidence"), MagicMock(space_id="space-trials")]

            from backend.pipelines.cache_pipeline import run_cache_pipeline
            result = await run_cache_pipeline(limit=10)

            assert result["cache"]["added"] == 2, (
                f"Expected both sub-questions to be cached, got {result['cache']['added']}"
            )
            assert mock_cs.add.call_count == 2

            calls = mock_cs.add.call_args_list
            cached_questions = {c.kwargs.get("query") or c.args[0] for c in calls}
            assert "What are the top 5 cancer types by incidence?" in cached_questions
            assert any("clinical trials" in q for q in cached_questions)

    @pytest.mark.asyncio
    async def test_multi_step_caches_sql_not_descriptions(self):
        """Sub-result SQL is cached; the answer text is NOT stored.

        Descriptions used to be persisted as cached_answer so a later question
        could have the prose adapted without re-querying. That storage is removed:
        the cache holds SQL only, so every hit re-executes and results come from
        the warehouse rather than being replayed.
        """
        now = datetime.now(timezone.utc)
        trace = Trace(
            id="t-desc", session_id="s1", user_id="u1",
            question="Multi-step question",
            sql="SELECT 1; SELECT 2",
            cache_status=CacheStatus.MISS,
            latency_ms=5000.0, created_at=now,
            sub_results=[
                {
                    "sub_question": "Step 1 question",
                    "sql": "SELECT step1 FROM data",
                    "space_id": "sp1",
                    "description": "Step 1 found 10 results",
                    "cache_hit": False,
                },
                {
                    "sub_question": "Step 2 question",
                    "sql": "SELECT step2 FROM data WHERE x IN ('a','b')",
                    "space_id": "sp2",
                    "description": "Step 2 found 25 matching records",
                    "cache_hit": False,
                },
            ],
        )

        mock_cs = _mock_cache_store()
        mock_ms = _mock_memory_store()

        with (
            patch("backend.pipelines.cache_pipeline.trace_store") as mock_ts,
            patch("backend.pipelines.cache_pipeline.cache_store", mock_cs),
            patch("backend.pipelines.cache_pipeline.memory_store", mock_ms),
            patch("backend.pipelines.cache_pipeline.config") as mock_config,
        ):
            mock_ts.get_thumbs_up_uncached = AsyncMock(return_value=[trace])
            mock_ts.get_recent_traces = AsyncMock(return_value=[])
            mock_cs.search = AsyncMock(return_value=None)
            mock_config.cache.parameterize_on_ingest = False
            mock_config.genie.spaces = [MagicMock(space_id="space-1"), MagicMock(space_id="sp1"), MagicMock(space_id="sp2"), MagicMock(space_id="default-space"), MagicMock(space_id="space-incidence"), MagicMock(space_id="space-trials")]

            from backend.pipelines.cache_pipeline import run_cache_pipeline
            result = await run_cache_pipeline(limit=10)

            assert result["cache"]["added"] == 2
            calls = mock_cs.add.call_args_list

            # Both sub-questions cached, by SQL.
            cached_sql = {c.kwargs.get("sql") for c in calls}
            assert "SELECT step1 FROM data" in cached_sql
            assert "SELECT step2 FROM data WHERE x IN ('a','b')" in cached_sql

            # No answer text was persisted anywhere.
            for c in calls:
                assert "cached_answer" not in c.kwargs
                assert "result" not in c.kwargs

    @pytest.mark.asyncio
    async def test_multi_step_missing_sql_on_step2_skipped(self):
        """If step 2 has no SQL (e.g. Genie failed), it should be skipped but step 1 still cached."""
        now = datetime.now(timezone.utc)
        trace = Trace(
            id="t-partial", session_id="s1", user_id="u1",
            question="Two step question",
            sql="SELECT 1",
            cache_status=CacheStatus.MISS,
            latency_ms=5000.0, created_at=now,
            sub_results=[
                {
                    "sub_question": "Step 1",
                    "sql": "SELECT 1 FROM t",
                    "space_id": "sp1",
                    "cache_hit": False,
                },
                {
                    "sub_question": "Step 2",
                    "sql": None,
                    "space_id": "sp2",
                    "cache_hit": False,
                },
            ],
        )

        mock_cs = _mock_cache_store()
        mock_ms = _mock_memory_store()

        with (
            patch("backend.pipelines.cache_pipeline.trace_store") as mock_ts,
            patch("backend.pipelines.cache_pipeline.cache_store", mock_cs),
            patch("backend.pipelines.cache_pipeline.memory_store", mock_ms),
            patch("backend.pipelines.cache_pipeline.config") as mock_config,
        ):
            mock_ts.get_thumbs_up_uncached = AsyncMock(return_value=[trace])
            mock_ts.get_recent_traces = AsyncMock(return_value=[])
            mock_cs.search = AsyncMock(return_value=None)
            mock_config.cache.parameterize_on_ingest = False
            mock_config.genie.spaces = [MagicMock(space_id="space-1"), MagicMock(space_id="sp1"), MagicMock(space_id="sp2"), MagicMock(space_id="default-space"), MagicMock(space_id="space-incidence"), MagicMock(space_id="space-trials")]

            from backend.pipelines.cache_pipeline import run_cache_pipeline
            result = await run_cache_pipeline(limit=10)

            assert result["cache"]["added"] == 1
            assert result["cache"]["skipped"] == 1

    @pytest.mark.asyncio
    async def test_sub_results_none_falls_back_to_single_space(self):
        """When sub_results is None (e.g. span attribute retrieval failed),
        the pipeline should fall back to caching the top-level question."""
        now = datetime.now(timezone.utc)
        trace = Trace(
            id="t-fallback", session_id="s1", user_id="u1",
            question="Original question about cancer trials",
            rewritten_question="Rewritten question about cancer trials",
            sql="SELECT * FROM trials",
            cache_status=CacheStatus.MISS,
            latency_ms=5000.0, created_at=now,
            genie_space_id="space-1",
            sub_results=None,
        )

        mock_cs = _mock_cache_store()
        mock_ms = _mock_memory_store()

        with (
            patch("backend.pipelines.cache_pipeline.trace_store") as mock_ts,
            patch("backend.pipelines.cache_pipeline.cache_store", mock_cs),
            patch("backend.pipelines.cache_pipeline.memory_store", mock_ms),
            patch("backend.pipelines.cache_pipeline.config") as mock_config,
        ):
            mock_ts.get_thumbs_up_uncached = AsyncMock(return_value=[trace])
            mock_ts.get_recent_traces = AsyncMock(return_value=[])
            mock_cs.search = AsyncMock(return_value=None)
            mock_config.cache.parameterize_on_ingest = False
            mock_config.genie.spaces = [MagicMock(space_id="space-1"), MagicMock(space_id="sp1"), MagicMock(space_id="sp2"), MagicMock(space_id="default-space"), MagicMock(space_id="space-incidence"), MagicMock(space_id="space-trials")]

            from backend.pipelines.cache_pipeline import run_cache_pipeline
            result = await run_cache_pipeline(limit=10)

            assert result["cache"]["added"] == 1
            call_kwargs = mock_cs.add.call_args.kwargs
            assert call_kwargs["query"] == "Rewritten question about cancer trials"


class TestLeanSubResults:
    """Test that the lean sub_results serialization strips bulk data."""

    def test_lean_sub_results_excludes_data_and_columns(self):
        """The lean version stored in span attributes should NOT contain data/columns."""
        import json

        sub_results = [
            {
                "space_id": "sp1",
                "space_title": "Cancer Incidence",
                "sub_question": "What are the top 5 cancer types?",
                "sql": "SELECT cancer_type FROM incidence LIMIT 5",
                "columns": ["cancer_type", "count"],
                "data": [["Prostate", 230000], ["Breast", 280000], ["Lung", 220000]],
                "row_count": 3,
                "description": "Top cancers are Prostate, Breast, Lung",
                "conversation_id": "conv-123",
                "message_id": "msg-456",
                "cache_hit": False,
            },
            {
                "space_id": "sp2",
                "space_title": "Clinical Trials",
                "sub_question": "What are trial dates for those cancers?",
                "sql": "SELECT trial_date FROM trials WHERE cancer_type IN ('Prostate')",
                "columns": ["cancer_type", "trial_date"],
                "data": [["Prostate", "2024-01-15"], ["Breast", "2024-03-20"]] * 50,
                "row_count": 100,
                "description": "Found 100 clinical trials",
                "conversation_id": "conv-789",
                "message_id": "msg-012",
                "cache_hit": False,
            },
        ]

        lean = [{
            "space_id": r.get("space_id"),
            "space_title": r.get("space_title"),
            "sub_question": r.get("sub_question"),
            "sql": r.get("sql"),
            "description": r.get("description"),
            "conversation_id": r.get("conversation_id"),
            "message_id": r.get("message_id"),
            "cache_hit": r.get("cache_hit", False),
            "row_count": r.get("row_count"),
        } for r in sub_results]

        lean_json = json.dumps(lean, default=str)
        full_json = json.dumps(sub_results, default=str)

        assert len(lean_json) < len(full_json), "Lean should be smaller than full"
        assert "data" not in {k for item in lean for k in item.keys()}
        assert "columns" not in {k for item in lean for k in item.keys()}

        parsed = json.loads(lean_json)
        assert len(parsed) == 2
        assert parsed[0]["sub_question"] == "What are the top 5 cancer types?"
        assert parsed[1]["sub_question"] == "What are trial dates for those cancers?"
        assert parsed[0]["sql"] is not None
        assert parsed[1]["sql"] is not None
        assert parsed[0]["space_id"] == "sp1"
        assert parsed[1]["space_id"] == "sp2"

    def test_lean_sub_results_dramatically_smaller(self):
        """With large data payloads, the lean version should be orders of magnitude smaller."""
        import json

        big_data = [[f"val_{i}", i, f"2024-{i%12+1:02d}-01"] for i in range(500)]
        sub_results = [{
            "space_id": "sp1",
            "space_title": "Space",
            "sub_question": "A question?",
            "sql": "SELECT * FROM t",
            "columns": ["col_a", "col_b", "col_c"],
            "data": big_data,
            "row_count": 500,
            "description": "Got 500 rows",
            "conversation_id": "c1",
            "message_id": "m1",
            "cache_hit": False,
        }]

        lean = [{
            "space_id": r.get("space_id"),
            "space_title": r.get("space_title"),
            "sub_question": r.get("sub_question"),
            "sql": r.get("sql"),
            "description": r.get("description"),
            "conversation_id": r.get("conversation_id"),
            "message_id": r.get("message_id"),
            "cache_hit": r.get("cache_hit", False),
            "row_count": r.get("row_count"),
        } for r in sub_results]

        lean_json = json.dumps(lean)
        full_json = json.dumps(sub_results)

        assert len(full_json) > 10000, f"Full should be large, got {len(full_json)}"
        assert len(lean_json) < 500, f"Lean should be small, got {len(lean_json)}"


class TestCachePipelineEmpty:
    """Test pipeline with no traces to process."""

    @pytest.mark.asyncio
    async def test_no_traces(self):
        mock_cs = _mock_cache_store()
        mock_ms = _mock_memory_store()

        with (
            patch("backend.pipelines.cache_pipeline.trace_store") as mock_ts,
            patch("backend.pipelines.cache_pipeline.cache_store", mock_cs),
            patch("backend.pipelines.cache_pipeline.memory_store", mock_ms),
            patch("backend.pipelines.cache_pipeline.config"),
        ):
            mock_ts.get_thumbs_up_uncached = AsyncMock(return_value=[])
            mock_ts.get_recent_traces = AsyncMock(return_value=[])

            from backend.pipelines.cache_pipeline import run_cache_pipeline
            result = await run_cache_pipeline(limit=10)

            assert result["cache"]["added"] == 0
            assert result["cache"]["skipped"] == 0
            assert result["cache"]["total_traces"] == 0


class TestForeignSpaceTracesAreNotPromoted:
    """Promotion must ignore traces from spaces this deployment doesn't serve.

    Regression found in UAT. The trace archive is a persistent Unity Catalog
    table shared across deployments, so it accumulates traces from every app that
    ever wrote to it. Promotion used to fall back to `config.genie.spaces[0]`
    whenever a trace had no space of its own, which silently mis-filed foreign
    traces against the first configured space: a brand-new deployment pointed at
    retail and sales Genie spaces came up with a cache full of a previous
    deployment's oncology questions, bound to the retail space.
    """

    def test_is_configured_space_accepts_only_configured_ids(self):
        from unittest.mock import patch

        from backend.config import GenieSpaceConfig
        from backend.pipelines.cache_pipeline import _is_configured_space

        spaces = [
            GenieSpaceConfig(space_id="space-retail", title="Retail"),
            GenieSpaceConfig(space_id="space-sales", title="Sales"),
        ]
        with patch("backend.pipelines.cache_pipeline.config") as cfg:
            cfg.genie.spaces = spaces

            assert _is_configured_space("space-retail") is True
            assert _is_configured_space("space-sales") is True
            # A space from another deployment.
            assert _is_configured_space("space-oncology") is False
            assert _is_configured_space("") is False
            assert _is_configured_space(None) is False

    @pytest.mark.asyncio
    async def test_trace_from_a_foreign_space_is_skipped(self):
        """A trace whose space isn't configured must not become a cache entry."""
        from backend.models import Trace

        now = datetime.now(timezone.utc)
        foreign = Trace(
            id="tr-foreign", session_id="s1", user_id="alice@example.com",
            question="What are the 3 most common cancers?",
            sql="SELECT site FROM oncology.incidence ORDER BY rate DESC LIMIT 3",
            genie_space_id="space-oncology",   # not configured in this deployment
            cache_status=CacheStatus.MISS,
            latency_ms=500.0, created_at=now,
        )

        mock_cache = _mock_cache_store()
        with (
            patch("backend.pipelines.cache_pipeline.cache_store", mock_cache),
            patch("backend.pipelines.cache_pipeline.memory_store", _mock_memory_store()),
            patch("backend.pipelines.cache_pipeline.trace_store") as ts,
            patch("backend.pipelines.cache_pipeline.config") as cfg,
        ):
            cfg.genie.spaces = [
                type("S", (), {"space_id": "space-retail", "title": "Retail"})()
            ]
            cfg.cache.parameterize_on_ingest = False
            ts.get_thumbs_up_uncached = AsyncMock(return_value=[foreign])
            ts.get_recent_traces = AsyncMock(return_value=[])

            from backend.pipelines.cache_pipeline import run_cache_pipeline
            result = await run_cache_pipeline(limit=10)

        assert result["cache"]["added"] == 0, "a foreign-space trace was promoted"
        mock_cache.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_trace_from_a_configured_space_is_still_promoted(self):
        """The guard must not block legitimate promotion."""
        from backend.models import Trace

        now = datetime.now(timezone.utc)
        local = Trace(
            id="tr-local", session_id="s1", user_id="alice@example.com",
            question="What are the top 5 products by sales?",
            sql="SELECT product FROM retail.sales ORDER BY total DESC LIMIT 5",
            genie_space_id="space-retail",
            cache_status=CacheStatus.MISS,
            latency_ms=500.0, created_at=now,
        )

        mock_cache = _mock_cache_store()
        with (
            patch("backend.pipelines.cache_pipeline.cache_store", mock_cache),
            patch("backend.pipelines.cache_pipeline.memory_store", _mock_memory_store()),
            patch("backend.pipelines.cache_pipeline.trace_store") as ts,
            patch("backend.pipelines.cache_pipeline.config") as cfg,
        ):
            cfg.genie.spaces = [
                type("S", (), {"space_id": "space-retail", "title": "Retail"})()
            ]
            cfg.cache.parameterize_on_ingest = False
            ts.get_thumbs_up_uncached = AsyncMock(return_value=[local])
            ts.get_recent_traces = AsyncMock(return_value=[])

            from backend.pipelines.cache_pipeline import run_cache_pipeline
            result = await run_cache_pipeline(limit=10)

        assert result["cache"]["added"] == 1
        mock_cache.add.assert_called_once()
