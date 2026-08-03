# Migrations

Plain-SQL migrations applied in filename order. Each file runs exactly once and
is recorded in the `schema_migrations` table (created automatically by the
runner in `scripts/migrations_runner.py`).

## Conventions

- **Naming:** `NNN_short_description.sql` — zero-padded, strictly increasing.
  Lexicographic order is execution order.
- **Immutable once merged:** never edit a migration that has been applied to
  production; add a new one. The runner records a checksum and warns on drift.
- **One transaction per file:** each file is applied inside a single
  transaction and rolled back entirely on failure. Avoid statements that can't
  run in a transaction block (e.g. `CREATE INDEX CONCURRENTLY`).
- **Idempotent DDL preferred** (`IF NOT EXISTS`) so files are also safe to run
  by hand against a scratch branch.

## How migrations reach each environment

| Path | Trigger | What runs |
|---|---|---|
| Pull request | PR touching `migrations/**/*.sql` | `.github/workflows/lakebase-pr-validate.yml` forks a Lakebase branch off `production`, executes only the changed files there, and posts an AI-generated impact report on the PR |
| Merge to `main` | Push to `main` touching `migrations/**/*.sql` | `.github/workflows/lakebase-deploy.yml` applies pending migrations to the `production` branch, exactly once (via the `schema_migrations` table) |

`001`/`002` here are a baseline manufacturing-telemetry schema and seed data so
the workflow has something real to fork and validate against. To exercise the PR
workflow, add a new `003_*.sql` on a feature branch and open a PR — the
validation action runs it against a throwaway branch off `production` and reports
back.
