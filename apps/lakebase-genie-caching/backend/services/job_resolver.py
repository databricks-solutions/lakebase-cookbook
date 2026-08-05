"""Helpers for resolving Databricks Jobs across bundle and manual deploys."""

from collections.abc import Iterable
from typing import Any


BATCH_JOB_TAGS = {"project": "lakebase-genie-caching", "type": "batch-pipeline"}


def _settings(job: Any) -> Any:
    return getattr(job, "settings", None)


def _job_name(job: Any) -> str:
    settings = _settings(job)
    return getattr(settings, "name", "") or ""


def _job_tags(job: Any) -> dict:
    settings = _settings(job)
    tags = getattr(settings, "tags", None) or {}
    return tags if isinstance(tags, dict) else {}


def _is_bundle_managed(job: Any) -> bool:
    settings = _settings(job)
    return bool(getattr(settings, "deployment", None))


def _matches_batch_tags(job: Any) -> bool:
    tags = _job_tags(job)
    return all(tags.get(key) == value for key, value in BATCH_JOB_TAGS.items())


def select_batch_job_id(jobs: Iterable[Any], configured_name: str) -> str:
    """Select the best batch job candidate, preferring bundle-managed jobs."""
    candidates = list(jobs)
    if not candidates:
        return ""

    def score(job: Any) -> tuple[int, str]:
        job_name = _job_name(job)
        points = 0
        if _matches_batch_tags(job):
            points += 10
        if _is_bundle_managed(job):
            points += 100
        if job_name == configured_name:
            points += 5
        elif configured_name and job_name.endswith(configured_name):
            points += 3
        return points, str(getattr(job, "job_id", ""))

    best = max(candidates, key=score)
    return str(getattr(best, "job_id", "")) if score(best)[0] > 0 else ""


def resolve_batch_job_id(w: Any, configured_job_id: str, configured_name: str) -> str:
    """Resolve the Databricks Job ID for the offline batch pipeline."""
    if configured_job_id:
        return configured_job_id

    jobs = []
    for job in w.jobs.list():
        name = _job_name(job)
        if name == configured_name or name.endswith(configured_name) or _matches_batch_tags(job):
            jobs.append(job)
    return select_batch_job_id(jobs, configured_name)
