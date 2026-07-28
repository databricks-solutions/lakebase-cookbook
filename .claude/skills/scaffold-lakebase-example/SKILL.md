---
name: scaffold-lakebase-example
description: >-
  Scaffold a new Lakebase Cookbook example folder — the top-level snake_case
  directory with a Databricks Asset Bundle (databricks.yml + resources/),
  pyproject.toml (uv), README.md, .env.example, and .gitignore. Use when a
  contributor is starting a new example and needs the standard file layout and
  DAB templates. Implements CONTRIBUTING.md sections 1–3. Triggers on "scaffold
  an example", "start a new Lakebase example", "set up the example folder".
---

# Scaffold a Lakebase Cookbook example

Create a new, deployable example folder that matches the repo conventions and
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md) §1–§3. The reference implementation
is [`genie_caching/`](../../../genie_caching/) — mirror its structure.

## Inputs to collect first

- **`<name>`** — the example name in `snake_case`. This is the top-level folder.
- **`<title>`** — human title, e.g. "Vector Search Reranking".
- **`<description>`** — one sentence.
- **Resources deployed** — app / job / pipeline / dashboard / etc.
- **Workspace-specific values** the deployer must supply — each becomes a DAB
  **variable** (Lakebase database path, branch, catalog, schema; Genie space ID;
  warehouse ID; serving endpoint; …).

If any are missing, ask before scaffolding.

## What to create

Create `<name>/` at the **repo root** with these files. Templates live in this
skill's [`templates/`](templates/) directory — copy them and substitute the
placeholders (`__NAME__`, `__TITLE__`, `__DESCRIPTION__`, `__BUNDLE_NAME__`).

```
<name>/
├── README.md              # from templates/README.md.tmpl
├── databricks.yml         # from templates/databricks.yml.tmpl
├── resources/
│   └── <name>.app.yml      # from templates/resource.app.yml.tmpl (or a job/pipeline resource)
├── pyproject.toml         # from templates/pyproject.toml.tmpl
├── .env.example           # from templates/.env.example.tmpl
└── .gitignore             # from templates/.gitignore.tmpl
```

Add source files the example actually needs (`app.py`, `notebooks/`,
`backend/`, `src/<name>/`, etc.). Keep the six files above as the baseline.

## Rules to enforce while scaffolding

- **Every workspace-specific value is a DAB `variable`** with a sensible
  `default` and a comment on how to override it. Never hardcode a Lakebase path,
  Genie space ID, or warehouse ID in code.
- **Parameterize Lakebase**: `lakebase_branch`, `lakebase_database`,
  `lakebase_catalog`, `lakebase_schema` are always variables (see the reference
  `databricks.yml`).
- **No secrets.** Only `.env.example` with placeholder keys; ensure real `.env`
  files are gitignored (the template does this).
- **Small/cheap sizing.** Use the smallest `compute_size`/warehouse that works;
  prefer scale-to-zero. Call this out in a comment.
- **`uv` + `ruff`.** The `pyproject.toml` template configures both.

## Choosing the resource file

- **App** (like `genie_caching`): use `templates/resource.app.yml.tmpl`.
- **Job / pipeline / dashboard**: replace the `apps:` block with the appropriate
  DAB resource type. Look up the exact schema in the `databricks-dabs` skill or
  the Databricks docs rather than guessing — if that skill is available, defer to
  it for non-app resources.

## After scaffolding

Tell the contributor:

1. Fill in the source code and the README's architecture/config sections.
2. **Deploy from a clean checkout to a real workspace** to prove it works:
   ```bash
   databricks bundle validate -t demo
   databricks bundle deploy -t demo --var lakebase_database="projects/<project>/branches/<branch>/databases/<id>"
   ```
   An agent cannot do this for them — it needs their workspace + credentials.
3. When the example runs, move on to **`document-lakebase-example`**.
