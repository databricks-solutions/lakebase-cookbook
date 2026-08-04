# Lakebase Examples

Examples and guides to accelerate your Lakebase projects:

- Cookbook site: https://lakebase-cookbook.com
- Official Lakebase announcment blog: https://www.databricks.com/product/lakebase
- Official Documentation: https://docs.databricks.com/aws/en/oltp/

## Examples in this repository

Examples are grouped into category folders:

| Category | Examples |
|----------|----------|
| [`agents/`](agents/) | [`graphrag/`](agents/graphrag/) — knowledge-graph RAG on Lakebase; [`ai_memory/`](agents/ai_memory/) — durable agent memory |
| [`developer_experience/`](developer_experience/) | [`branching_cicd/`](developer_experience/branching_cicd/) — validate schema changes on a Lakebase branch in CI/CD |
| [`apps/`](apps/) | [`lakebase-fastapi/`](apps/lakebase-fastapi/) — FastAPI backend serving a Lakebase synced table |
| [`data/`](data/) | [`feature_store/`](data/feature_store/) — online feature serving; [`reverse_etl/`](data/reverse_etl/) — lakehouse → Lakebase sync |

## Contributing

Want to add an example? **Read [`CONTRIBUTING.md`](CONTRIBUTING.md)** — it is a
step-by-step guide covering the required example layout, how to deploy via
Databricks Asset Bundles, and how to document your example so it appears on the
cookbook site.

The essentials:

- Resources related to your example must be deployable via Databricks Asset Bundles
- Keep database configurations small to reduce spend
- Use `uv` as the package manager
- Use `ruff` as the linter

## Documentation site

This repo also publishes a documentation site hosted on Cloudflare Workers at
**https://lakebase-cookbook.com**. The site is built with
[Astro](https://astro.build/); the source lives in [`site/`](site/), and common
tasks are wrapped in the [`Makefile`](Makefile) (run `make help` to list them).

You can preview and contribute to the site without any Cloudflare account or
credentials:

```bash
make install    # one-time: install site dependencies
make dev        # local dev server with hot reload at http://localhost:3000
make build      # build the static site into site/dist (verifies the build)
```

To add or edit content:

- **Docs / examples** — add or edit Markdown in [`site/src/content/docs/`](site/src/content/docs/).
  New files under `examples/` automatically appear in the sidebar. See
  [`CONTRIBUTING.md`](CONTRIBUTING.md) for the exact frontmatter and layout.
- **Blog posts** — add Markdown to [`site/src/content/blog/`](site/src/content/blog/).
- **Landing page / styling** — [`site/src/`](site/src/) (Astro pages, React
  islands, and CSS design tokens in [`site/src/styles/global.css`](site/src/styles/global.css)).
- **Navbar, footer, site config** — [`site/src/config.ts`](site/src/config.ts).

Then open a pull request. Deploys are handled by a maintainer after merge and
require Cloudflare credentials that are **not** stored in this repo, so cloning or
forking does not grant any ability to deploy.

## License

&copy; 2025 Databricks, Inc. All rights reserved. The source in this notebook is provided subject to the Databricks License [https://databricks.com/db-license-source].  All included or referenced third party libraries are subject to the licenses set forth below.

| library                                | description             | license    | source                                              |
|----------------------------------------|-------------------------|------------|-----------------------------------------------------|
