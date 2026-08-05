"""Tests for batch job runtime configuration wiring."""

import argparse
import os

from jobs.batch_pipelines import (
    _apply_runtime_env,
    _candidate_project_roots,
    _is_missing_archive_table_error,
)


def test_apply_runtime_env_sets_backend_config_variables(monkeypatch):
    for key in (
        "LAKEBASE_PROJECT",
        "SQL_WAREHOUSE_ID",
        "GENIE_SPACE_IDS",
        "TRACE_ARCHIVE_CATALOG",
        "TRACE_ARCHIVE_SCHEMA",
        "TRACE_ARCHIVE_TABLE",
        "MLFLOW_TRACKING_URI",
        "MLFLOW_EXPERIMENT_NAME",
        "CLASSIFIER_LLM_ENDPOINT",
        "ASSISTANT_LLM_ENDPOINT",
        "WORKSPACE_SOURCE_ROOT",
    ):
        monkeypatch.delenv(key, raising=False)

    args = argparse.Namespace(
        lakebase_project="lakebase-genie-caching",
        endpoint_name="projects/demo/branches/production/endpoints/primary",
        warehouse_id="warehouse-123",
        genie_space_ids="space-a,space-b",
        trace_archive_catalog="demo_catalog",
        trace_archive_schema="demo_schema",
        trace_archive_table="mlflow_traces_archived",
        mlflow_experiment_name="/lakebase-genie-caching",
        classifier_llm_endpoint="databricks-claude-haiku-4-5",
        assistant_llm_endpoint="databricks-claude-sonnet-4",
        workspace_source_root="/Workspace/Users/me/.bundle/lakebase_genie_caching/dev/files",
    )

    _apply_runtime_env(args)

    assert os.environ["LAKEBASE_PROJECT"] == "lakebase-genie-caching"
    assert os.environ["ENDPOINT_NAME"] == "projects/demo/branches/production/endpoints/primary"
    assert os.environ["SQL_WAREHOUSE_ID"] == "warehouse-123"
    assert os.environ["GENIE_SPACE_IDS"] == "space-a,space-b"
    assert os.environ["TRACE_ARCHIVE_TABLE"] == "mlflow_traces_archived"
    assert os.environ["WORKSPACE_SOURCE_ROOT"] == "/Workspace/Users/me/.bundle/lakebase_genie_caching/dev/files"
    assert os.environ["MLFLOW_TRACKING_URI"] == "databricks"


def test_candidate_project_roots_include_bundle_file_parent():
    roots = _candidate_project_roots(
        "/Workspace/Users/me/.bundle/lakebase_genie_caching/dev/files/jobs/batch_pipelines.py"
    )

    assert "/Workspace/Users/me/.bundle/lakebase_genie_caching/dev/files" in roots


def test_missing_archive_table_error_is_detected():
    assert _is_missing_archive_table_error(
        RuntimeError(
            "SQL failed: [TABLE_OR_VIEW_NOT_FOUND] The table or view "
            "`demo_catalog`.`demo_schema`.`mlflow_traces_archived` cannot be found."
        )
    )
    assert not _is_missing_archive_table_error(RuntimeError("SQL failed: syntax error"))


def test_is_configured_space_does_not_need_module_level_config(monkeypatch):
    """The batch job imports backend.config lazily, and helpers must too.

    Regression: _is_configured_space referenced `config` at module scope, where it
    is never imported -- backend.config reads env vars at import time, so this
    module defers the import until after _apply_runtime_env has run. The result
    was NameError: name 'config' is not defined, which only appeared once the job
    ran on Spark, after every unit test had passed.
    """
    from jobs.batch_pipelines import _is_configured_space

    monkeypatch.setenv("GENIE_SPACE_IDS", "space-a,space-b")

    # Force a fresh backend.config so it picks up the env var above.
    import importlib

    import backend.config

    importlib.reload(backend.config)

    assert _is_configured_space("space-a") is True
    assert _is_configured_space("space-zzz") is False
    assert _is_configured_space(None) is False


def test_no_module_level_config_references_in_batch_job():
    """Any top-level `config.` use would fail at import on the job cluster."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "jobs" / "batch_pipelines.py").read_text()
    tree = ast.parse(src)

    # Collect names used directly in module-level statements (not inside a def).
    offenders = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id == "config":
                offenders.append(getattr(sub, "lineno", "?"))

    assert not offenders, f"module-level `config` reference at line(s) {offenders}"


def test_archive_parsing_reads_the_genie_space_id_tag():
    """The space is tagged as `genie_space_id`, not `selected_space_id`.

    Regression: the batch job read only tags["selected_space_id"], which the
    pipeline never writes -- _set_trace_metadata tags it as genie_space_id. The
    lookup therefore always returned None, and the old `or spaces[0]` fallback hid
    that by attributing every promoted entry to the first configured space. Once
    the fallback was replaced with a real space check, promotion silently skipped
    every trace instead.
    """
    import inspect
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "jobs" / "batch_pipelines.py").read_text()

    # The parsing block must consult the tag the pipeline actually writes.
    assert 'tags.get("genie_space_id")' in src, (
        "batch job does not read the genie_space_id tag, so traces have no space "
        "and promotion skips them all"
    )


def test_no_spaces_zero_fallback_remains():
    """`or config.genie.spaces[0]` silently mis-attributes foreign traces."""
    from pathlib import Path

    for name in ("jobs/batch_pipelines.py", "backend/pipelines/cache_pipeline.py"):
        src = (Path(__file__).resolve().parents[1] / name).read_text()
        assert "spaces[0].space_id if config.genie.spaces" not in src, (
            f"{name} still falls back to the first configured space"
        )
