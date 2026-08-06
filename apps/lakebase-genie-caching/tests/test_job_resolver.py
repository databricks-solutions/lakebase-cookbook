"""Tests for Databricks Job discovery helpers."""

from types import SimpleNamespace

from backend.services.job_resolver import select_batch_job_id


def _job(job_id, name, tags=None, deployment=None):
    return SimpleNamespace(
        job_id=job_id,
        settings=SimpleNamespace(
            name=name,
            tags=tags or {},
            deployment=deployment,
        ),
    )


def test_select_batch_job_prefers_bundle_managed_project_job():
    stale_manual = _job(
        1,
        "lakebase-genie-caching-batch",
        {"project": "lakebase-genie-caching", "type": "batch-pipeline"},
    )
    bundle_managed = _job(
        2,
        "[dev alice] lakebase-genie-caching-batch",
        {"project": "lakebase-genie-caching", "type": "batch-pipeline"},
        deployment=SimpleNamespace(kind="BUNDLE"),
    )

    assert select_batch_job_id([stale_manual, bundle_managed], "lakebase-genie-caching-batch") == "2"


def test_select_batch_job_falls_back_to_exact_name():
    exact = _job(3, "lakebase-genie-caching-batch")

    assert select_batch_job_id([exact], "lakebase-genie-caching-batch") == "3"
