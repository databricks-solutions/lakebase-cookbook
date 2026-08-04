# CI scripts

Python scripts behind the two workflows in `.github/workflows/`, plus a local
runner that exercises the same code path without GitHub.

| Script | Used by | What it does |
|---|---|---|
| `lakebase_pr_validate.py` | `lakebase-pr-validate.yml` (PR open/update) | Creates a Lakebase branch `pr-<num>-<slug>` off `production` (24h TTL), runs the PR's changed SQL files against it via `psql`, collects row-count stats, asks AI Gateway for an impact analysis, and posts the report as a PR comment. Exit code mirrors SQL success. |
| `lakebase_pr_cleanup.py` | `lakebase-pr-validate.yml` (PR closed) | Deletes the PR's Lakebase branch. |
| `apply_production_migrations.py` | `lakebase-deploy.yml` (push to main) | Applies pending migrations to the `production` branch using the shared runner (`scripts/migrations_runner.py`), so each file applies exactly once. |
| `run_local.sh` | you | Runs the PR validation locally against a real Lakebase branch using your CLI profile — no GitHub required. Skips the PR comment. |

## Required GitHub secrets

| Secret | Example | Notes |
|---|---|---|
| `DATABRICKS_HOST` | `https://<workspace>.cloud.databricks.com` | No trailing slash |
| `DATABRICKS_TOKEN` | `dapi...` | PAT (or SP OAuth token) with Lakebase permissions on the project |
| `LAKEBASE_PROJECT` | `lakebase-manufacturing` | Project id of the Lakebase project whose `production` branch you provisioned |
| `LAKEBASE_SOURCE_BRANCH` | `production` | Branch PRs fork from / deploys apply to |
| `LAKEBASE_DATABASE` | `databricks_postgres` | Postgres database name |
| `LAKEBASE_PG_USER` | `you@company.com` | Postgres role used for connections (the token's identity) |
| `AI_GATEWAY_MODEL` | `databricks-claude-opus-4-7` | Serving endpoint used for the AI review |

## Local run

```bash
databricks auth login                      # once
./.github/scripts/run_local.sh migrations/003_your_change.sql
./.github/scripts/run_local.sh             # auto-detects changed files vs main
```

Overrides: `DATABRICKS_CONFIG_PROFILE`, plus any of the env vars in the
secrets table above.
