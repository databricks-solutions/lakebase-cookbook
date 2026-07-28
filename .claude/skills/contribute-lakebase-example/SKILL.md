---
name: contribute-lakebase-example
description: >-
  End-to-end guide for contributing a new example to the Lakebase Cookbook
  repository. Use when a contributor wants to add, build, document, or submit a
  Lakebase example (a new top-level example folder + its cookbook site doc
  page). Orchestrates scaffolding, documentation, and verification, following
  CONTRIBUTING.md. Triggers on "add an example", "contribute to the cookbook",
  "new Lakebase example", "document my example", or pointing an agent at
  CONTRIBUTING.md.
---

# Contribute a Lakebase Cookbook example

You are helping a contributor add a new example to the **Lakebase Cookbook**
repo. This skill is the entry point; it sequences three focused skills, each
matching a stage of [`CONTRIBUTING.md`](../../../CONTRIBUTING.md):

1. **`scaffold-lakebase-example`** — create the example folder, DAB bundle, and
   required files (CONTRIBUTING §1–§3).
2. **`document-lakebase-example`** — add the cookbook site doc page and wire it
   into the sidebar/index/landing data (CONTRIBUTING §4).
3. **`verify-lakebase-example`** — lint, build the site, validate the bundle,
   and produce the PR checklist (CONTRIBUTING §3, §5, §6).

## First: read the source of truth

Before doing anything, **read [`CONTRIBUTING.md`](../../../CONTRIBUTING.md) in
full.** It is the authoritative spec; these skills implement it. If this skill
and CONTRIBUTING.md ever disagree, CONTRIBUTING.md wins — and you should flag the
drift to the contributor.

Also skim the fully worked reference example
[`genie_caching/`](../../../genie_caching/) — every scaffold decision mirrors it.

## Orient before acting

Confirm you are working in the `lakebase-cookbook` repo (top-level folders like
`ai_memory/`, `genie_caching/`, and a `site/` directory). Then ask the
contributor for the essentials if not already given:

- **Example name** (`snake_case`, e.g. `vector_search_rerank`).
- **One-line description** of what it demonstrates and which Lakebase capability
  it highlights.
- **What resources it deploys** (App? Job? Pipeline? Dashboard?).
- **What it needs from the workspace** (Lakebase project/branch/database, Genie
  space, SQL warehouse, model serving endpoint, etc.) — these become DAB
  variables.

## Then sequence the work

Run the three skills **in order**, checking in with the contributor between
stages. Do not skip verification. After each stage, tell the contributor what
was created and what they must do themselves (e.g. actually deploying the bundle
to a real workspace — an agent cannot fully verify a deploy without their
credentials and workspace).

## Guardrails (enforce throughout)

- **No secrets, ever** — no tokens, PATs, real workspace URLs, or populated
  `.env` files. Only `.env.example` with placeholders.
- **Everything workspace-specific is a DAB variable**, never hardcoded.
- **Small/cheap** database and compute sizing.
- **`uv`** for packaging, **`ruff`** clean, **DABs** for all deployable
  resources.
- **No emojis** in cookbook doc pages.

## Finish

End by presenting the completed **PR checklist** from CONTRIBUTING §6 with each
item ticked or flagged, and remind the contributor that a maintainer handles the
site deploy (Cloudflare credentials are not in the repo).
