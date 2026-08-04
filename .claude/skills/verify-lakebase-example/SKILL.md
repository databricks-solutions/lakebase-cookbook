---
name: verify-lakebase-example
description: >-
  Verify a Lakebase Cookbook contribution before opening a PR — lint with ruff,
  validate the Databricks Asset Bundle, build the Astro site, check for
  committed secrets, and produce the CONTRIBUTING.md PR checklist. Use when a
  contributor is ready to submit or wants to check their example is complete.
  Implements CONTRIBUTING.md sections 3, 5, and 6. Triggers on "verify my
  example", "check before I PR", "is my example ready", "run the checklist".
---

# Verify a Lakebase Cookbook contribution

Run the pre-PR gates from [`CONTRIBUTING.md`](../../../CONTRIBUTING.md) §3, §5,
§6 and report results honestly. Do **not** claim a step passed if it did not —
show the actual output.

## Inputs

- **`<name>`** — the example folder.
- **`<slug>`** — its doc page slug (if documented).

## Checks to run

Run each, from the repo root unless noted, and capture the real result.

### 1. Lint / format (CONTRIBUTING §5)

```bash
cd <name> && uv run ruff check . && uv run ruff format --check .
```

Report any violations. Offer to fix (`ruff check --fix`, `ruff format`).

### 2. Bundle validates (CONTRIBUTING §3)

```bash
cd <name> && databricks bundle validate -t demo
```

- If the CLI isn't configured to a workspace, this may fail on auth — say so and
  note that the contributor must run it themselves.
- **A full `bundle deploy` to a real workspace is the contributor's job** — an
  agent cannot verify a live deploy without their credentials/workspace. Remind
  them this is required before merge.

### 3. Site builds (CONTRIBUTING §4c)

```bash
make build
```

This must succeed with no errors (bad frontmatter, dead internal links, etc.
fail it). If they documented the example, confirm the page and sidebar entry
exist.

### 4. No secrets committed (CONTRIBUTING §1)

Scan the example for leaked secrets and stray env files:

```bash
git status --porcelain <name>
grep -rInE '(password|token|secret|api[_-]?key|pat)[[:space:]]*[:=]' <name> \
  --include=*.py --include=*.yml --include=*.yaml --include=*.toml --include=*.env* \
  | grep -viE '\.env\.example|placeholder|CHANGE_ME|<your|example\.com'
```

Flag anything that looks like a real credential, real workspace URL, or a
committed `.env` (only `.env.example` should be tracked). Confirm `.env` is
gitignored.

### 5. Structure sanity (CONTRIBUTING §1)

Confirm the example folder has: `README.md`, `databricks.yml`, `resources/*.yml`,
`pyproject.toml` (uv), `.env.example`, `.gitignore`. Confirm the folder name is
`snake_case` and lives under a category dir (e.g. `agents/`, `apps/`,
`developer_experience/`, `data/`).

## Output: the PR checklist

Finish by printing the CONTRIBUTING §6 checklist with each box **checked** or
**flagged with what's missing**:

- [ ] New `snake_case/` example folder under a category dir with required files
- [ ] Deployable via DABs; all workspace-specific values are variables
- [ ] Small/cheap database and compute configuration
- [ ] No secrets committed; `.env.example` provided; real files gitignored
- [ ] `uv` for deps, `ruff` clean
- [ ] Example `README.md` written
- [ ] Doc page under `site/src/content/docs/examples/`
- [ ] Listed in `examples.ts` and `intro.md`
- [ ] `make build` succeeds locally

Then remind the contributor: a maintainer merges and handles the site deploy —
Cloudflare credentials are not in the repo, so forking grants no deploy ability.
