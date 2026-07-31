"""Delete the Lakebase branch created for a PR after the PR is closed/merged."""

from __future__ import annotations

import os
import re
import sys
import time

import requests

DATABRICKS_HOST = os.environ["DATABRICKS_HOST"].rstrip("/")
DATABRICKS_TOKEN = os.environ["DATABRICKS_TOKEN"]
PROJECT = os.environ["LAKEBASE_PROJECT"]
PR_NUMBER = os.environ["PR_NUMBER"]
PR_HEAD_REF = os.environ["PR_HEAD_REF"]

HEADERS = {"Authorization": f"Bearer {DATABRICKS_TOKEN}"}


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return (s or "pr")[:48]


BRANCH_PATH = f"projects/{PROJECT}/branches/pr-{PR_NUMBER}-{slugify(PR_HEAD_REF)}"


def main() -> int:
    url = f"{DATABRICKS_HOST}/api/2.0/postgres/{BRANCH_PATH}"
    r = requests.delete(url, headers=HEADERS, timeout=60)
    if r.status_code == 404:
        print(f"Branch {BRANCH_PATH} not found; nothing to clean up.")
        return 0
    if not r.ok:
        print(f"::warning::Delete branch failed: {r.status_code} {r.text}", file=sys.stderr)
        return 0
    op = r.json()
    if op.get("done"):
        print(f"Deleted {BRANCH_PATH}")
        return 0
    name = op.get("name")
    deadline = time.time() + 300
    while name and time.time() < deadline:
        time.sleep(3)
        s = requests.get(f"{DATABRICKS_HOST}/api/2.0/postgres/{name}", headers=HEADERS, timeout=30)
        if s.ok and s.json().get("done"):
            print(f"Deleted {BRANCH_PATH}")
            return 0
    print(f"::warning::Timed out waiting for branch delete on {BRANCH_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
