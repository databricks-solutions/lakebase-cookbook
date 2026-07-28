---
name: document-lakebase-example
description: >-
  Add a Lakebase Cookbook example's documentation page to the Astro site and
  wire it into the sidebar, docs index, and landing-page data. Use after an
  example folder exists and needs to appear on lakebase-cookbook.com. Implements
  CONTRIBUTING.md section 4. Triggers on "document my example", "add my example
  to the site", "create the doc page", "add it to the cookbook site".
---

# Document a Lakebase Cookbook example on the site

Add the site doc page for an existing example and wire it into the navigation,
per [`CONTRIBUTING.md`](../../../CONTRIBUTING.md) §4. The site is an Astro project
in [`site/`](../../../site/) — see [`site/README.md`](../../../site/README.md).

## Inputs

- **`<name>`** — the example folder name (`snake_case`).
- **`<slug>`** — the doc page slug (`kebab-case`, usually the folder name with
  underscores → hyphens, e.g. `feature_store` → `feature-store`).
- **`<title>`**, **`<sidebar_label>`**, **`<description>`**.
- A short list of the key points to surface (architecture, deploy, config).

## Steps

### 1. Create the doc page

Create `site/src/content/docs/examples/<slug>.mdx` from this skill's
[`templates/example.mdx.tmpl`](templates/example.mdx.tmpl). Substitute
`__TITLE__`, `__SIDEBAR_LABEL__`, `__DESCRIPTION__`, `__NAME__`, `__SLUG__`, and
`__SIDEBAR_POSITION__`.

- **`sidebar_position`** orders the sidebar; existing examples use 10, 20, 30…
  Read the other files in `site/src/content/docs/examples/` and pick a value that
  slots this example where it belongs. (`genie-caching` = 10.)
- Use `.mdx` (not `.md`) if you use the `<Callout>` component. Import it from
  `../../../components/Callout.astro`.
- Convert any Docusaurus-style `:::note … :::` admonitions to
  `<Callout type="info|note|tip|warning" title="…">…</Callout>`.
- **No emojis.**
- The page is a shorter, styled mirror of the example's own `README.md` — do not
  duplicate the whole README; summarize and link to the source.
- **End with a Source callout** linking to the example folder on GitHub.

The sidebar picks up the new file automatically (folder = group,
`sidebar_position` = order — see `site/src/lib/docs.ts`). No sidebar config edit
needed.

### 2. Feature it in the landing + docs index data

- **`site/src/data/examples.ts`** — append an `ExampleCard` entry:
  `{ tag, title, bracket, description, href: '/docs/examples/<slug>/', status }`.
  Use `status: 'ready'` for a fully worked example, `'soon'` for a stub. Match
  the tone of the existing entries (the `bracket` field is the short mono
  `[like this]` phrase).
- **`site/src/content/docs/intro.md`** — add a row to the examples table
  pointing at `/docs/examples/<slug>/`.
- Optionally add a card to **`site/src/data/resources.ts`** if it warrants a
  resource link.

### 3. Preview

From the repo root:

```bash
make dev     # http://localhost:3000 — check the page renders and the sidebar shows it
make build   # MUST succeed with no errors before the PR
```

If a visual check matters, follow the CLAUDE.md workflow (build, load with the
chrome-devtools MCP, screenshot).

## After documenting

Move on to **`verify-lakebase-example`** to lint, confirm the build, validate the
bundle, and assemble the PR checklist.
