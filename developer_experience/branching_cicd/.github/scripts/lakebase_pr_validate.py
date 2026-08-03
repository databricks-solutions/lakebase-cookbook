"""
Validate a PR's SQL changes against a Lakebase branch.

Flow:
  1. Create a Lakebase branch off the configured source branch (named after PR branch).
  2. Poll until the branch is READY.
  3. Resolve the primary endpoint host and generate a short-lived DB credential.
  4. Execute each changed SQL file via psql against the new branch.
  5. Ask the AI Gateway (Claude on Databricks) to analyze the PR + execution results.
  6. Post the full report as a PR comment.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import requests

DATABRICKS_HOST = os.environ["DATABRICKS_HOST"].rstrip("/")
DATABRICKS_TOKEN = os.environ["DATABRICKS_TOKEN"]
PROJECT = os.environ["LAKEBASE_PROJECT"]
SOURCE_BRANCH = os.environ.get("LAKEBASE_SOURCE_BRANCH", "production")
DATABASE = os.environ.get("LAKEBASE_DATABASE", "databricks_postgres")
PG_USER = os.environ["LAKEBASE_PG_USER"]
AI_MODEL = os.environ.get("AI_GATEWAY_MODEL", "databricks-claude-opus-4-7")

PR_NUMBER = os.environ.get("PR_NUMBER", "local")
PR_TITLE = os.environ.get("PR_TITLE", "") or "(local run)"
PR_BODY = os.environ.get("PR_BODY", "") or ""
PR_HEAD_REF = os.environ.get("PR_HEAD_REF", "local")
GH_TOKEN = os.environ.get("GH_TOKEN", "")
GH_REPO = os.environ.get("GH_REPO", "")

API = f"{DATABRICKS_HOST}/api/2.0/postgres"
AUTH = {"Authorization": f"Bearer {DATABRICKS_TOKEN}"}
JSON_HEADERS = {**AUTH, "Content-Type": "application/json"}


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return (s or "pr")[:48]


BRANCH_ID = f"pr-{PR_NUMBER}-{slugify(PR_HEAD_REF)}"
BRANCH_PATH = f"projects/{PROJECT}/branches/{BRANCH_ID}"


@dataclass
class SqlResult:
    file: str
    ok: bool
    stdout: str
    stderr: str
    duration_ms: int
    stats: dict[str, Any] = field(default_factory=dict)


def http(method: str, url: str, **kw) -> requests.Response:
    r = requests.request(method, url, headers=JSON_HEADERS, timeout=60, **kw)
    if not r.ok:
        print(f"::error::{method} {url} -> {r.status_code} {r.text}", file=sys.stderr)
        r.raise_for_status()
    return r


def wait_operation(op: dict, timeout_s: int = 600) -> dict:
    if op.get("done"):
        return op
    name = op["name"]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = http("GET", f"{API}/{name}")
        data = r.json()
        if data.get("done"):
            if "error" in data:
                raise RuntimeError(f"Operation failed: {data['error']}")
            return data
        time.sleep(3)
    raise TimeoutError(f"Operation {name} did not complete in {timeout_s}s")


def create_branch() -> dict:
    existing = requests.get(f"{API}/{BRANCH_PATH}", headers=JSON_HEADERS, timeout=60)
    if existing.status_code == 200:
        print(f"Branch already exists, reusing: {BRANCH_PATH}")
        return existing.json()

    print(f"Creating Lakebase branch: {BRANCH_PATH}")
    payload = {
        "spec": {
            "source_branch": f"projects/{PROJECT}/branches/{SOURCE_BRANCH}",
            "ttl": "86400s",
        }
    }
    r = http(
        "POST",
        f"{API}/projects/{PROJECT}/branches",
        params={"branch_id": BRANCH_ID},
        data=json.dumps(payload),
    )
    op = r.json()
    result = wait_operation(op)
    print(f"Branch created: {BRANCH_PATH}")
    return result.get("response", {})


def get_primary_endpoint() -> dict:
    data = http("GET", f"{API}/{BRANCH_PATH}/endpoints").json()
    endpoints_list = data.get("endpoints", []) if isinstance(data, dict) else data
    if not endpoints_list:
        raise RuntimeError("No endpoints on branch")
    primary = next(
        (
            e for e in endpoints_list
            if "READ_WRITE" in (e.get("status", {}).get("endpoint_type") or "")
        ),
        endpoints_list[0],
    )
    return primary


def generate_credential(endpoint_name: str) -> str:
    r = http(
        "POST",
        f"{API}/credentials",
        data=json.dumps({"endpoint": endpoint_name}),
    )
    return r.json()["token"]


def run_sql(host: str, password: str, sql_file: str) -> SqlResult:
    env = {**os.environ, "PGPASSWORD": password}
    started = time.time()
    proc = subprocess.run(
        [
            "psql",
            "-h", host,
            "-p", "5432",
            "-U", PG_USER,
            "-d", DATABASE,
            "-v", "ON_ERROR_STOP=1",
            "-X",
            "-a",
            "-f", sql_file,
        ],
        env={**env, "PGSSLMODE": "require"},
        capture_output=True,
        text=True,
        timeout=600,
    )
    duration_ms = int((time.time() - started) * 1000)
    stats = collect_table_stats(host, password, sql_file)
    return SqlResult(
        file=sql_file,
        ok=proc.returncode == 0,
        stdout=proc.stdout[-8000:],
        stderr=proc.stderr[-8000:],
        duration_ms=duration_ms,
        stats=stats,
    )


TABLE_RE = re.compile(
    r"\b(?:from|join|into|update|table(?:\s+if\s+(?:not\s+)?exists)?)\s+"
    r"([a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*)?)",
    re.IGNORECASE,
)


def collect_table_stats(host: str, password: str, sql_file: str) -> dict[str, Any]:
    try:
        with open(sql_file, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {}
    tables = sorted({m.group(1) for m in TABLE_RE.finditer(text)})
    stats: dict[str, Any] = {}
    for t in tables[:10]:
        try:
            proc = subprocess.run(
                [
                    "psql", "-h", host, "-p", "5432", "-U", PG_USER, "-d", DATABASE,
                    "-tA", "-X", "-c", f"SELECT count(*) FROM {t};",
                ],
                env={**os.environ, "PGPASSWORD": password, "PGSSLMODE": "require"},
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode == 0:
                stats[t] = {"row_count": proc.stdout.strip()}
            else:
                stats[t] = {"error": proc.stderr.strip()[:200]}
        except Exception as e:
            stats[t] = {"error": str(e)[:200]}
    return stats


def read_file(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        return f"<unable to read {path}: {e}>"


def ai_analyze(results: list[SqlResult]) -> str:
    file_blocks = []
    for r in results:
        content = read_file(r.file)
        file_blocks.append(
            f"### `{r.file}` (success={r.ok}, duration_ms={r.duration_ms})\n"
            f"```sql\n{content}\n```\n"
            f"**stdout (tail):**\n```\n{r.stdout}\n```\n"
            f"**stderr (tail):**\n```\n{r.stderr}\n```\n"
            f"**table stats:** ```json\n{json.dumps(r.stats, indent=2)}\n```\n"
        )
    user_msg = (
        f"Analyze this PR's SQL changes executed against an isolated Lakebase branch.\n\n"
        f"## PR\n**Title:** {PR_TITLE}\n\n**Description:**\n{PR_BODY or '(none)'}\n\n"
        f"## Execution results\n\n" + "\n".join(file_blocks) + "\n\n"
        "## Requested analysis\n"
        "1. Summarize the intent of this change based on the PR description and SQL.\n"
        "2. Did each statement run successfully? If not, root-cause the failure.\n"
        "3. Identify any test cases listed in the PR and assess whether the "
        "executed SQL satisfies them.\n"
        "4. Highlight risks (data loss, locking, perf, indexes, constraints, RLS).\n"
        "5. Surface notable statistics from the table stats provided "
        "(row counts pre/post if inferable).\n"
        "6. Give a clear merge recommendation: APPROVE / REQUEST_CHANGES / BLOCK "
        "with one-line reason.\n"
        "Be concise and use markdown."
    )
    body = {
        "model": AI_MODEL,
        "max_tokens": 2048,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a senior database reviewer for production "
                    "Postgres changes."
                ),
            },
            {"role": "user", "content": user_msg},
        ],
    }
    r = requests.post(
        f"{DATABRICKS_HOST}/serving-endpoints/{AI_MODEL}/invocations",
        headers=JSON_HEADERS,
        data=json.dumps(body),
        timeout=180,
    )
    if not r.ok:
        r2 = requests.post(
            f"{DATABRICKS_HOST}/ai-gateway/mlflow/v1/chat/completions",
            headers=JSON_HEADERS,
            data=json.dumps(body),
            timeout=180,
        )
        r2.raise_for_status()
        r = r2
    data = r.json()
    return data["choices"][0]["message"]["content"]


def post_pr_comment(body: str) -> None:
    url = f"https://api.github.com/repos/{GH_REPO}/issues/{PR_NUMBER}/comments"
    r = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {GH_TOKEN}",
            "Accept": "application/vnd.github+json",
        },
        json={"body": body},
        timeout=30,
    )
    r.raise_for_status()


def render_comment(results: list[SqlResult], analysis: str) -> str:
    overall = all(r.ok for r in results)
    badge = "[PASS]" if overall else "[FAIL]"
    lines = [
        f"## {badge} Lakebase PR Validation",
        f"**Branch:** `{BRANCH_PATH}` (source: `{SOURCE_BRANCH}`)  ",
        f"**Database:** `{DATABASE}`  ",
        f"**Files executed:** {len(results)}",
        "",
        "### Execution",
        "| File | Result | Duration |",
        "|---|---|---|",
    ]
    for r in results:
        status = "[OK]" if r.ok else "[FAIL]"
        lines.append(f"| `{r.file}` | {status} | {r.duration_ms} ms |")
    lines += ["", "### AI Analysis", analysis, ""]
    for r in results:
        if r.stderr.strip():
            lines += [
                "<details><summary>stderr — " + r.file + "</summary>",
                "",
                "```",
                r.stderr,
                "```",
                "</details>",
                "",
            ]
    return "\n".join(lines)


def main(sql_files: list[str]) -> int:
    sql_files = [f for f in sql_files if f.strip() and os.path.exists(f)]
    if not sql_files:
        print("No SQL files to execute.")
        return 0

    create_branch()
    endpoint = get_primary_endpoint()
    host = endpoint["status"]["hosts"]["host"]
    ep_name = endpoint["name"]
    print(f"Endpoint host: {host}")
    token = generate_credential(ep_name)

    results = [run_sql(host, token, f) for f in sql_files]
    try:
        analysis = ai_analyze(results)
    except Exception as e:
        analysis = f"_AI analysis failed: {e}_"

    comment = render_comment(results, analysis)
    print(comment)
    if GH_TOKEN and GH_REPO and PR_NUMBER != "local":
        try:
            post_pr_comment(comment)
        except Exception as e:
            print(f"::warning::Failed to post PR comment: {e}", file=sys.stderr)
    else:
        print("\n(Local run: skipping GitHub PR comment.)", file=sys.stderr)

    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
