"""Databricks Job: batch pipelines for cache promotion, memory extraction, and eviction.

Reads traces from the inference table payload Delta table, cross-references
feedback from MLflow, then runs the cache/memory/eviction pipelines against
Lakebase. Designed for serverless compute with a 30-minute schedule.

Usage (from workspace):
    python jobs/batch_pipelines.py [--cache-limit 200] [--memory-sessions 20] [--no-eviction]
"""

import argparse
import asyncio
import base64
import importlib.util
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _early_arg_value(name: str) -> str:
    """Read a simple CLI argument before argparse runs."""
    try:
        index = sys.argv.index(name)
    except ValueError:
        return ""
    if index + 1 >= len(sys.argv):
        return ""
    return sys.argv[index + 1]


def _candidate_project_roots(file_path: str | None = None) -> list[str]:
    """Return candidate roots that may contain the backend package."""
    roots: list[str] = []
    explicit_root = os.environ.get("WORKSPACE_SOURCE_ROOT") or _early_arg_value("--workspace-source-root")
    if explicit_root:
        roots.append(explicit_root)

    if file_path:
        raw_path = file_path
        if "/jobs/" in raw_path:
            roots.append(raw_path.split("/jobs/", 1)[0])
        try:
            path = Path(raw_path)
            roots.append(str(path.parent.parent))
            roots.append(str(path.resolve().parent.parent))
        except Exception:
            pass

    roots.append(os.getcwd())
    roots.append(str(Path.cwd()))

    deduped = []
    for root in roots:
        if root and root not in deduped:
            deduped.append(root)
    return deduped


def _add_project_root_to_path() -> None:
    """Add the bundle/source root to sys.path so `backend.*` imports resolve."""
    file_path = globals().get("__file__")
    for root in _candidate_project_roots(file_path):
        if root not in sys.path:
            sys.path.insert(0, root)
        if (Path(root) / "backend" / "__init__.py").exists():
            return


def _workspace_object_type(value: object) -> str:
    """Normalize Databricks workspace object enum/string values."""
    raw_value = getattr(value, "value", value)
    return str(raw_value).upper()


def _workspace_python_files(w, package_path: str):
    """Yield Python file paths below a workspace package directory."""
    pending = [package_path]
    while pending:
        current = pending.pop()
        for item in w.workspace.list(current):
            item_path = getattr(item, "path", "")
            item_type = _workspace_object_type(getattr(item, "object_type", ""))
            if not item_path:
                continue
            if "DIRECTORY" in item_type:
                pending.append(item_path)
            elif item_path.endswith(".py"):
                yield item_path


def _materialize_workspace_package(root: str, package: str) -> str | None:
    """Copy a workspace package to local disk when serverless cannot import it directly."""
    if not root.startswith("/Workspace/"):
        return None

    try:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.workspace import ExportFormat

        w = WorkspaceClient()
        package_path = f"{root.rstrip('/')}/{package}"
        local_root = Path(tempfile.mkdtemp(prefix="genie-caching-source-"))

        for source_path in _workspace_python_files(w, package_path):
            response = w.workspace.export(source_path, format=ExportFormat.SOURCE)
            content = base64.b64decode(response.content or "").decode("utf-8")
            relative_path = source_path.removeprefix(f"{root.rstrip('/')}/")
            target_path = local_root / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")

        if str(local_root) not in sys.path:
            sys.path.insert(0, str(local_root))
        return str(local_root)
    except Exception as exc:
        logging.getLogger("batch_pipelines").warning(
            "Failed to materialize workspace package %s: %s", package, exc
        )
        return None


def _ensure_backend_importable() -> None:
    """Ensure `backend` imports work in Databricks serverless Python tasks."""
    if importlib.util.find_spec("backend") is not None:
        return

    file_path = globals().get("__file__")
    for root in _candidate_project_roots(file_path):
        _materialize_workspace_package(root, "backend")
        if importlib.util.find_spec("backend") is not None:
            return


_add_project_root_to_path()
_ensure_backend_importable()

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("batch_pipelines")

WATERMARK_KEY = "batch_pipeline_watermark"


def _set_env_if_value(name: str, value: str | None) -> None:
    """Set an environment variable from a job parameter when provided."""
    if value:
        os.environ[name] = value


def _apply_runtime_env(args: argparse.Namespace) -> None:
    """Map Databricks Job parameters into the env vars backend.config reads.

    Serverless job environments do not inherit Databricks App env vars, so the
    bundle passes the same runtime contract as task parameters.
    """
    _set_env_if_value("LAKEBASE_PROJECT", getattr(args, "lakebase_project", None))
    _set_env_if_value("ENDPOINT_NAME", getattr(args, "endpoint_name", None))
    _set_env_if_value("SQL_WAREHOUSE_ID", getattr(args, "warehouse_id", None))
    _set_env_if_value("GENIE_SPACE_IDS", getattr(args, "genie_space_ids", None))
    _set_env_if_value("TRACE_ARCHIVE_CATALOG", getattr(args, "trace_archive_catalog", None))
    _set_env_if_value("TRACE_ARCHIVE_SCHEMA", getattr(args, "trace_archive_schema", None))
    _set_env_if_value("TRACE_ARCHIVE_TABLE", getattr(args, "trace_archive_table", None))
    _set_env_if_value("MLFLOW_EXPERIMENT_NAME", getattr(args, "mlflow_experiment_name", None))
    _set_env_if_value("MLFLOW_EXPERIMENT_ID", getattr(args, "mlflow_experiment_id", None))
    _set_env_if_value("CLASSIFIER_LLM_ENDPOINT", getattr(args, "classifier_llm_endpoint", None))
    _set_env_if_value("ASSISTANT_LLM_ENDPOINT", getattr(args, "assistant_llm_endpoint", None))
    _set_env_if_value("WORKSPACE_SOURCE_ROOT", getattr(args, "workspace_source_root", None))
    os.environ.setdefault("MLFLOW_TRACKING_URI", "databricks")


from databricks.sdk.service.sql import StatementParameterListItem  # noqa: E402


def _execute_sql(
    sql: str, warehouse_id: str, parameters: list | None = None
) -> list[dict]:
    """Execute SQL via the Databricks SQL warehouse.

    ``parameters`` binds values as named markers (``:name``) rather than
    interpolating them into the statement text.
    """
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState

    w = WorkspaceClient()
    resp = w.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=sql,
        parameters=parameters,
        wait_timeout="50s",
    )
    if resp.status and resp.status.state == StatementState.FAILED:
        raise RuntimeError(f"SQL failed: {resp.status.error}")
    if not resp.result or not resp.result.data_array:
        return []
    columns = [c.name for c in resp.manifest.schema.columns]
    return [dict(zip(columns, row)) for row in resp.result.data_array]


def _is_missing_archive_table_error(exc: Exception) -> bool:
    """Return True when the trace archive table has not been created yet."""
    message = str(exc)
    return "TABLE_OR_VIEW_NOT_FOUND" in message and "mlflow_traces" in message


async def _get_watermark() -> str | None:
    """Read the last processed request_time from Lakebase."""
    from backend.services.db import execute_raw

    rows = await execute_raw(
        "SELECT value FROM pipeline_watermarks WHERE key = %(key)s",
        {"key": WATERMARK_KEY},
    )
    if rows and rows[0].get("value"):
        return rows[0]["value"]
    return None


async def _set_watermark(ts: str) -> None:
    """Upsert the watermark in Lakebase."""
    from backend.services.db import execute_raw

    await execute_raw(
        """INSERT INTO pipeline_watermarks (key, value, updated_at)
           VALUES (%(key)s, %(val)s, NOW())
           ON CONFLICT (key) DO UPDATE SET value = %(val)s, updated_at = NOW()""",
        {"key": WATERMARK_KEY, "val": ts},
    )


async def _ensure_watermark_table() -> None:
    """Create the watermark table if it doesn't exist."""
    from backend.services.db import execute_raw

    await execute_raw("""
        CREATE TABLE IF NOT EXISTS pipeline_watermarks (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)


def _is_configured_space(space_id: str | None) -> bool:
    """True when space_id is one this deployment is configured to serve.

    Imports config lazily, like the rest of this module: backend.config reads its
    values at import time, and _apply_runtime_env must set the environment first.
    A module-level import here raised NameError at runtime.
    """
    if not space_id:
        return False
    from backend.config import config

    return any(s.space_id == space_id for s in config.genie.spaces)


def _parse_sub_results(raw) -> list[dict] | None:
    """Parse sub_results from a string or return as-is if already a list."""
    if not raw:
        return None
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else None
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def _read_archive_traces(warehouse_id: str, archive_table: str, watermark: str | None, limit: int) -> list[dict]:
    """Read traces from the MLflow traces archive Delta table.

    The archive table is populated by the Trace Archive Job and contains
    columns: trace_id, request_time, execution_duration_ms, request,
    response, tags (JSON string), etc.
    """
    # Bind the watermark rather than interpolating it. It comes from our own
    # table today, but building SQL text out of stored values is the pattern
    # that turns a future data-integrity bug into an injection.
    where = ""
    parameters = None
    if watermark:
        where = "AND request_time > :watermark"
        parameters = [
            StatementParameterListItem(name="watermark", value=str(watermark))
        ]

    sql = f"""
        SELECT
            trace_id,
            request_time,
            execution_duration_ms,
            state,
            request,
            response,
            tags,
            spans[0].attributes['sql_full'] AS sql_full,
            spans[0].attributes['sub_results_full'] AS sub_results_full
        FROM {archive_table}
        WHERE state = 'OK'
          {where}
        ORDER BY request_time DESC
        LIMIT {limit}
    """
    try:
        rows = _execute_sql(sql, warehouse_id, parameters=parameters)
    except RuntimeError as exc:
        if _is_missing_archive_table_error(exc):
            logger.warning("Trace archive table %s does not exist yet; treating as no traces", archive_table)
            return []
        raise

    traces = []
    for row in rows:
        tags_raw = row.get("tags")
        if not tags_raw:
            continue
        try:
            parsed = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
            tags = parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            tags = {}

        question = tags.get("question", "")
        if not question:
            continue

        resp_raw = row.get("response")
        resp_json = {}
        if resp_raw:
            try:
                parsed = json.loads(resp_raw) if isinstance(resp_raw, str) else resp_raw
                resp_json = parsed if isinstance(parsed, dict) else {}
            except (json.JSONDecodeError, TypeError):
                pass

        req_raw = row.get("request")
        req_json = {}
        if req_raw:
            try:
                parsed = json.loads(req_raw) if isinstance(req_raw, str) else req_raw
                req_json = parsed if isinstance(parsed, dict) else {}
            except (json.JSONDecodeError, TypeError):
                pass

        feedback_str = tags.get("feedback_rating", "")
        feedback_rating = None
        if feedback_str:
            try:
                feedback_rating = int(feedback_str)
            except (ValueError, TypeError):
                pass

        # Prefer full SQL/sub_results from span attributes (no size limit)
        # over truncated tag values (capped at 250 chars by MLflow).
        sql_full = row.get("sql_full") or ""
        sql_val = sql_full if sql_full.strip() and sql_full.strip() != '""' else (tags.get("sql") or None)

        sub_results_full_raw = row.get("sub_results_full") or ""
        sub_results = None
        if sub_results_full_raw and sub_results_full_raw.strip() and sub_results_full_raw.strip() != '""':
            sub_results = _parse_sub_results(sub_results_full_raw)
        if not sub_results:
            sub_results = _parse_sub_results(tags.get("sub_results")) or resp_json.get("sub_results")

        traces.append({
            "trace_id": row.get("trace_id") or tags.get("mlflow.traceName", ""),
            "request_time": row.get("request_time"),
            "execution_duration_ms": row.get("execution_duration_ms"),
            "question": question,
            "rewritten_question": tags.get("rewritten_question") or None,
            "sql": sql_val,
            "cache_status": tags.get("cache_status") or "miss",
            "session_id": tags.get("session_id") or req_json.get("session_id"),
            "user_id": req_json.get("user_id") or tags.get("user_id", "unknown"),
            # The pipeline writes this as the `genie_space_id` TAG (see
            # _set_trace_metadata in backend/services/graph.py); only the response
            # body calls it selected_space_id. Reading just selected_space_id from
            # tags always yielded None, which the old `or spaces[0]` fallback then
            # silently papered over -- so every promoted entry was attributed to
            # the first configured space regardless of which one answered.
            "selected_space_id": (
                tags.get("genie_space_id")
                or tags.get("selected_space_id")
                or resp_json.get("selected_space_id")
            ),
            "sub_results": sub_results,
            "similarity_score": tags.get("similarity_score") or None,
            "genie_latency_ms": resp_json.get("genie_latency_ms"),
            "feedback_rating": feedback_rating,
        })

    logger.info(f"Read {len(traces)} traces from archive table (watermark={watermark})")
    return traces


def _get_thumbs_up_ids_from_traces(traces: list[dict]) -> set[str]:
    """Extract trace IDs with thumbs-up (feedback_rating=1) from already-read traces."""
    ids = {t["trace_id"] for t in traces if t.get("feedback_rating") == 1}
    logger.info(f"Found {len(ids)} thumbs-up traces in archive data")
    return ids


async def run_cache_from_traces(traces: list[dict], thumbs_up_ids: set[str], limit: int) -> dict:
    """Run the cache promotion pipeline on thumbs-up payload traces."""
    from backend.pipelines.cache_pipeline import _cache_single_entry

    from backend.config import config

    added = 0
    skipped = 0
    parameterized = 0
    processed = 0

    for trace in traces:
        if processed >= limit:
            break

        trace_id = trace.get("trace_id", "")
        if trace_id not in thumbs_up_ids:
            continue

        if trace.get("cache_status") != "miss":
            continue

        sql = trace.get("sql")
        if not sql:
            skipped += 1
            continue

        sub_results = trace.get("sub_results")
        if sub_results and len(sub_results) > 1:
            for sub in sub_results:
                sub_sql = sub.get("sql")
                sub_space = sub.get("space_id")
                sub_question = sub.get("sub_question")
                if not sub_sql or not sub_space or not sub_question:
                    skipped += 1
                    continue
                if not _is_configured_space(sub_space):
                    # Foreign trace from another deployment sharing this archive.
                    skipped += 1
                    continue
                if sub.get("cache_hit"):
                    continue

                was_added, was_param = await _cache_single_entry(
                    query=sub_question,
                    sql=sub_sql,
                    space_id=sub_space,
                    trace_id=trace_id,
                    original_question=trace.get("question", ""),
                )
                if was_added:
                    added += 1
                    if was_param:
                        parameterized += 1
                else:
                    skipped += 1
                processed += 1
            continue

        # Only promote traces belonging to a space this deployment serves. The
        # archive table is persistent and shared across deployments, so falling
        # back to spaces[0] mis-filed foreign traces against the first configured
        # space -- see backend.pipelines.cache_pipeline._is_configured_space.
        space_id = trace.get("selected_space_id")
        if not space_id or not _is_configured_space(space_id):
            skipped += 1
            processed += 1
            continue
        query = trace.get("rewritten_question") or trace.get("question", "")

        was_added, was_param = await _cache_single_entry(
            query=query,
            sql=sql,
            space_id=space_id,
            trace_id=trace_id,
            original_question=trace.get("question", ""),
        )
        if was_added:
            added += 1
            if was_param:
                parameterized += 1
        else:
            skipped += 1
        processed += 1

    result = {"added": added, "skipped": skipped, "parameterized": parameterized, "processed": processed}
    logger.info(f"Cache pipeline: {result}")
    return result


async def run_memory_from_traces(traces: list[dict], max_traces: int) -> dict:
    """Extract memories directly from archive traces (no MLflow API re-fetch).

    Groups traces by user_id and processes ALL traces through the LLM memory
    extractor. The strict prompt ensures only explicit user instructions,
    self-descriptions, corrections, and definitions are captured — feedback
    rating is not required.
    """
    from backend.models import MemoryType
    from backend.pipelines.cache_pipeline import _extract_memories_from_trace, _TYPE_MAP
    from backend.services.cache_store import cache_store
    from backend.services.memory_store import memory_store

    user_traces: dict[str, list[dict]] = {}
    for t in traces:
        uid = t.get("user_id", "unknown")
        if uid and uid != "unknown" and t.get("question"):
            user_traces.setdefault(uid, []).append(t)

    total_added = 0
    total_updated = 0
    total_blocked = 0
    total_extracted = 0
    total_decayed = 0
    total_skipped = 0

    for uid, u_traces in user_traces.items():
        processed_for_user = 0
        for trace in u_traces:
            if processed_for_user >= max_traces:
                break

            trace_id = trace.get("trace_id", "")
            memory_key = f"mem:{trace_id}"
            # Atomic claim: the scheduled run and a UI trigger can overlap.
            if not await cache_store.claim_promotion(memory_key):
                total_skipped += 1
                continue

            try:
                memories = await _extract_memories_from_trace(
                    trace.get("question", ""),
                    trace.get("sql"),
                )
                for mem in memories:
                    mem_type = _TYPE_MAP.get(mem["type"], MemoryType.PREFERENCE)
                    result = await memory_store.add_or_update(
                        user_id=uid,
                        content=mem["content"],
                        memory_type=mem_type,
                    )
                    if result is None:
                        total_blocked += 1
                    elif result.recurrence_count > 1:
                        total_updated += 1
                    else:
                        total_added += 1
                total_extracted += 1
                processed_for_user += 1
            except Exception as e:
                logger.warning(f"Memory extraction failed for trace {trace_id}: {e}")


        try:
            decayed = await memory_store.apply_decay(uid)
            total_decayed += decayed
        except Exception as e:
            logger.warning(f"Memory decay failed for user {uid}: {e}")

    evicted = await memory_store.evict()

    result = {
        "users_processed": len(user_traces),
        "added": total_added,
        "updated": total_updated,
        "blocked": total_blocked,
        "decayed": total_decayed,
        "evicted": evicted,
        "traces_extracted": total_extracted,
        "traces_skipped": total_skipped,
    }
    logger.info(f"Memory pipeline: {result}")
    return result


async def run_eviction() -> dict:
    """Run eviction across all stores."""
    from backend.pipelines.eviction_pipeline import run_eviction_pipeline
    result = await run_eviction_pipeline()
    logger.info(f"Eviction pipeline: {result}")
    return result


async def main(args: argparse.Namespace) -> None:
    _apply_runtime_env(args)

    from backend.config import config
    from backend.services.cache_store import cache_store
    from backend.services.db import init_db
    from backend.services.memory_store import memory_store
    from backend.services.session_store import session_store

    logger.info("=== Batch Pipelines Job Started ===")

    logger.info("Initializing Lakebase connection and stores...")
    await init_db()
    await cache_store.initialize()
    await session_store.initialize()
    await memory_store.initialize()
    await _ensure_watermark_table()
    logger.info("All stores initialized")

    watermark = await _get_watermark()
    logger.info(f"Current watermark: {watermark or 'none (first run)'}")

    logger.info("Reading traces from archive table...")
    traces = await asyncio.to_thread(
        _read_archive_traces,
        config.genie.warehouse_id,
        config.trace_archive.full_table_name,
        watermark,
        args.cache_limit * 3,
    )

    if not traces:
        logger.info("No new traces found. Nothing to do.")
        return

    max_request_time = max(t.get("request_time", "") for t in traces if t.get("request_time"))

    logger.info("Extracting thumbs-up feedback from archive data...")
    thumbs_up_ids = _get_thumbs_up_ids_from_traces(traces)

    logger.info(f"Running cache pipeline (limit={args.cache_limit})...")
    cache_result = await run_cache_from_traces(traces, thumbs_up_ids, args.cache_limit)

    logger.info(f"Running memory pipeline (max_traces={args.memory_sessions})...")
    memory_result = await run_memory_from_traces(traces, args.memory_sessions)

    eviction_result = {}
    if args.eviction:
        logger.info("Running eviction pipeline...")
        eviction_result = await run_eviction()

    if max_request_time:
        await _set_watermark(max_request_time)
        logger.info(f"Watermark updated to {max_request_time}")

    logger.info("=== Batch Pipelines Job Complete ===")
    logger.info(f"  Cache: {cache_result}")
    logger.info(f"  Memory: {memory_result}")
    if eviction_result:
        logger.info(f"  Eviction: {eviction_result}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch pipelines for cache/memory/eviction")
    parser.add_argument("--cache-limit", type=int, default=200, help="Max traces to process for cache")
    parser.add_argument("--memory-sessions", type=int, default=20, help="Max sessions per user for memory")
    parser.add_argument("--no-eviction", dest="eviction", action="store_false", help="Skip eviction")
    parser.add_argument("--lakebase-project", default="", help="Lakebase Autoscaling project name")
    parser.add_argument("--endpoint-name", default="", help="Lakebase endpoint resource path override")
    parser.add_argument("--warehouse-id", default="", help="SQL warehouse ID for trace reads")
    parser.add_argument("--genie-space-ids", default="", help="Comma-separated Genie Space IDs")
    parser.add_argument("--trace-archive-catalog", default="", help="Trace archive Unity Catalog catalog")
    parser.add_argument("--trace-archive-schema", default="", help="Trace archive Unity Catalog schema")
    parser.add_argument("--trace-archive-table", default="", help="Trace archive Unity Catalog table")
    parser.add_argument("--mlflow-experiment-name", default="", help="MLflow experiment path")
    parser.add_argument(
        "--mlflow-experiment-id",
        default="",
        help="MLflow experiment ID (preferred; avoids a name lookup the bundle may have prefixed)",
    )
    parser.add_argument("--classifier-llm-endpoint", default="", help="Classifier LLM endpoint")
    parser.add_argument("--assistant-llm-endpoint", default="", help="Assistant LLM endpoint")
    parser.add_argument("--workspace-source-root", default="", help="Bundle workspace source root")
    parser.set_defaults(eviction=True)
    return parser.parse_args()


def _run_async(coro):
    """Run an async coroutine, handling both standalone and nested event loop cases."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Databricks serverless runs inside an existing event loop (IPython kernel)
        import nest_asyncio
        nest_asyncio.apply()
        return loop.run_until_complete(coro)
    else:
        return asyncio.run(coro)


if __name__ == "__main__":
    args = parse_args()
    _run_async(main(args))
