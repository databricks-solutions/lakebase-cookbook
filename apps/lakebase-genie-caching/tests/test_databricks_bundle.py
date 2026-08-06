"""Tests for Databricks Asset Bundle resource configuration."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _bundle() -> dict:
    with (ROOT / "databricks.yml").open() as f:
        return yaml.safe_load(f)


def test_batch_job_runs_archive_before_pipeline():
    job = _bundle()["resources"]["jobs"]["batch_pipelines"]
    tasks = {task["task_key"]: task for task in job["tasks"]}

    assert {"archive_fresh", "batch_pipelines"}.issubset(tasks)
    assert tasks["archive_fresh"]["run_job_task"]["job_id"] == "${resources.jobs.trace_archive.id}"
    assert tasks["batch_pipelines"]["depends_on"] == [{"task_key": "archive_fresh"}]
    assert tasks["batch_pipelines"]["spark_python_task"]["python_file"] == "jobs/batch_pipelines.py"


def test_batch_job_passes_autoscaling_runtime_config():
    task = next(
        task
        for task in _bundle()["resources"]["jobs"]["batch_pipelines"]["tasks"]
        if task["task_key"] == "batch_pipelines"
    )
    params = task["spark_python_task"]["parameters"]

    expected_pairs = {
        "--lakebase-project": "${var.lakebase_project}",
        "--warehouse-id": "${var.warehouse_id}",
        "--genie-space-ids": "${var.genie_space_ids}",
        "--trace-archive-catalog": "${var.trace_archive_catalog}",
        "--trace-archive-schema": "${var.trace_archive_schema}",
        "--trace-archive-table": "${var.trace_archive_table}",
        "--mlflow-experiment-name": "${var.mlflow_experiment_name}",
        "--classifier-llm-endpoint": "${var.classifier_llm_endpoint}",
        "--assistant-llm-endpoint": "${var.assistant_llm_endpoint}",
        "--workspace-source-root": "${workspace.file_path}",
    }
    actual_pairs = dict(zip(params[::2], params[1::2]))

    for flag, value in expected_pairs.items():
        assert actual_pairs[flag] == value


def test_trace_archive_variables_are_declared():
    variables = _bundle()["variables"]

    assert variables["trace_archive_table"]["default"] == "mlflow_traces_archived"


def test_bundle_declares_lakebase_autoscaling_project():
    resources = _bundle()["resources"]

    assert "database_instances" not in resources
    project = resources["postgres_projects"]["genie_cache_db"]
    assert project["project_id"] == "${var.lakebase_project}"
    assert project["pg_version"] == 17


def test_app_uses_setup_for_lakebase_autoscaling_permissions():
    app = _bundle()["resources"]["apps"]["genie_cache"]
    resources = {resource["name"]: resource for resource in app["resources"]}

    assert "postgres" not in resources
    assert app["config"]["env"][1] == {
        "name": "LAKEBASE_PROJECT",
        "value": "${var.lakebase_project}",
    }


def test_app_attaches_batch_and_trace_archive_jobs():
    app = _bundle()["resources"]["apps"]["genie_cache"]
    resources = {resource["name"]: resource for resource in app["resources"]}

    assert resources["batch-job"]["job"]["id"] == "${resources.jobs.batch_pipelines.id}"
    assert resources["trace-archive-job"]["job"]["id"] == "${resources.jobs.trace_archive.id}"
    assert resources["trace-archive-job"]["job"]["permission"] == "CAN_MANAGE_RUN"


def test_trace_archive_job_is_bundle_managed():
    jobs = _bundle()["resources"]["jobs"]
    archive_job = jobs["trace_archive"]
    task = archive_job["tasks"][0]

    assert archive_job["name"] == "[${resources.experiments.genie_cache_experiment.id}] Trace Archive Job"
    assert archive_job["tags"] == {"project": "lakebase-genie-caching", "type": "trace-archive"}
    assert task["python_wheel_task"]["package_name"] == "databricks_agents_monitoring"
    assert task["python_wheel_task"]["entry_point"] == "archive_job"
    assert (
        task["python_wheel_task"]["named_parameters"]["experiment_id"]
        == "${resources.experiments.genie_cache_experiment.id}"
    )
    assert (
        task["python_wheel_task"]["named_parameters"]["trace_archive_table_fullname"]
        == "`${var.trace_archive_catalog}`.`${var.trace_archive_schema}`.`${var.trace_archive_table}`"
    )


def test_app_receives_the_bundle_experiment_id():
    """The app must be given the experiment ID, not only its name.

    Regression: in development mode the bundle prefixes resource names, so an app
    told only "/lakebase-genie-caching" fails to resolve it and calls set_experiment,
    which tries to CREATE an experiment at the workspace root. The app's service
    principal cannot, so it failed with PERMISSION_DENIED on aclPath /workspace
    and tracing degraded silently -- taking thumbs-up feedback and therefore cache
    promotion with it.
    """
    app = _bundle()["resources"]["apps"]["genie_cache"]
    env = {item["name"]: item["value"] for item in app["config"]["env"]}

    assert env["MLFLOW_EXPERIMENT_ID"] == "${resources.experiments.genie_cache_experiment.id}"


def test_batch_job_receives_the_bundle_experiment_id():
    task = next(
        task
        for task in _bundle()["resources"]["jobs"]["batch_pipelines"]["tasks"]
        if task["task_key"] == "batch_pipelines"
    )
    params = task["spark_python_task"]["parameters"]
    pairs = dict(zip(params[::2], params[1::2]))

    assert pairs["--mlflow-experiment-id"] == "${resources.experiments.genie_cache_experiment.id}"


def test_app_declares_user_api_scopes_for_obo():
    """Without these scopes Genie rejects the forwarded token with a 403."""
    app = _bundle()["resources"]["apps"]["genie_cache"]
    scopes = set(app["user_api_scopes"])

    # `genie` is the string the Genie Conversation API enforces; the Apps API
    # accepts `dashboards.genie` too, which is why the wrong one is easy to ship.
    assert "sql" in scopes
    assert "genie" in scopes


def test_targets_do_not_pin_a_workspace_host():
    """A pinned host makes every deploy fail with a profile/bundle host mismatch."""
    for name, target in _bundle()["targets"].items():
        host = (target.get("workspace") or {}).get("host")
        assert not host, f"target {name!r} pins a host ({host}); let --profile supply it"
