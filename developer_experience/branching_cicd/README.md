# Branching CI/CD — validate schema changes on a Lakebase branch

A reference GitHub CI/CD workflow that uses **Lakebase branching** to move
database schema changes to production with confidence. Every pull request that
touches `migrations/` forks a short-lived Lakebase branch off `production` — a
copy-on-write copy of the production schema *and data*, ready in seconds — runs
the changed SQL there, has an AI Gateway model analyze the impact, and posts the
report on the PR. Merging applies the migration to production exactly once;
closing the PR deletes the branch.

Schema changes never touch production directly, and reviewers see a real
execution result (plus an AI risk assessment) before they approve.

## Features

| Area | What you get |
|------|--------------|
| **Branch-per-PR** | Each PR forks an isolated Lakebase branch off `production` (24h TTL) and runs the changed SQL against real prod-shaped data |
| **AI impact review** | AI Gateway (Claude on Databricks) summarizes intent, flags risks (data loss, locking, constraints), checks the PR's stated test cases, and gives an APPROVE / REQUEST_CHANGES / BLOCK call — posted as a PR comment |
| **Exactly-once deploy** | Merge to `main` applies pending migrations to `production`; a `schema_migrations` table (checksum-tracked) guarantees each file applies once and flags drift |
| **Auto cleanup** | Closing the PR deletes its Lakebase branch |
| **Local dry-run** | `run_local.sh` runs the identical validation from your machine — no GitHub required |

## Architecture

```
            ┌───────────────── your repo ─────────────────┐
            │ migrations/*.sql   scripts/   .github/        │
            └──────┬───────────────────────────┬───────────┘
   PR opened       │                merge to main
        │          │                           │
        ▼          │                           ▼
  ┌──────────────┐ │                  ┌──────────────────┐
  │ Lakebase     │ │                  │ apply pending    │
  │ branch:      │◀┘ forked from      │ migrations to    │
  │ pr-<n>-<slug>│   production       │ production branch│
  └──────┬───────┘                    └──────────────────┘
         │
         ▼
  run changed SQL  →  AI Gateway impact analysis  →  PR comment
         │
         ▼
  PR closed  →  delete branch
```

Two workflows drive it:

- **`.github/workflows/lakebase-pr-validate.yml`** — on PR open/update, forks the
  branch, runs the changed SQL via `psql`, collects row-count stats, calls AI
  Gateway, and comments. On PR close, deletes the branch.
- **`.github/workflows/lakebase-deploy.yml`** — on push to `main` touching
  `migrations/`, applies pending migrations to `production` via the shared
  runner (`scripts/migrations_runner.py`).

## Prerequisites

This example is a **reference workflow you lift into your own repository** — see
the note at the bottom. Before it can run you need:

- A **Lakebase Autoscaling** project with a long-lived **`production`** branch
  and a primary READ_WRITE endpoint. (Provision it however you like — a
  Databricks Asset Bundle with `postgres_projects` / `postgres_branches` /
  `postgres_endpoints` resources, the Postgres APIs, or Catalog Explorer.)
- A model-serving / **AI Gateway** chat endpoint for the impact review
  (`AI_GATEWAY_MODEL`, e.g. `databricks-claude-opus-4-7`).
- The `databricks` CLI and `uv` for local runs.

## Set it up

1. **Copy these directories into your repository root** (the workflows only run
   from a repo's root `.github/`):

   ```
   .github/workflows/   .github/scripts/   scripts/   migrations/
   ```

2. **Add the GitHub secrets** the workflows read (repo → Settings → Secrets and
   variables → Actions). Full table in
   [`.github/scripts/README.md`](.github/scripts/README.md):

   | Secret | Example |
   |--------|---------|
   | `DATABRICKS_HOST` | `https://<workspace>.cloud.databricks.com` |
   | `DATABRICKS_TOKEN` | PAT or SP OAuth token with Lakebase permissions |
   | `LAKEBASE_PROJECT` | your Lakebase project id |
   | `LAKEBASE_SOURCE_BRANCH` | `production` |
   | `LAKEBASE_DATABASE` | `databricks_postgres` |
   | `LAKEBASE_PG_USER` | the Postgres role / user email |
   | `AI_GATEWAY_MODEL` | `databricks-claude-opus-4-7` |

3. **Author migrations** as `migrations/NNN_description.sql` (zero-padded, strictly
   increasing — see [`migrations/README.md`](migrations/README.md)). `001`/`002`
   here are a baseline manufacturing-telemetry schema + seed data so the branch
   has something real to validate against.

4. **Open a PR** that adds a migration → the validation action forks a branch,
   runs your SQL, and comments with the AI review. Merge → the deploy action
   applies it to `production`.

## Local dry-run

Run the same validation from your machine (skips the PR comment):

```bash
databricks auth login                         # once
./.github/scripts/run_local.sh migrations/003_your_change.sql
./.github/scripts/run_local.sh                # auto-detects changed files vs main
```

It reads your `~/.databrickscfg` profile, mints a short-lived token, forks the
Lakebase branch, runs the SQL, and prints the AI analysis locally.

## How exactly-once works

Both the merge-to-`main` deploy and any postdeploy hook you add call
`scripts/migrations_runner.py`, which records every applied file in a
`schema_migrations` table with a content checksum. Already-applied files are
skipped; a file whose content changed after it was applied is reported as
**drift** (add a new migration instead of editing an applied one). Each file
runs in its own transaction and rolls back entirely on failure.

---

> **This is a reference workflow, not a `databricks bundle deploy`.** Unlike the
> other cookbook examples, it ships no `databricks.yml` — the assets are meant to
> be copied into *your* repository, where the GitHub Actions run against a
> Lakebase project you provision separately (see Prerequisites). Adapted from a
> Databricks Field Engineering app-developer reference project; this cookbook
> version isolates the branching-CI/CD story.
