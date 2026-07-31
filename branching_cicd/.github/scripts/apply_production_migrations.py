"""Apply pending migrations to the PRODUCTION Lakebase branch.

Runs from .github/workflows/lakebase-deploy.yml after a PR touching
migrations/ merges to main. Uses the same runner as the bundle's postdeploy
hook (scripts/migrations_runner.py), so the schema_migrations table guarantees
each file applies exactly once no matter which path ran first.

Env (same secrets as the PR validation workflow):
  DATABRICKS_HOST, DATABRICKS_TOKEN, LAKEBASE_PROJECT,
  LAKEBASE_SOURCE_BRANCH (the target; default "production"),
  LAKEBASE_DATABASE, LAKEBASE_PG_USER
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import psycopg
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from migrations_runner import apply_pending, pending_migrations  # noqa: E402

DATABRICKS_HOST = os.environ["DATABRICKS_HOST"].rstrip("/")
DATABRICKS_TOKEN = os.environ["DATABRICKS_TOKEN"]
PROJECT = os.environ["LAKEBASE_PROJECT"]
TARGET_BRANCH = os.environ.get("LAKEBASE_SOURCE_BRANCH", "production")
DATABASE = os.environ.get("LAKEBASE_DATABASE", "databricks_postgres")
PG_USER = os.environ["LAKEBASE_PG_USER"]

API = f"{DATABRICKS_HOST}/api/2.0/postgres"
JSON_HEADERS = {
    "Authorization": f"Bearer {DATABRICKS_TOKEN}",
    "Content-Type": "application/json",
}
BRANCH_PATH = f"projects/{PROJECT}/branches/{TARGET_BRANCH}"

MIGRATIONS_DIR = REPO_ROOT / "migrations"


def http(method: str, url: str, **kw) -> requests.Response:
    r = requests.request(method, url, headers=JSON_HEADERS, timeout=60, **kw)
    if not r.ok:
        print(f"::error::{method} {url} -> {r.status_code} {r.text}", file=sys.stderr)
        r.raise_for_status()
    return r


def get_primary_endpoint() -> dict:
    data = http("GET", f"{API}/{BRANCH_PATH}/endpoints").json()
    endpoints_list = data.get("endpoints", []) if isinstance(data, dict) else data
    if not endpoints_list:
        raise RuntimeError(f"No endpoints on branch {BRANCH_PATH}")
    return next(
        (
            e for e in endpoints_list
            if "READ_WRITE" in (e.get("status", {}).get("endpoint_type") or "")
        ),
        endpoints_list[0],
    )


def main() -> int:
    endpoint = get_primary_endpoint()
    host = endpoint["status"]["hosts"]["host"]
    print(f"Target: {BRANCH_PATH} ({host}/{DATABASE})")

    token = http(
        "POST", f"{API}/credentials", data=json.dumps({"endpoint": endpoint["name"]})
    ).json()["token"]

    conninfo = f"host={host} port=5432 dbname={DATABASE} user={PG_USER} sslmode=require"
    with psycopg.connect(
        conninfo, password=token, autocommit=True, prepare_threshold=None
    ) as conn:
        pending = pending_migrations(conn, MIGRATIONS_DIR)
        if not pending:
            print("No pending migrations — production is up to date.")
            return 0
        print(f"Pending: {', '.join(p.name for p in pending)}")

        for result in apply_pending(conn, MIGRATIONS_DIR):
            if result.applied:
                print(f"applied {result.filename}")
            elif result.note:
                print(f"::warning::{result.filename}: {result.note}", file=sys.stderr)

    print("Production migrations complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
