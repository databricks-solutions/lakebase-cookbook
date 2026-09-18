"""Point-in-time recovery for Lakebase: create a recovery branch, then repoint an app at it.

Lakebase branches are copy-on-write, so "recovery" is a branch plus a one-variable
redeploy — no restore job, no backup file. This script does the whole flow against
the Databricks Postgres and Apps APIs:

1. Create a recovery branch off a source (production) branch, as of a point in time.
2. Resolve the recovery branch's endpoint host.
3. Rewrite the target app's deployed ``app.yaml`` Lakebase env vars
   (``LAKEBASE_HOST`` + ``LAKEBASE_ENDPOINT``) to that branch.
4. Grant the app's service principal access on the recovery branch (idempotent).
5. Redeploy the app (SNAPSHOT) so it serves clean data from the recovery branch.

It is a standalone, repurposable pattern: no notebook, no ``dbutils``, no repo-specific
setup. Everything workspace-specific is an env var or a CLI flag. Authentication uses
the standard Databricks SDK resolution (``DATABRICKS_HOST`` / ``DATABRICKS_TOKEN``, a
``--profile`` in ``~/.databrickscfg``, or workspace-native auth).

Examples
--------
Recover to one hour ago and repoint an app::

    export LAKEBASE_PROJECT=my-project
    export DATABRICKS_APP_NAME=my-app
    python point_in_time_recovery.py --hours-back 1

Recover to an exact instant, only create the branch (no repoint)::

    python point_in_time_recovery.py --recovery-time 2026-08-26T14:30:00Z --no-repoint
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import sys
from datetime import UTC, datetime, timedelta

import psycopg
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.apps import AppDeployment, AppDeploymentMode
from databricks.sdk.service.postgres import Branch, BranchSpec, Timestamp
from databricks.sdk.service.workspace import ExportFormat, ImportFormat
from psycopg import sql

DEFAULT_SOURCE_BRANCH = "production"
DEFAULT_ENDPOINT = "primary"
DEFAULT_DATABASE = "databricks_postgres"
DEFAULT_SCHEMA = "public"


def _env(name: str, default: str | None = None) -> str | None:
    """Read an env var, treating empty strings as unset."""
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Create a Lakebase point-in-time recovery branch and (optionally) "
        "repoint an app at it.",
    )
    p.add_argument(
        "--project",
        default=_env("LAKEBASE_PROJECT"),
        help="Lakebase project id (env LAKEBASE_PROJECT). Required.",
    )
    p.add_argument(
        "--source-branch",
        default=_env("LAKEBASE_SOURCE_BRANCH", DEFAULT_SOURCE_BRANCH),
        help="Branch to recover from "
        f"(env LAKEBASE_SOURCE_BRANCH, default {DEFAULT_SOURCE_BRANCH}).",
    )
    p.add_argument(
        "--endpoint",
        default=_env("LAKEBASE_ENDPOINT", DEFAULT_ENDPOINT),
        help=f"Endpoint name on the branch (env LAKEBASE_ENDPOINT, default {DEFAULT_ENDPOINT}).",
    )
    p.add_argument(
        "--database",
        default=_env("LAKEBASE_DATABASE", DEFAULT_DATABASE),
        help=f"Postgres database (env LAKEBASE_DATABASE, default {DEFAULT_DATABASE}).",
    )
    p.add_argument(
        "--schema",
        default=_env("LAKEBASE_PG_SCHEMA", DEFAULT_SCHEMA),
        help=f"Schema the app reads (env LAKEBASE_PG_SCHEMA, default {DEFAULT_SCHEMA}).",
    )
    p.add_argument(
        "--app-name",
        default=_env("DATABRICKS_APP_NAME"),
        help="App to repoint (env DATABRICKS_APP_NAME). If unset, the branch is created "
        "but no app is repointed.",
    )

    when = p.add_mutually_exclusive_group()
    when.add_argument(
        "--hours-back",
        type=float,
        default=1.0,
        help="Recover to this many hours before now (UTC). Default: 1.",
    )
    when.add_argument(
        "--recovery-time",
        help="Recover to an explicit ISO-8601 instant, e.g. 2026-08-26T14:30:00Z. "
        "Naive timestamps are treated as UTC.",
    )

    p.add_argument(
        "--branch-id",
        help="Recovery branch id to create. Default: recovery-<UTC timestamp>.",
    )
    p.add_argument(
        "--no-repoint",
        action="store_true",
        help="Only create the recovery branch; do not touch any app.",
    )
    return p.parse_args(argv)


def compute_recovery_time(args: argparse.Namespace) -> datetime:
    """Resolve the point in time to recover to, as a timezone-aware UTC datetime."""
    if args.recovery_time:
        parsed = datetime.fromisoformat(args.recovery_time.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return datetime.now(UTC) - timedelta(hours=args.hours_back)


def create_recovery_branch(
    w: WorkspaceClient,
    project: str,
    source_branch: str,
    recovery_time: datetime,
    branch_id: str,
) -> Branch:
    """Create a recovery branch off ``source_branch`` as of ``recovery_time``."""
    recovery_ts = Timestamp()
    recovery_ts.FromDatetime(recovery_time)
    op = w.postgres.create_branch(
        parent=f"projects/{project}",
        branch=Branch(
            spec=BranchSpec(
                source_branch=f"projects/{project}/branches/{source_branch}",
                source_branch_time=recovery_ts,
                no_expiry=True,  # keep the recovery branch until you delete it
            )
        ),
        branch_id=branch_id,
    )
    return op.wait()


def resolve_endpoint(w: WorkspaceClient, fq_branch: str, endpoint_name: str) -> tuple[str, str]:
    """Return the (host, fully-qualified endpoint path) for a branch's endpoint."""
    endpoints = list(w.postgres.list_endpoints(fq_branch))
    if not endpoints:
        raise RuntimeError(f"No endpoint found on branch {fq_branch}.")
    host = endpoints[0].status.hosts.host
    return host, f"{fq_branch}/endpoints/{endpoint_name}"


def resolve_app_source_path(app) -> str:
    """The deployed app's own source path (from its active or pending deployment)."""
    deployment = app.active_deployment or app.pending_deployment
    source_path = deployment.source_code_path if deployment else None
    if not source_path:
        raise RuntimeError(
            f"Could not resolve the source path for app '{app.name}'. "
            "Deploy the app once before repointing it."
        )
    return source_path


def rewrite_app_yaml(
    w: WorkspaceClient, app_yaml_path: str, target_host: str, target_endpoint: str
) -> None:
    """Rewrite the deployed app.yaml's LAKEBASE_HOST + LAKEBASE_ENDPOINT env values."""
    exported = w.workspace.export(app_yaml_path, format=ExportFormat.AUTO)
    new_yaml = base64.b64decode(exported.content).decode("utf-8")
    for key, value in {"LAKEBASE_HOST": target_host, "LAKEBASE_ENDPOINT": target_endpoint}.items():
        pattern = re.compile(rf"(name:\s*{key}\s*\n\s*value:\s*)([^\s#\n]+)")
        if not pattern.search(new_yaml):
            raise RuntimeError(f"Could not find env var {key} in {app_yaml_path}.")
        new_yaml = pattern.sub(lambda m, _v=value: m.group(1) + _v, new_yaml, count=1)
    w.workspace.import_(
        app_yaml_path,
        format=ImportFormat.AUTO,
        content=base64.b64encode(new_yaml.encode()).decode(),
        overwrite=True,
    )


def grant_app_access(
    w: WorkspaceClient, app, project: str, branch: str, database: str, schema: str
) -> str:
    """Grant the app's service principal SELECT on the recovery branch (idempotent).

    A branch has its own roles, so an app repointed at a fresh branch will fail auth
    until its service principal is (re)granted here. Widen the grants below if the
    app writes as well as reads.
    """
    service_principal = app.service_principal_client_id
    fq_branch = f"projects/{project}/branches/{branch}"
    endpoint = next(iter(w.postgres.list_endpoints(fq_branch)))
    token = w.postgres.generate_database_credential(endpoint.name).token
    conn = psycopg.connect(
        host=endpoint.status.hosts.host,
        port=5432,
        dbname=database,
        user=w.current_user.me().user_name,
        password=token,
        sslmode="require",
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS databricks_auth")
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (service_principal,))
            if not cur.fetchone():
                cur.execute(
                    "SELECT databricks_create_role(%s, 'service_principal')", (service_principal,)
                )
            role = sql.Identifier(service_principal)
            db_ident = sql.Identifier(database)
            schema_ident = sql.Identifier(schema)
            cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(db_ident, role))
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema_ident, role))
            cur.execute(
                sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(schema_ident, role)
            )
            cur.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT ON TABLES TO {}"
                ).format(schema_ident, role)
            )
    finally:
        conn.close()
    return service_principal


def redeploy_app(w: WorkspaceClient, app_name: str, source_path: str) -> str:
    """Redeploy the app (SNAPSHOT) so it picks up the rewritten app.yaml. Returns its URL."""
    deployment = w.apps.deploy_and_wait(
        app_name,
        AppDeployment(source_code_path=source_path, mode=AppDeploymentMode.SNAPSHOT),
    )
    state = deployment.status.state.value if deployment.status and deployment.status.state else None
    if state != "SUCCEEDED":
        raise RuntimeError(f"Deployment did not succeed (state={state}).")
    return w.apps.get(app_name).url


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if not args.project:
        sys.exit("LAKEBASE_PROJECT is required (set the env var or pass --project).")

    w = WorkspaceClient()
    recovery_time = compute_recovery_time(args)
    branch_id = args.branch_id or f"recovery-{recovery_time.strftime('%Y%m%d-%H%M%S')}"

    print(f"Recovery point (UTC) : {recovery_time.isoformat()}")
    print(f"Recovery branch      : {branch_id} (from '{args.source_branch}')")
    branch = create_recovery_branch(w, args.project, args.source_branch, recovery_time, branch_id)
    print(f"Recovery branch created: {branch.name}")

    fq_branch = f"projects/{args.project}/branches/{branch_id}"
    host, endpoint_path = resolve_endpoint(w, fq_branch, args.endpoint)
    print(f"Target host          : {host}")
    print(f"Target endpoint      : {endpoint_path}")

    if args.no_repoint or not args.app_name:
        print(
            "\nBranch is ready. No app repointed "
            "(pass --app-name / set DATABRICKS_APP_NAME to repoint one)."
        )
        return

    app = w.apps.get(args.app_name)
    source_path = resolve_app_source_path(app)
    app_yaml_path = f"{source_path}/app.yaml"
    print(f"\nApp {args.app_name} | source {source_path}")

    rewrite_app_yaml(w, app_yaml_path, host, endpoint_path)
    print(f"Rewrote app.yaml -> {endpoint_path}")

    service_principal = grant_app_access(
        w, app, args.project, branch_id, args.database, args.schema
    )
    print(f"Granted app SP {service_principal} access on schema '{args.schema}'.")

    url = redeploy_app(w, args.app_name, source_path)
    print(f"\n{args.app_name} is live on recovery branch '{branch_id}': {url}")


if __name__ == "__main__":
    main()
