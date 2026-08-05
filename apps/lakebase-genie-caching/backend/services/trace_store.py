"""Trace read-only store using MLflow API.

All operations use the MLflow tracking server API for reads.
This replaces the previous inference-table-based implementation.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

import mlflow

from backend.config import config
from backend.models import CacheStatus, Trace

logger = logging.getLogger(__name__)

_mlflow_client: mlflow.MlflowClient | None = None


def _get_client() -> mlflow.MlflowClient:
    global _mlflow_client
    if _mlflow_client is None:
        _mlflow_client = mlflow.MlflowClient()
    return _mlflow_client


def _experiment_id() -> str | None:
    """Resolve the experiment to search for traces.

    Prefers the ID the bundle passed. A name lookup fails whenever the bundle
    prefixed the experiment name (development mode), which silently returned None
    here and made every trace query come back empty -- so cache promotion found
    nothing to promote.
    """
    from backend.config import config

    if config.mlflow_experiment_id:
        return config.mlflow_experiment_id
    exp = mlflow.get_experiment_by_name(config.mlflow_experiment_name)
    return exp.experiment_id if exp else None


class TraceStore:

    async def initialize(self) -> None:
        logger.info("Trace store ready (MLflow API)")

    async def get_owner(self, trace_id: str) -> str | None:
        """Return the user_id tagged on a trace, or None if unknown.

        Used to authorize feedback: a trace_id is a bearer-like handle, so
        without this check any caller could rate any other user's answer -- and
        thumbs-up is what promotes a question into the shared cache.
        """
        def _fetch():
            client = _get_client()
            trace = client.get_trace(trace_id)
            if not trace or not trace.info:
                return None
            return (trace.info.tags or {}).get("user_id") or None

        try:
            return await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.warning("Could not resolve owner for trace %s: %s", trace_id, e)
            return None

    async def get_genie_ids(self, trace_id: str) -> dict | None:
        """Get Genie space/conversation/message IDs from MLflow trace tags."""
        def _fetch():
            client = _get_client()
            trace = client.get_trace(trace_id)
            if not trace or not trace.info:
                return None
            tags = trace.info.tags or {}
            space_id = tags.get("genie_space_id")
            conv_id = tags.get("genie_conversation_id")
            msg_id = tags.get("genie_message_id")
            if space_id and conv_id and msg_id:
                return {
                    "space_id": space_id,
                    "conversation_id": conv_id,
                    "message_id": msg_id,
                }
            return None

        try:
            return await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.warning(f"get_genie_ids failed for {trace_id}: {e}")
            return None

    async def get_thumbs_up_uncached(self, limit: int = 100) -> list[Trace]:
        """Get thumbs-up cache-miss traces for the cache promotion pipeline."""
        def _search():
            client = _get_client()
            exp_id = _experiment_id()
            if not exp_id:
                return []
            return client.search_traces(
                experiment_ids=[exp_id],
                filter_string=(
                    "tags.feedback_rating = '1' "
                    "AND tags.cache_status = 'miss'"
                ),
                max_results=limit,
            )

        try:
            mlflow_traces = await asyncio.to_thread(_search)
        except Exception as e:
            logger.warning(f"get_thumbs_up failed: {e}")
            return []

        return _mlflow_traces_to_traces(mlflow_traces)

    async def get_recent_traces(self, limit: int = 200) -> list[Trace]:
        """Get recent pipeline traces (all ratings) for memory extraction.

        Returns traces with intent=data_query that have a question,
        regardless of feedback rating or cache status.
        """
        def _search():
            client = _get_client()
            exp_id = _experiment_id()
            if not exp_id:
                return []
            return client.search_traces(
                experiment_ids=[exp_id],
                filter_string="tags.pipeline = 'langgraph' AND tags.intent = 'data_query'",
                max_results=limit,
            )

        try:
            mlflow_traces = await asyncio.to_thread(_search)
        except Exception as e:
            logger.warning(f"get_recent_traces failed: {e}")
            return []

        return _mlflow_traces_to_traces(mlflow_traces, fetch_full_sql=False, require_sql=False)

    async def get_metrics(self) -> dict:
        """Get cache performance metrics from MLflow traces."""
        def _search():
            client = _get_client()
            exp_id = _experiment_id()
            if not exp_id:
                return []
            return client.search_traces(
                experiment_ids=[exp_id],
                filter_string="tags.pipeline = 'langgraph'",
                max_results=1000,
            )

        try:
            traces = await asyncio.to_thread(_search)
        except Exception as e:
            logger.warning(f"get_metrics failed: {e}")
            return {}

        if not traces:
            return {}

        total = len(traces)
        hits = misses = rejections = 0
        hit_latencies: list[float] = []
        miss_latencies: list[float] = []

        for t in traces:
            tags = t.info.tags or {}
            cs = tags.get("cache_status")
            dur = float(t.info.execution_time_ms or 0)
            if cs == "hit":
                hits += 1
                hit_latencies.append(dur)
            elif cs == "miss":
                misses += 1
                miss_latencies.append(dur)
            elif cs == "rejected":
                rejections += 1

        avg_hit = sum(hit_latencies) / len(hit_latencies) if hit_latencies else 0.0
        avg_miss = sum(miss_latencies) / len(miss_latencies) if miss_latencies else 0.0

        return {
            "total_queries": total,
            "cache_hits": hits,
            "cache_misses": misses,
            "cache_rejections": rejections,
            "hit_rate": hits / total if total > 0 else 0,
            "avg_latency_hit_ms": round(avg_hit, 1),
            "avg_latency_miss_ms": round(avg_miss, 1),
            "latency_savings_ms": round(avg_miss - avg_hit, 1),
        }


def _get_full_sql_from_spans(trace_id: str) -> str | None:
    """Fetch untruncated SQL from the root span's sql_full attribute."""
    try:
        client = _get_client()
        full_trace = client.get_trace(trace_id)
        if full_trace and full_trace.data and full_trace.data.spans:
            for span in full_trace.data.spans:
                attrs = span.attributes or {}
                if "sql_full" in attrs and attrs["sql_full"]:
                    return attrs["sql_full"]
    except Exception as e:
        logger.debug(f"Could not fetch sql_full for {trace_id}: {e}")
    return None


def _get_full_sub_results_from_spans(trace_id: str) -> list | None:
    """Fetch untruncated sub_results from span attributes."""
    try:
        client = _get_client()
        full_trace = client.get_trace(trace_id)
        if full_trace and full_trace.data and full_trace.data.spans:
            for span in full_trace.data.spans:
                attrs = span.attributes or {}
                raw = attrs.get("sub_results_full")
                if raw:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                    logger.info(
                        f"Fetched sub_results_full for {trace_id}: "
                        f"{len(parsed)} sub-result(s), {len(raw) if isinstance(raw, str) else '?'} chars"
                    )
                    return parsed
        logger.warning(f"No sub_results_full attribute found in any span for {trace_id}")
    except Exception as e:
        logger.warning(f"Could not fetch sub_results_full for {trace_id}: {e}")
    return None


_TAG_TRUNCATION_LEN = 250


def _mlflow_traces_to_traces(
    mlflow_traces: list,
    fetch_full_sql: bool = True,
    require_sql: bool = True,
) -> list[Trace]:
    results = []
    for t in mlflow_traces:
        tags = t.info.tags or {}
        sql_val = tags.get("sql")
        if not sql_val and require_sql:
            continue

        # If the SQL tag looks truncated, fetch the full value from span attrs
        if fetch_full_sql and sql_val and len(sql_val) >= _TAG_TRUNCATION_LEN:
            full_sql = _get_full_sql_from_spans(t.info.request_id)
            if full_sql:
                logger.debug(
                    f"Using sql_full ({len(full_sql)} chars) instead of "
                    f"truncated tag ({len(sql_val)} chars) for {t.info.request_id}"
                )
                sql_val = full_sql

        sub_raw = tags.get("sub_results")
        sub = _try_json(sub_raw)
        # If sub_results tag looks truncated, fetch full version from span attrs
        if fetch_full_sql and sub_raw and len(sub_raw) >= _TAG_TRUNCATION_LEN and not sub:
            logger.info(
                f"sub_results tag truncated ({len(sub_raw)} chars) for {t.info.request_id}, "
                f"fetching from span attributes..."
            )
            sub = _get_full_sub_results_from_spans(t.info.request_id)
            if not sub:
                logger.warning(
                    f"Failed to recover sub_results for {t.info.request_id} — "
                    f"multi-step cache promotion will fall back to single-entry mode"
                )

        similarity = _try_float(tags.get("similarity_score"))
        genie_lat = _try_float(tags.get("genie_latency_ms"))

        created = datetime.fromtimestamp(
            t.info.timestamp_ms / 1000, tz=timezone.utc
        ) if t.info.timestamp_ms else datetime.now(timezone.utc)

        rating_raw = tags.get("feedback_rating")
        rating = int(rating_raw) if rating_raw else None

        results.append(Trace(
            id=t.info.request_id,
            session_id=tags.get("session_id") or "",
            user_id=tags.get("user_id") or "",
            question=tags.get("question") or "",
            rewritten_question=tags.get("rewritten_question") or None,
            sql=sql_val,
            cache_status=CacheStatus(tags.get("cache_status", "miss")),
            similarity_score=similarity,
            latency_ms=float(t.info.execution_time_ms or 0),
            genie_latency_ms=genie_lat,
            genie_space_id=tags.get("genie_space_id"),
            rating=rating,
            sub_results=sub,
            created_at=created,
        ))
    return results


def _try_json(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _try_float(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


trace_store = TraceStore()
