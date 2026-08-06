"""Pipeline trigger endpoints – delegates to a Databricks Job when configured."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.config import config
from backend.services.authz import require_admin, require_self

router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])
logger = logging.getLogger(__name__)


class PipelineResult(BaseModel):
    pipeline: str
    result: dict


class JobTriggerResult(BaseModel):
    pipeline: str
    run_id: int
    job_id: str
    message: str
    job_url: Optional[str] = None


def _trigger_job() -> JobTriggerResult:
    """Trigger the batch Databricks Job and return the run metadata."""
    from databricks.sdk import WorkspaceClient
    from backend.services.job_resolver import resolve_batch_job_id

    w = WorkspaceClient()
    job_id = resolve_batch_job_id(w, config.batch_job.job_id, config.batch_job.job_name)
    if not job_id:
        raise HTTPException(status_code=500, detail="Batch job is not configured")

    run = w.jobs.run_now(job_id=int(job_id))
    host = w.config.host.rstrip("/")
    run_url = f"{host}/jobs/{job_id}/runs/{run.run_id}"

    logger.info("Triggered batch job %s, run_id=%s", job_id, run.run_id)
    return JobTriggerResult(
        pipeline="batch",
        run_id=run.run_id,
        job_id=job_id,
        message="Batch job triggered successfully",
        job_url=run_url,
    )


@router.post("/cache")
async def trigger_cache_pipeline(request: Request, limit: int = 100):
    """Trigger unified pipeline (cache promotion + memory extraction).

    Delegates to Databricks Job if configured. Admin-only: promotion writes to
    the shared cache and consumes warehouse and LLM capacity for the workspace.
    """
    require_admin(request)
    if config.batch_job.enabled:
        return _trigger_job()

    from backend.pipelines.cache_pipeline import run_cache_pipeline
    result = await run_cache_pipeline(limit=limit)
    return PipelineResult(pipeline="cache", result=result)


@router.post("/memory/{user_id}")
async def trigger_memory_pipeline(request: Request, user_id: str):
    """Extract memories from this user's rated traces, then run decay + eviction."""
    require_self(request, user_id)
    if config.batch_job.enabled:
        return _trigger_job()

    from backend.pipelines.memory_pipeline import run_memory_pipeline
    result = await run_memory_pipeline(user_id)
    return PipelineResult(pipeline="memory", result=result)


@router.post("/eviction")
async def trigger_eviction_pipeline(
    request: Request,
    cache_max_age_days: int | None = None,
    memory_max_age_days: int | None = None,
):
    """Trigger eviction pipeline – delegates to Databricks Job if configured.

    Admin-only: eviction deletes cache and memory entries workspace-wide.
    """
    require_admin(request)
    if config.batch_job.enabled:
        return _trigger_job()

    from backend.pipelines.eviction_pipeline import run_eviction_pipeline
    result = await run_eviction_pipeline(cache_max_age_days, memory_max_age_days)
    return PipelineResult(pipeline="eviction", result=result)
