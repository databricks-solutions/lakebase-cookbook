# Lakebase SCM Extension — paired Git + Lakebase branching in your IDE

The [Lakebase SCM Extension](https://github.com/databricks-solutions/lakebase-scm-extension)
is a VS Code / Cursor extension that replaces the built-in Git source control
with a unified **Git + Lakebase** SCM provider. Every code branch gets a paired
Databricks Lakebase database branch — code and schema travel together through
development, review, CI/CD, and merge.

**The problem it solves.** When an application uses Lakebase (Databricks'
Postgres-compatible database with copy-on-write branching), developers have to
keep code branches and database branches in sync. Without the extension, you
manually create database branches, refresh credentials, track schema diffs, and
clean up branches — across the CLI, the Databricks console, and GitHub. The
extension makes the code branch and the database branch one operation, surfaced
where you already work.

## What you get

| Area | What it does |
|------|--------------|
| **Paired branching** | Creating a code branch provisions a paired Lakebase database branch; they travel together through review and merge |
| **Unified SCM view** | Replaces the built-in Git provider with a combined Git + Lakebase source-control surface in the editor |
| **Credentials handled** | Short-lived database credentials are minted and refreshed for you, instead of hand-managing connection strings |
| **Project scaffold** | A "Create New Project" wizard scaffolds a Lakebase-paired repo (Java/Spring Boot, Kotlin/Spring Boot, Python/FastAPI, or Node.js/Express) |
| **Adopt existing repos** | An "Adopt" command onboards an existing Git repo to Lakebase without touching the rest of the codebase |

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| VS Code 1.85+ or Cursor | — |
| Databricks CLI v0.285+ | `brew install databricks` |
| GitHub sign-in (VS Code) or PAT | sign in when prompted, or set `lakebaseSync.githubToken` |
| PostgreSQL client (`psql`) | `brew install libpq` |
| Databricks workspace | with Lakebase enabled |

Per-language: Java/Kotlin need JVM 21+ and Maven; Python needs 3.10+ and `uv`;
Node.js needs 18+.

## Install

1. Download the `lakebase-scm-extension-*.vsix` asset from the
   [latest release](https://github.com/databricks-solutions/lakebase-scm-extension/releases/latest).
2. In VS Code: **Extensions** → `...` → **Install from VSIX** → select the file.
3. Reload the window.

Then either run **`Lakebase: Create New Project`** from the Command Palette to
scaffold a new paired project, or adopt an existing repo. See the
[extension README](https://github.com/databricks-solutions/lakebase-scm-extension)
for the full wizard walkthrough.

## How this fits with the other Developer Experience examples

- The extension is the IDE surface over
  [`lakebase_scm_utils`](../lakebase_scm_utils/), the portable engine that owns
  the branching, SCM state machine, credentials, and migrations.
- [`consort`](../consort/) uses the same engine to run its spec-first,
  test-driven agentic workflow against paired branches.

> **A pointer to an external project, not a `databricks bundle deploy`.** The
> extension ships no `databricks.yml` here — it is installed as a VSIX from
> [`databricks-solutions/lakebase-scm-extension`](https://github.com/databricks-solutions/lakebase-scm-extension)
> and run against a Lakebase-enabled workspace you provision separately. This
> folder is a guide to what it is and how to start; the source of truth is the
> extension repository.
