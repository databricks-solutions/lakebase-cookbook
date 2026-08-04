# Contributing to the Lakebase Cookbook

Thanks for adding to the cookbook! This guide is **prescriptive on purpose** —
follow it step by step and your example will be consistent with the rest of the
repo, deployable by anyone, and documented on
[lakebase-cookbook.com](https://lakebase-cookbook.com).

There are two deliverables for every contribution:

1. **The example** — a self-contained, deployable project in a category folder.
2. **The doc page** — a Markdown page on the cookbook site that explains it.

Both are required. An example without a doc page won't be discoverable; a doc
page without a working example isn't a cookbook entry.

---

## Let an agent walk you through it (Claude Code skills)

This repo ships **Claude Code skills** in [`.claude/skills/`](.claude/skills/)
that implement the steps below. If you're using Claude Code (they travel with
your clone/fork automatically), you can point your agent at this guide and let
the skills drive:

> "Read CONTRIBUTING.md and help me contribute a new Lakebase example."

The skills map directly to the sections in this guide:

| Skill | What it does | Sections |
|-------|--------------|----------|
| **`contribute-lakebase-example`** | Orchestrator — reads this guide and sequences the others | all |
| **`scaffold-lakebase-example`** | Creates the example folder, DAB bundle, and required files | §1–§3 |
| **`document-lakebase-example`** | Adds the site doc page and wires it into the sidebar/index/landing data | §4 |
| **`verify-lakebase-example`** | Lints, validates the bundle, builds the site, checks for secrets, prints the PR checklist | §3, §5, §6 |

Invoke the orchestrator with `/contribute-lakebase-example`, or just describe
what you want — the skills trigger on intent. The skills follow this document;
**if they ever disagree with it, this document wins.** You can also follow every
step by hand — the skills are a convenience, not a requirement.

---

## 0. Before you start

- **Open an issue or draft PR first** describing the example so a maintainer can
  confirm it's a good fit and not a duplicate.
- **Fork** the repo and work on a **feature branch** (`example/<short-name>`).
- Standard tooling for all examples:
  - **`uv`** as the package manager (not pip/poetry).
  - **`ruff`** as the linter and formatter.
  - **Databricks Asset Bundles (DABs)** for all deployable resources — no
    click-ops-only examples.
- **Keep it cheap.** Database and compute configurations must be small. Prefer
  scale-to-zero, the smallest warehouse that works, and minimal capacity. The
  cookbook is meant to be run by anyone without a surprise bill.

---

## 1. Create the example folder

Add your example as a `snake_case` folder **inside the category it belongs to**.
Examples are grouped into category folders — the current ones are
[`agents/`](agents/), [`apps/`](apps/), [`developer_experience/`](developer_experience/),
and [`data/`](data/). Put your example under the best-fit category (e.g.
`agents/my_example/`); if none fits, propose a new category folder in your issue
or PR. Use the fully worked [`apps/lakebase-fastapi/`](apps/lakebase-fastapi/)
example as your reference for structure.

### Required files

Every example folder must contain:

```
<category>/your_example/    # e.g. agents/your_example/
├── README.md              # how the example works + how to deploy (see §2)
├── databricks.yml         # DAB bundle definition (see §3)
├── resources/             # DAB resource YAMLs (app, jobs, pipelines, etc.)
│   └── *.yml
├── pyproject.toml         # deps + tool config, managed by uv
└── .gitignore             # ignore local/secret files (.env, .databricks, etc.)
```

Add whatever else the example needs (`app.py`, `notebooks/`, `backend/`, a
`docker-compose.*.yml` for local dev, etc.), but the files above are the
baseline.

### Hard rules

- **No secrets, ever.** No tokens, PATs, connection strings, workspace URLs tied
  to a real account, or `.env` files with real values. Provide a
  **`.env.example`** with placeholder keys instead, and make sure real
  equivalents are `.gitignore`d. See [`SECURITY.md`](SECURITY.md).
- **No hardcoded workspace-specific identifiers** in code paths. Anything
  workspace-specific (Lakebase database path, Genie space ID, warehouse ID,
  catalog/schema) must be a **DAB variable** the deployer overrides — see §3.
- **Parameterize Lakebase**: the database resource path, catalog, and schema are
  always variables, never constants.

---

## 2. Write the example `README.md`

Each example's `README.md` is the deep, source-of-truth documentation. The
cookbook site page (§4) is a shorter, styled mirror of it. Structure it like
[`apps/lakebase-fastapi/README.md`](apps/lakebase-fastapi/README.md):

1. **Title + one-paragraph summary** — what it does and why you'd use it.
2. **Features / what you get** — a short table.
3. **Architecture** — a diagram (ASCII is fine) and a sentence on the data flow
   and who talks to Lakebase.
4. **Deploy with Asset Bundles** — the exact, copy-pasteable steps (see §3).
   List prerequisites explicitly (Apps? Genie space? warehouse? Lakebase
   project with a specific extension like pgvector?).
5. **Configuration** — a table of every variable/setting and what it does.
6. **Local development** (if applicable) — how to run it off-platform.

Write for someone who has a Databricks workspace but has never seen your
example. Spell out every prerequisite and every variable they must set.

---

## 3. Make it deployable with Databricks Asset Bundles

All resources deploy via DABs. Model your `databricks.yml` on
[`apps/lakebase-fastapi/databricks.yml`](apps/lakebase-fastapi/databricks.yml):

- Give the bundle a unique `name`.
- Put each resource (app, job, pipeline, dashboard…) in its own file under
  `resources/*.yml` and `include:` them.
- Declare **every workspace-specific value as a `variable`** with a sensible
  `default`, and document how to override it. Lakebase paths in particular:

  ```bash
  databricks bundle deploy -t demo \
    --var lakebase_database="projects/<project>/branches/<branch>/databases/<id>"
  ```

- Provide at least one **`target`** (e.g. `demo`) and keep its compute/database
  sizing minimal.

**Verify before you PR:** from a clean checkout, run

```bash
databricks bundle validate -t demo
databricks bundle deploy -t demo
```

against a real workspace and confirm the example actually runs end to end. A PR
that hasn't been deployed from scratch will be sent back.

---

## 4. Document the example on the cookbook site

The site is an [Astro](https://astro.build/) project in [`site/`](site/). Docs
are Markdown/MDX in [`site/src/content/docs/`](site/src/content/docs/), and files
under `examples/` **appear in the sidebar automatically**. See
[`site/README.md`](site/README.md) for the full site reference.

### 4a. Add the doc page

Create `site/src/content/docs/examples/<your-example>.mdx` (use `.mdx` if you
want the `<Callout>` component; plain `.md` is fine otherwise). Copy the
frontmatter shape from an existing page such as
[`lakebase-fastapi.mdx`](site/src/content/docs/examples/lakebase-fastapi.mdx):

```mdx
---
title: Your Example — one-line descriptor
sidebar_label: Your Example        # short label for the sidebar
category: Agents                   # groups the example under a category
sidebar_position: 13               # ordering within the category
description: One sentence for SEO and social cards.
---
import Callout from '../../../components/Callout.astro';

# Your Example — one-line descriptor

A short, styled version of your README: what it does, the architecture,
how to deploy, and configuration highlights.

<Callout type="note" title="Source">
The full example lives in
[`<category>/your_example/`](https://github.com/databricks-solutions/lakebase-cookbook/tree/main/<category>/your_example).
</Callout>
```

Notes:

- **`category`** groups the example in the sidebar and on the landing page. Use
  the same category as your folder (Agents, Developer Experience, Apps, Data);
  category order lives in `src/lib/docs.ts` and `src/data/examples.ts`.
- **`sidebar_position`** controls order *within* the category; examples use the
  category's number band (Agents 10s, Developer Experience 20s, Apps 30s,
  Data 40s). Pick a value that slots your example where it belongs.
- Convert any Docusaurus-style `:::note … :::` admonitions to
  `<Callout type="info|note|tip|warning" title="…">…</Callout>`.
- **No emojis** in doc pages.
- End the page with a **Source** callout linking back to your example folder.

### 4b. Feature it on the landing / index pages

- **Landing page + docs index:** add an entry to
  [`site/src/data/examples.ts`](site/src/data/examples.ts) (`category`, `tag`,
  `title`, `bracket`, `description`, `href`, `status`) — use the same `category`
  as the doc-page frontmatter. Set `status: 'ready'` once it's fully worked, or
  `'soon'` for a stub.
- **Docs index table:** add a row to
  [`site/src/content/docs/intro.md`](site/src/content/docs/intro.md).
- If your example warrants it, you can also add a card to
  [`resources.ts`](site/src/data/resources.ts).

### 4c. Preview locally

From the repo root:

```bash
make install   # one-time
make dev       # http://localhost:3000 — check your page + sidebar
make build     # must succeed with no errors before you PR
```

`make build` is the gate — a broken build (bad frontmatter, dead internal link,
etc.) will fail CI/review.

---

## 5. Lint and format

```bash
uv run ruff check .
uv run ruff format .
```

Fix everything ruff flags in your example folder before opening the PR.

---

## 6. Open the pull request

Your PR should include, in the description:

- **What the example demonstrates** and the Lakebase capability it highlights.
- **Confirmation you deployed it from a clean checkout** (`bundle deploy`
  succeeded and the example ran).
- **Confirmation `make build` passes** for the site.
- Any prerequisites a reviewer needs to reproduce it.

### PR checklist

- [ ] New `snake_case/` example folder under a category dir with the required files (§1).
- [ ] Deployable via DABs; all workspace-specific values are variables (§3).
- [ ] Small/cheap database and compute configuration.
- [ ] No secrets committed; `.env.example` provided; real files `.gitignore`d.
- [ ] `uv` for deps, `ruff` clean.
- [ ] Example `README.md` written (§2).
- [ ] Doc page added under `site/src/content/docs/examples/` (§4a).
- [ ] Listed in `examples.ts` and `intro.md` (§4b).
- [ ] `make build` succeeds locally (§4c).

A maintainer reviews, merges, and handles the site deploy — deploying requires
Cloudflare credentials that are **not** in this repo, so forking grants no
deploy ability.

Thanks for contributing.
