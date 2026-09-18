# Point-in-time recovery — recover a branch and repoint an app

A standalone, repurposable script that recovers Lakebase data to an earlier
point in time using **branching**, then repoints a running Databricks App at the
recovered data. Because Lakebase branches are copy-on-write, "recovery" is a
branch created *as of a past timestamp* plus a one-variable redeploy — no restore
job, no backup file, and the live branch is left untouched so you can compare
before cutting over.

Use it after a bad deploy, a runaway `UPDATE`/`DELETE`, or any data corruption:
create a branch from just before the damage, verify it, and point the app there.

## Features

| Area | What you get |
|------|--------------|
| **Point-in-time branch** | Fork a recovery branch off any source branch *as of* an exact instant or N hours ago — copy-on-write, ready in seconds |
| **App repoint** | Rewrite the deployed app's `app.yaml` Lakebase env vars (`LAKEBASE_HOST` + `LAKEBASE_ENDPOINT`) and redeploy (SNAPSHOT) — same app, same code, only the branch changes |
| **Access re-grant** | Idempotently (re)grant the app's service principal on the new branch, so the repointed app doesn't fail auth |
| **Branch-only mode** | `--no-repoint` creates and reports the branch (host + endpoint) without touching any app, for manual inspection first |
| **Repurposable** | Pure Python + the Databricks SDK — no notebook, no `dbutils`, no repo-specific setup; every workspace value is an env var or CLI flag |

## Architecture

```
   source branch (e.g. production)          recovery branch
   ─────────────────────────────            ────────────────
   corrupted "now"                          clean, as of T-1h
          │                                        ▲
          │  create_branch(source_branch_time=T)   │ copy-on-write
          └────────────────────────────────────────┘
                                 │
                                 ▼
        rewrite app.yaml (LAKEBASE_HOST + LAKEBASE_ENDPOINT)
                                 │
                                 ▼
        grant app service principal on the recovery branch
                                 │
                                 ▼
        redeploy app (SNAPSHOT) ──►  app serves clean data
```

The script talks to two Databricks APIs: **Postgres** (create the branch, list its
endpoint, mint a credential to run the grants) and **Apps** (read the deployed
source path, rewrite `app.yaml` in the workspace, redeploy).

## Run it

This is a **reference script you run against your own workspace** (see the note
at the bottom). Prerequisites:

- A **Lakebase** project with a source branch that has point-in-time history
  (e.g. `production`) and a primary endpoint.
- The `databricks` CLI authenticated (`databricks auth login`) or
  `DATABRICKS_HOST` + `DATABRICKS_TOKEN` exported, and **`uv`**.
- To use the repoint step: a deployed Databricks App whose `app.yaml` sets
  `LAKEBASE_HOST` and `LAKEBASE_ENDPOINT` env vars.

```bash
cd developer_experience/point_in_time_recovery
uv sync

# Configure — copy .env.example to .env and fill it in, or export the vars:
export LAKEBASE_PROJECT=<your-lakebase-project-id>
export DATABRICKS_APP_NAME=<your-app-name>

# Recover to one hour ago and repoint the app:
uv run scripts/point_in_time_recovery.py --hours-back 1

# Or recover to an exact instant, branch only (inspect before repointing):
uv run scripts/point_in_time_recovery.py \
  --recovery-time 2026-08-26T14:30:00Z --no-repoint
```

`--no-repoint` (or omitting `--app-name` / `DATABRICKS_APP_NAME`) creates the
branch and prints its host and endpoint so you can connect and verify the data
before cutting the app over.

## Configuration

Every value is an env var with a matching CLI flag (the flag wins). Run
`uv run scripts/point_in_time_recovery.py --help` for the full list.

| Env var / flag | Purpose | Default |
|----------------|---------|---------|
| `LAKEBASE_PROJECT` / `--project` | Lakebase project id. **Required.** | — |
| `LAKEBASE_SOURCE_BRANCH` / `--source-branch` | Branch to recover from. | `production` |
| `LAKEBASE_ENDPOINT` / `--endpoint` | Endpoint name on the branch. | `primary` |
| `LAKEBASE_DATABASE` / `--database` | Postgres database. | `databricks_postgres` |
| `LAKEBASE_PG_SCHEMA` / `--schema` | Schema the app reads (used for the grants). | `public` |
| `DATABRICKS_APP_NAME` / `--app-name` | App to repoint. Unset ⇒ branch only. | — |
| `--hours-back` | Recover to N hours before now (UTC). | `1` |
| `--recovery-time` | Recover to an explicit ISO-8601 instant (overrides `--hours-back`). | — |
| `--branch-id` | Recovery branch id to create. | `recovery-<UTC timestamp>` |
| `--no-repoint` | Only create the branch; never touch an app. | off |

Authentication uses the standard Databricks SDK resolution — a `--profile` in
`~/.databrickscfg`, `DATABRICKS_CONFIG_PROFILE`, or `DATABRICKS_HOST` +
`DATABRICKS_TOKEN`.

## Notes and caveats

- **The grants are read-only** (`SELECT`/`USAGE`). If your app writes to Lakebase,
  widen the grants in `grant_app_access()` accordingly.
- **The recovery branch is created with `no_expiry`** so it survives until you
  delete it. Branches are copy-on-write and cheap, but delete the ones you no
  longer need. To cut a repointed app back to `production`, rerun the app's normal
  deploy (it re-renders `app.yaml`), or repoint it at `production` the same way.
- **The repoint edits the *deployed* `app.yaml` in place.** A subsequent
  `databricks bundle deploy` of the app re-renders `app.yaml` from source and
  reverts the repoint — expected, since production is the steady state.

---

> **This is a reference script, not a `databricks bundle deploy`.** Like the
> `branching_cicd` example, it ships no `databricks.yml` — it deploys no resources
> of its own. It is an operational recovery utility you run against a Lakebase
> project and an app you already have. Adapted from a Databricks Field Engineering
> app-developer reference project; this cookbook version isolates the
> point-in-time-recovery pattern.
