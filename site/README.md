# Lakebase Cookbook — Astro site

The redesigned documentation + marketing site for
**https://lakebase-cookbook.com**, built with [Astro](https://astro.build/).
This replaces the Docusaurus site in [`../docs/`](../docs/); both currently
coexist during the migration and ship via the same `lakebase-cookbook`
Cloudflare Worker (deploy one at a time).

## Why Astro

The cookbook's value is Markdown examples that contributors PR and that appear
in the sidebar automatically. Astro's **content collections** preserve that
authoring model while giving full control over the marketing pages — so the
landing experience can be art-directed without giving up zero-effort docs.

## Design system

A light, editorial system adapted from
[developers.databricks.com](https://developers.databricks.com/) — the reference
site is dark; this one keeps a readable light canvas and borrows the *system*:

- **Type:** DM Sans (oversized, light-weight display headings), Inter (body),
  Geist Mono (uppercase labels, nav, buttons, `[bracketed]` asides).
- **Color:** white / oat (`#F9F7F4`) canvas, Databricks deep navy ink
  (`#1B3139`), lava-coral accent (`#FF3621`). Zero border radius everywhere.
- **Devices:** coral tag chips above sections, `[bracket]` mono motif, zebra
  content rows, an editorial navy "poster" CTA band.

All tokens live in [`src/styles/global.css`](src/styles/global.css) as CSS
custom properties + Tailwind v4 `@theme`.

## Structure

```
src/
  config.ts              # nav + footer + site metadata
  content.config.ts      # docs & blog collection schemas
  content/
    docs/                # Markdown/MDX — folder = sidebar group,
                         #   sidebar_position = order (auto-sidebar)
    blog/                # Markdown/MDX blog posts
  data/                  # examples, archives, resources (typed arrays)
  components/            # Navbar, Footer, Button, Callout, DocsSidebar,
                         #   HeaderAnimation (island), FeatureScroller (island)
  layouts/               # BaseLayout, DocsLayout
  lib/docs.ts            # sidebar tree + prev/next helpers
  pages/                 # index, why-lakebase, archives, resources, 404,
                         #   docs/[...slug], blog/index, blog/[...slug]
```

## Adding content

- **A new example doc:** add a Markdown/MDX file under
  `src/content/docs/examples/` with frontmatter (`title`, `sidebar_position`,
  `description`). It appears in the sidebar and prev/next automatically. To also
  feature it on the landing page, add an entry to
  [`src/data/examples.ts`](src/data/examples.ts).
- **A blog post:** add a Markdown/MDX file under `src/content/blog/` with
  `title`, `date`, and optional `description`.
- **Archives / Resources cards:** append to
  [`src/data/archives.ts`](src/data/archives.ts) or
  [`src/data/resources.ts`](src/data/resources.ts).

Docusaurus `:::note` admonitions become the `<Callout>` component in `.mdx`.

## Commands

Run from the repo root via the `Makefile` (preferred):

```bash
make site-install   # install dependencies
make site-dev       # dev server with hot reload at http://localhost:3000
make site-build     # build static site into site/dist
make site-serve     # build + serve the production build locally
make site-preview   # build + wrangler dry-run (no publish)
make site-deploy    # build + deploy to Cloudflare (maintainers only)
```

Or directly with `npm run <dev|build|preview|deploy>` inside `site/`.

## Deploy

Same model as before: [`wrangler.jsonc`](wrangler.jsonc) ships `site/dist/` as
Cloudflare Worker static assets under the `lakebase-cookbook` worker, with
custom-domain routes for `lakebase-cookbook.com` + `www`. Deploys authenticate
via a per-machine `wrangler login`; no tokens are committed.

## Cutover checklist

When ready to make Astro the live site:

1. `make site-preview` to validate the Cloudflare build.
2. `make site-deploy` — this ships the Astro `dist/` to the shared worker,
   replacing the Docusaurus assets.
3. Point the root `Makefile`'s plain targets at `SITE_DIR` (or delete the
   `docs/`-based ones) and remove [`../docs/`](../docs/).
4. Update the root `README.md` / `CLAUDE.md` references from Docusaurus to Astro.
