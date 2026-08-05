"""Entry point: AgentServer + FastAPI routers + React frontend.

The AgentServer provides /invocations (Responses API) with automatic
MLflow tracing.  Backend API routers are mounted at /api/* and the
pre-built React app is served as static files at /.
"""

import asyncio
import logging
import os
import traceback

import mlflow
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# Register @invoke / @stream handlers before AgentServer init
import agent_server.agent  # noqa: F401
from mlflow.genai.agent_server import AgentServer

agent_server = AgentServer("ResponsesAgent")
app = agent_server.app

# ── CORS ──
#
# Only needed so the Vite dev server (a different origin) can call the API during
# local development. Deployed, the React bundle is served from this same origin,
# so no cross-origin access is required at all.
#
# `allow_origins=["*"]` together with `allow_credentials=True` is an invalid
# combination per the CORS spec and would let any site drive this API with the
# caller's cookies, so the wildcard is confined to local dev.
_DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

if os.environ.get("DATABRICKS_CLIENT_ID"):
    # Deployed as a Databricks App: same-origin only.
    logger.info("CORS: same-origin only (deployed)")
else:
    logger.info("CORS: allowing local dev origins %s", _DEV_ORIGINS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_DEV_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ── Mount API routers ──
from backend.routers import cache, feedback, genie_spaces, memory, pipelines  # noqa: E402

app.include_router(feedback.router)
app.include_router(cache.router)
app.include_router(memory.router)
app.include_router(pipelines.router)
app.include_router(genie_spaces.router)


# ── Startup / shutdown ──

from backend.config import config  # noqa: E402
from agent_server.sample_questions import refresh_genie_spaces_and_samples  # noqa: E402

_startup_error: str | None = None


_sample_questions: list[dict] = []


def _resolve_spaces_and_samples():
    """Fetch titles, descriptions, and sample questions for configured Genie spaces.

    Called once at startup. Updates config.genie.spaces in-place, refreshes
    the graph's space meta cache, and populates _sample_questions.
    """
    from backend.config import config

    global _sample_questions

    if not config.genie.spaces:
        return

    _sample_questions = refresh_genie_spaces_and_samples(config.genie.spaces, max_per_space=3)
    logger.info(f"Collected {len(_sample_questions)} sample questions from Genie spaces")

    from backend.services.graph import update_space_metas
    update_space_metas(config.genie.spaces)


def _bootstrap_lakebase_schema():
    """Grant CREATE on public schema to the app's SP when the current role can.

    On a fresh Lakebase database, the SP can connect but PostgreSQL's public
    schema may still deny CREATE to non-owners. This is best-effort: if the
    current role cannot grant privileges, setup_workspace.py must run once as
    the deployer/admin.
    """
    import uuid as _uuid
    from databricks.sdk import WorkspaceClient
    from backend.config import config

    sp_client_id = os.environ.get("DATABRICKS_CLIENT_ID")
    if not sp_client_id or not config.lakebase.dns:
        return

    try:
        w = WorkspaceClient()
        import psycopg
        from backend.services.db import get_credentials

        username, token = get_credentials()
        conn = psycopg.connect(
            host=config.lakebase.dns,
            port=config.lakebase.port,
            dbname=config.lakebase.database_name,
            user=username,
            password=token,
            sslmode=config.lakebase.sslmode,
            autocommit=True,
        )
        conn.execute(f'GRANT ALL ON SCHEMA public TO "{sp_client_id}"')
        conn.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "{sp_client_id}"')
        conn.close()
        logger.info(f"Lakebase schema bootstrap: granted CREATE to SP {sp_client_id}")
    except Exception as e:
        logger.warning(
            f"Lakebase schema bootstrap failed (may need manual grant): {e}\n"
            f"  Run: GRANT ALL ON SCHEMA public TO \"{sp_client_id}\";"
        )


def _bootstrap_genie_permissions():
    """Grant CAN_MANAGE on each configured Genie space to the app's SP."""
    from backend.config import config

    sp_client_id = os.environ.get("DATABRICKS_CLIENT_ID")
    if not sp_client_id or not config.genie.spaces:
        return

    try:
        import json
        import urllib.request
        from databricks.sdk import WorkspaceClient

        w = WorkspaceClient()
        host = w.config.host.rstrip("/")
        headers = w.config.authenticate()

        for space in config.genie.spaces:
            try:
                url = f"{host}/api/2.0/permissions/genie/{space.space_id}"
                body = json.dumps({
                    "access_control_list": [{
                        "service_principal_name": sp_client_id,
                        "permission_level": "CAN_MANAGE",
                    }]
                }).encode()
                req = urllib.request.Request(url, data=body, method="PATCH",
                    headers={**headers, "Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=10)
                logger.info(f"Genie bootstrap: granted CAN_MANAGE on {space.space_id}")
            except Exception as e:
                logger.warning(f"Genie bootstrap: failed for {space.space_id}: {e}")
    except Exception as e:
        logger.warning(f"Genie permission bootstrap failed: {e}")


@app.on_event("startup")
async def on_startup():
    logger.info("Starting Lakebase Genie Caching (AgentServer mode)...")

    # Fail loudly on misconfiguration: name the missing variable rather than
    # letting the app die later inside an opaque API call.
    for problem in config.validate():
        logger.error(f"CONFIG: {problem}")

    # Ensure SP has permissions on resources the Apps framework can't manage
    try:
        from backend.services.permissions import ensure_permissions
        perm_results = await asyncio.to_thread(ensure_permissions)
        logger.info(f"Permission bootstrap: {perm_results}")
    except Exception as e:
        logger.warning(f"Permission bootstrap failed (non-fatal): {e}")

    try:
        mlflow.set_tracking_uri("databricks")

        # Prefer the experiment ID the bundle created. set_experiment(name) will
        # CREATE the experiment when the name does not resolve, and the app's
        # service principal cannot create one at the workspace root -- it fails
        # with PERMISSION_DENIED on aclPath /workspace and tracing silently
        # degrades. The name never resolves in development mode, where the bundle
        # prefixes it (e.g. "[dev alice] lakebase-genie-caching").
        if config.mlflow_experiment_id:
            mlflow.set_experiment(experiment_id=config.mlflow_experiment_id)
            active = config.mlflow_experiment_id
        else:
            mlflow.set_experiment(config.mlflow_experiment_name)
            active = config.mlflow_experiment_name

        os.environ.setdefault("MLFLOW_TRACING_SQL_WAREHOUSE_ID", config.genie.warehouse_id)
        logger.info(
            f"MLflow configured: tracking_uri={mlflow.get_tracking_uri()}, "
            f"experiment={active}"
        )
    except Exception as e:
        logger.error(
            "MLflow setup failed -- traces and thumbs-up feedback will not be "
            "recorded, so the offline cache-promotion pipeline has nothing to read: %s",
            e,
            exc_info=True,
        )

    try:
        from backend.services.db import init_db

        await init_db()

        try:
            await asyncio.to_thread(_bootstrap_lakebase_schema)
        except Exception as e:
            logger.warning(f"Lakebase schema bootstrap failed: {e}")

        from backend.services.cache_store import cache_store
        from backend.services.session_store import session_store
        from backend.services.memory_store import memory_store

        await cache_store.initialize()
        await session_store.initialize()
        await memory_store.initialize()
        logger.info("All stores initialized successfully")

        try:
            from backend.services.checkpointer import setup_checkpointer
            await setup_checkpointer()
            logger.info("LangGraph managed checkpointer setup complete")
        except Exception as e:
            logger.warning(f"Checkpointer setup failed (pipeline works without it): {e}")

    except Exception as e:
        global _startup_error
        _startup_error = f"{type(e).__name__}: {e}"
        logger.error(f"Database init failed: {e}", exc_info=True)
        logger.warning("App starting in degraded mode -- DB features unavailable")

    # Resolve Genie space titles + sample questions from the API
    try:
        await asyncio.to_thread(_resolve_spaces_and_samples)
    except Exception as e:
        logger.warning(f"Space resolution failed (using IDs as titles): {e}")

    # Bootstrap Genie space permissions for the SP
    try:
        await asyncio.to_thread(_bootstrap_genie_permissions)
    except Exception as e:
        logger.warning(f"Genie permission bootstrap failed: {e}")

    from backend.services.graph import init_pipeline, _get_all_active_space_metas
    init_pipeline(checkpointer=None)
    active = _get_all_active_space_metas()

    # Do not report success when the database is down. "startup complete" next to
    # a swallowed "Database init failed" made a cacheless deployment look healthy:
    # the app answers questions via Genie, so nothing looks wrong until someone
    # notices the cache never fills.
    from backend.services.db import db_available

    if db_available():
        logger.info(
            f"Lakebase Genie Caching startup complete. "
            f"Active spaces: {[s.get('title', '?') for s in active]}"
        )
    else:
        logger.error(
            "Lakebase Genie Caching started in DEGRADED mode: no Lakebase connection, so "
            "the semantic cache, user memory, and sessions are ALL unavailable and "
            "every question will go to Genie. Cause: %s\n"
            "  If you recently ran `bundle destroy`, Lakebase soft-deletes the "
            "project and holds its name for 7 days -- redeploying inside that "
            "window silently does not recreate it. Set a new `lakebase_project` "
            "value and redeploy.\n"
            "  Active spaces: %s",
            _startup_error or "unknown",
            [s.get("title", "?") for s in active],
        )


@app.on_event("shutdown")
async def on_shutdown():
    from backend.services.checkpointer import close_checkpointer
    from backend.services.db import close_db

    try:
        await close_checkpointer()
    except Exception:
        pass
    try:
        await close_db()
    except Exception:
        pass
    logger.info("Lakebase Genie Caching shutdown complete")


# ── Global exception handler ──
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    logger.error(f"Unhandled exception on {request.url.path}: {exc}\n{tb}")
    return JSONResponse(
        status_code=500,
        content={
            "error": str(exc),
            "type": type(exc).__name__,
            "path": str(request.url.path),
        },
    )


# ── Utility endpoints ──

@app.get("/api/sample-questions")
async def get_sample_questions():
    """Return sample questions from the latest Genie Space configuration."""
    await asyncio.to_thread(_resolve_spaces_and_samples)
    return _sample_questions


@app.get("/api/landing-data")
async def get_landing_data():
    """Return all chat landing data after one Genie metadata refresh."""
    await asyncio.to_thread(_resolve_spaces_and_samples)
    from backend.routers.genie_spaces import get_active
    from backend.services.cache_store import cache_store

    try:
        cache_entries = await cache_store.list_entries(limit=12, offset=0)
    except Exception as e:
        logger.warning("Could not load cached landing questions: %s", e)
        cache_entries = []

    return {
        "active_spaces": await get_active(refresh=False),
        "sample_questions": _sample_questions,
        "cache_entries": cache_entries,
    }


@app.get("/api/health")
async def health():
    from backend.services.db import db_available
    result = {"status": "ok", "version": "0.1.0", "db_available": db_available()}
    if not db_available() and _startup_error:
        result["db_error"] = _startup_error
    return result


@app.get("/api/config")
async def get_app_config():
    """Return workspace URLs and resource IDs for frontend resource links."""
    from databricks.sdk import WorkspaceClient
    from backend.config import config
    from backend.services.workspace_links import extract_org_id, org_query_param

    w = WorkspaceClient()
    host = w.config.host.rstrip("/")
    org_id = extract_org_id(host)
    o_param = org_query_param(host)

    experiment_id = config.mlflow_experiment_id
    if not experiment_id:
        try:
            from mlflow import MlflowClient
            exp = MlflowClient().get_experiment_by_name(config.mlflow_experiment_name)
            experiment_id = exp.experiment_id if exp else ""
        except Exception:
            experiment_id = ""

    batch_job_id = os.environ.get("BATCH_JOB_ID", "")
    if not batch_job_id:
        try:
            from backend.services.job_resolver import resolve_batch_job_id
            batch_job_id = resolve_batch_job_id(w, "", config.batch_job.job_name)
        except Exception:
            batch_job_id = ""

    trace_archive_job_id = os.environ.get("TRACE_ARCHIVE_JOB_ID", "")
    if not trace_archive_job_id and experiment_id:
        trace_archive_job_name = os.environ.get(
            "TRACE_ARCHIVE_JOB_NAME", f"[{experiment_id}] Trace Archive Job"
        )
        try:
            for job in w.jobs.list(name=trace_archive_job_name):
                if job.settings and job.settings.name == trace_archive_job_name:
                    trace_archive_job_id = str(job.job_id)
                    break
        except Exception:
            trace_archive_job_id = ""
    if not trace_archive_job_id:
        try:
            tagged_jobs = []
            for job in w.jobs.list():
                settings = getattr(job, "settings", None)
                tags = getattr(settings, "tags", None) or {}
                if tags.get("project") == "lakebase-genie-caching" and tags.get("type") == "trace-archive":
                    tagged_jobs.append(job)
            if len(tagged_jobs) == 1:
                trace_archive_job_id = str(tagged_jobs[0].job_id)
        except Exception:
            trace_archive_job_id = ""
    if not trace_archive_job_id:
        try:
            archive_jobs = [
                job for job in w.jobs.list()
                if job.settings and (job.settings.name or "").endswith("Trace Archive Job")
            ]
            if len(archive_jobs) == 1:
                trace_archive_job_id = str(archive_jobs[0].job_id)
        except Exception:
            trace_archive_job_id = ""

    lakebase_url = os.environ.get("LAKEBASE_URL", "")
    if not lakebase_url and config.lakebase.is_autoscaling and config.lakebase.project_name:
        try:
            project = w.postgres.get_project(name=f"projects/{config.lakebase.project_name}")
            lakebase_url = f"{host}/lakebase/projects/{project.uid}"
        except Exception:
            lakebase_url = f"{host}/lakebase/projects/{config.lakebase.project_name}"

    def _job_link(job_id: str) -> str | None:
        return f"{host}/jobs/{job_id}{o_param}" if job_id else None

    def _link(value: str) -> str | None:
        return value or None

    return {
        "workspace_host": host,
        "org_id": org_id,
        "experiment_id": experiment_id,
        "lakebase_instance": config.lakebase.project_name or config.lakebase.instance_name,
        "warehouse_id": config.genie.warehouse_id,
        "resource_links": {
            "mlflow_traces": _link(f"{host}/ml/experiments/{experiment_id}/traces{o_param}" if experiment_id else ""),
            "lakebase": (
                lakebase_url
                if lakebase_url
                else
                f"{host}/lakebase/projects/{config.lakebase.project_name}"
                if config.lakebase.is_autoscaling
                else f"{host}/lakebase/provisioned/{config.lakebase.instance_name}"
            ),
            "trace_archive_table": f"{host}/explore/data/{config.trace_archive.catalog}/{config.trace_archive.schema}/{config.trace_archive.table_name}{o_param}",
            "trace_archive_job": _job_link(trace_archive_job_id),
            "batch_pipelines_job": _job_link(batch_job_id),
        },
    }


@app.get("/api/tuning")
async def get_tuning():
    """Return all tunable thresholds / model settings for the Config page."""
    from backend.config import config
    return {
        "cache": {
            "similarity_threshold": config.cache.similarity_threshold,
            "answer_morph_threshold": config.cache.answer_morph_threshold,
            "top_k": config.cache.top_k,
            "ttl_hours": config.cache.ttl_hours,
            "max_age_days": config.cache.max_age_days,
            "stale_days": config.cache.stale_days,
        },
        "memory": {
            "similarity_threshold": config.memory.similarity_threshold,
            "score_threshold": config.memory.score_threshold,
            "top_k": config.memory.top_k,
            "max_age_days": config.memory.max_age_days,
            "decay_rate": config.memory.decay_rate,
            "blocklist_threshold": config.memory.blocklist_threshold,
        },
        "llm": {
            "classifier_endpoint": config.llm.classifier_endpoint,
            "assistant_endpoint": config.llm.assistant_endpoint,
        },
    }


# Accepted range per tunable, as (minimum, maximum) inclusive.
#
# Without bounds this endpoint could be used to disable the cache's safety
# properties outright: similarity_threshold 0 makes every query a "hit",
# stale_days 0 evicts the entire cache on the next run, and a negative top_k
# breaks the SQL LIMIT.
_TUNING_BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    "cache": {
        "similarity_threshold": (0.5, 1.0),
        "answer_morph_threshold": (0.5, 1.0),
        "top_k": (1, 50),
        "ttl_hours": (1, 24 * 365),
        "max_age_days": (1, 3650),
        "stale_days": (1, 3650),
    },
    "memory": {
        "similarity_threshold": (0.0, 1.0),
        "score_threshold": (0.0, 1.0),
        "top_k": (1, 50),
        "max_age_days": (1, 3650),
        "decay_rate": (0.0, 1.0),
        "blocklist_threshold": (0.0, 1.0),
    },
}


@app.put("/api/tuning")
async def update_tuning(request: Request):
    """Hot-update tunable thresholds (no redeploy needed).

    Admin-only, and every value is range-checked: these settings are global, so
    one caller's edit changes cache behaviour for everyone.
    """
    from fastapi import HTTPException

    from backend.config import config
    from backend.services.authz import require_admin

    require_admin(request)

    body = await request.json()
    targets = {"cache": config.cache, "memory": config.memory}

    # Validate everything before mutating anything: a partially-applied update
    # that then fails validation would leave the cache in a state the caller
    # never asked for and cannot see.
    pending: list[tuple[object, str, object, str]] = []

    for section, target in targets.items():
        if section not in body:
            continue
        values = body[section]
        if not isinstance(values, dict):
            raise HTTPException(status_code=422, detail=f"'{section}' must be an object")

        for key, (low, high) in _TUNING_BOUNDS[section].items():
            if key not in values:
                continue
            coerce = type(getattr(target, key))
            try:
                value = coerce(values[key])
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=422,
                    detail=f"{section}.{key} must be a {coerce.__name__}",
                )
            if not low <= value <= high:
                raise HTTPException(
                    status_code=422,
                    detail=f"{section}.{key} must be between {low} and {high}; got {value}",
                )
            pending.append((target, key, value, f"{section}.{key}={value}"))

    # Cross-field invariant: a direct hit must not be a weaker match than an
    # adaptation candidate, or Tier 1 and Tier 2 routing inverts. Evaluate
    # against the would-be result, not the current config.
    proposed = {key: value for target, key, value, _ in pending if target is config.cache}
    hit = proposed.get("similarity_threshold", config.cache.similarity_threshold)
    morph = proposed.get("answer_morph_threshold", config.cache.answer_morph_threshold)
    if morph > hit:
        raise HTTPException(
            status_code=422,
            detail=(
                "cache.answer_morph_threshold must be <= cache.similarity_threshold "
                f"({morph} > {hit})"
            ),
        )

    for target, key, value, _label in pending:
        setattr(target, key, value)

    updated = [label for *_rest, label in pending]
    logger.info(f"Tuning updated: {updated}")
    return {"updated": updated}


@app.get("/api/whoami")
async def whoami(request: Request):
    """Return the authenticated user identity.

    In a Databricks App, the proxy sets X-Forwarded-* headers.
    Falls back to WorkspaceClient for local dev.
    """
    forwarded_email = request.headers.get("X-Forwarded-Email")
    forwarded_user = (
        request.headers.get("X-Forwarded-Preferred-Username")
        or request.headers.get("X-Forwarded-User")
    )

    if forwarded_email or forwarded_user:
        user_id = forwarded_email or forwarded_user
        return {
            "user_id": user_id,
            "display_name": forwarded_user or forwarded_email,
            "email": forwarded_email,
        }

    try:
        def _get_user():
            from databricks.sdk import WorkspaceClient
            w = WorkspaceClient()
            me = w.current_user.me()
            return {
                "user_id": me.user_name or me.display_name or "unknown",
                "display_name": me.display_name,
                "email": me.user_name,
            }
        return await asyncio.to_thread(_get_user)
    except Exception as e:
        logger.warning(f"whoami failed: {e}")
        return {"user_id": "unknown", "display_name": None, "email": None}


# ── Ask endpoints (for React frontend) ──

from fastapi.responses import StreamingResponse  # noqa: E402
from backend.models import AskRequest, CompareRequest  # noqa: E402


MAX_SSE_DATA_ROWS = 200


def _cap_sse_rows(event_data):
    """Trim oversized result sets so one query can't flood the SSE stream."""
    if isinstance(event_data, dict):
        data_rows = event_data.get("data")
        if isinstance(data_rows, list) and len(data_rows) > MAX_SSE_DATA_ROWS:
            return {**event_data, "data": data_rows[:MAX_SSE_DATA_ROWS]}
    return event_data


def _sse_frame(event_type: str, event_data) -> str:
    """Serialise one Server-Sent Event frame."""
    import json

    if isinstance(event_data, dict):
        payload = json.dumps(event_data, ensure_ascii=False, default=str)
    else:
        payload = str(event_data)
    return f"event: {event_type}\ndata: {payload}\n\n"


def _ask_stream_response(question: str, session_id: str | None, auth) -> StreamingResponse:
    """Stream a pipeline run as SSE.

    Shared by the GET and POST stream endpoints, which previously carried four
    near-identical copies of this generator.
    """
    import json
    from backend.services import auth_context
    from backend.services.graph import run_pipeline_stream

    async def event_generator():
        # Bind the caller for the whole run: nodes read it via
        # auth_context.current() so Genie and cached SQL execute as this user.
        with auth_context.use(auth):
            try:
                async for event_type, event_data in run_pipeline_stream(
                    question, session_id, auth.user_id
                ):
                    yield _sse_frame(event_type, _cap_sse_rows(event_data))
            except Exception as e:
                logger.error(f"SSE generator error: {e}", exc_info=True)
                yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/ask")
async def ask_post(body: AskRequest, request: Request):
    """Non-streaming ask endpoint."""
    from backend.services import auth_context
    from backend.services.graph import run_pipeline

    # Identity comes from the proxy headers, never from the request body: a
    # client-supplied user_id would let any caller read another user's memory
    # and cache partition.
    auth = auth_context.from_headers(request.headers, fallback_user_id=body.user_id)
    with auth_context.use(auth):
        response, _events = await run_pipeline(body.question, body.session_id, auth.user_id)
    return response.model_dump()


@app.get("/api/ask")
async def ask_get(request: Request, question: str, session_id: str = None):
    """GET-based ask endpoint (for quick testing)."""
    from backend.services import auth_context
    from backend.services.graph import run_pipeline

    auth = auth_context.from_headers(request.headers)
    with auth_context.use(auth):
        response, _events = await run_pipeline(question, session_id, auth.user_id)
    return response.model_dump()


@app.post("/api/ask/stream")
async def ask_stream_post(body: AskRequest, request: Request):
    """SSE streaming endpoint (POST, used by React frontend)."""
    from backend.services import auth_context

    auth = auth_context.from_headers(request.headers, fallback_user_id=body.user_id)
    return _ask_stream_response(body.question, body.session_id, auth)


@app.get("/api/ask/stream")
async def ask_stream_get(request: Request, question: str, session_id: str = None):
    """SSE streaming endpoint (GET, for curl testing)."""
    from backend.services import auth_context

    auth = auth_context.from_headers(request.headers)
    return _ask_stream_response(question, session_id, auth)


@app.post("/api/compare/stream")
async def compare_stream(body: CompareRequest, request: Request):
    """A/B comparison: run the same question with and without cache in parallel."""
    import json
    from backend.services import auth_context
    from backend.services.graph import run_pipeline_stream

    auth = auth_context.from_headers(request.headers, fallback_user_id=body.user_id)

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue()
        result_a = None
        result_b = None

        async def _run_side(prefix: str, bypass: bool):
            # Each side runs in its own task, so bind the caller inside the task:
            # contextvars are copied at task creation, not shared afterwards.
            with auth_context.use(auth):
                try:
                    async for event_type, event_data in run_pipeline_stream(
                        body.question, session_id=None, user_id=auth.user_id,
                        bypass_cache=bypass,
                    ):
                        await queue.put((prefix, event_type, event_data))
                except Exception as e:
                    await queue.put((prefix, "error", {"message": str(e)}))
            await queue.put((prefix, "_done", None))

        task_a = asyncio.create_task(_run_side("a", False))
        task_b = asyncio.create_task(_run_side("b", True))

        done_count = 0
        try:
            while done_count < 2:
                prefix, event_type, event_data = await asyncio.wait_for(queue.get(), timeout=300)
                if event_type == "_done":
                    done_count += 1
                    continue
                event_data = _cap_sse_rows(event_data)
                yield _sse_frame(f"{prefix}_{event_type}", event_data)
                if event_type == "complete":
                    if prefix == "a":
                        result_a = event_data
                    else:
                        result_b = event_data

            # Comparison summary
            if result_a and result_b:
                lat_a = result_a.get("latency_ms", 0)
                lat_b = result_b.get("latency_ms", 0)
                saved = lat_b - lat_a
                saved_pct = (saved / lat_b * 100) if lat_b > 0 else 0
                rows_a = result_a.get("row_count") or 0
                rows_b = result_b.get("row_count") or 0
                results_match = rows_a == rows_b
                comparison = {
                    "latency_a_ms": lat_a,
                    "latency_b_ms": lat_b,
                    "saved_ms": saved,
                    "saved_pct": round(saved_pct, 1),
                    "cache_status_a": result_a.get("cache_status", "miss"),
                    "results_match": results_match,
                    "question": body.question,
                }
                yield f"event: comparison\ndata: {json.dumps(comparison)}\n\n"
        except asyncio.TimeoutError:
            yield f"event: error\ndata: {json.dumps({'message': 'Comparison timed out after 5 minutes'})}\n\n"
        except Exception as e:
            logger.error(f"Compare SSE error: {e}", exc_info=True)
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
        finally:
            task_a.cancel()
            task_b.cancel()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── Admin: reset memory processing so traces get re-scanned ──
@app.post("/api/admin/reset-memory-processing")
async def reset_memory_processing(request: Request):
    """Delete mem:* promotion keys + reset batch watermark so the next
    pipeline run re-extracts memories from all existing traces.

    Admin-only: this rewinds shared pipeline state, so the next batch run
    reprocesses every trace in the experiment.
    """
    from backend.services.authz import require_admin
    from backend.services.db import execute_raw

    require_admin(request)

    await execute_raw(
        "DELETE FROM promoted_trace_ids WHERE trace_id LIKE 'mem:%%'"
    )
    await execute_raw(
        "DELETE FROM pipeline_watermarks WHERE key = 'batch_pipeline_watermark'"
    )
    logger.info("Admin reset memory processing: promotion keys and watermark cleared")
    return {"status": "ok", "message": "Memory promotion keys and watermark cleared"}


# ── No-cache HTML middleware ──
@app.middleware("http")
async def no_cache_html(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.endswith(".html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ── Serve React frontend static files (with SPA fallback) ──
_frontend_dir: str | None = None
for candidate in [
    os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"),
    os.path.join(os.path.dirname(__file__), "..", "frontend_dist"),
    "/app/frontend/dist",
    "/app/frontend_dist",
]:
    if os.path.isdir(candidate):
        _frontend_dir = os.path.abspath(candidate)
        logger.info(f"Serving frontend from {_frontend_dir}")
        break

if _frontend_dir:
    from fastapi.responses import FileResponse, HTMLResponse  # noqa: E402

    app.mount("/assets", StaticFiles(directory=os.path.join(_frontend_dir, "assets")), name="static-assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        """Serve static files or fall back to index.html for SPA routing."""
        file_path = os.path.join(_frontend_dir, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        index = os.path.join(_frontend_dir, "index.html")
        return FileResponse(index)


def main():
    agent_server.run(app_import_string="agent_server.start_server:app")


if __name__ == "__main__":
    main()
