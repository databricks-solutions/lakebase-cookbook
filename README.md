# Lakebase Examples

Examples and guides to accelerate your Lakebase projects:

- Cookbook site: https://lakebase-cookbook.com
- Official Lakebase announcment blog: https://www.databricks.com/product/lakebase
- Official Documentation: https://docs.databricks.com/aws/en/oltp/

## Examples in this repository

| Folder | Description |
|--------|--------------|
| [`ai_memory/`](ai_memory/) | AI memory patterns |
| [`apps/`](apps/) | Sample applications |
| [`feature_store/`](feature_store/) | Feature store integration |
| [`reverse_etl/`](reverse_etl/) | Reverse ETL examples |
| [`genie_caching/`](genie_caching/) | Genie conversational API proxy with Lakebase (pgvector) semantic query cache; deploy via Databricks Asset Bundle. See [`genie_caching/README.md`](genie_caching/README.md). |

## Contributing

To Contribute:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

Contributing Guidelines:

- Resources related to your example must be deployed via Databricks Asset Bundles
- Database configurations should be small to reduce spend
- UV as package manager
- Ruff as linter

## Documentation site

This repo also publishes a documentation site (Docusaurus) hosted on Cloudflare
Workers at **https://lakebase-cookbook.com**. The site source lives in
[`docs/`](docs/), and common tasks are wrapped in the [`Makefile`](Makefile)
(run `make help` to list them).

You can preview and contribute to the site without any Cloudflare account or
credentials:

```bash
make install    # one-time: install site dependencies
make dev        # local dev server with hot reload at http://localhost:3000
make build      # build the static site into docs/build (verifies the build)
```

To add or edit content:

- **Docs / examples** — add or edit Markdown in [`docs/docs/`](docs/docs/). New
  files under `docs/docs/examples/` automatically appear in the sidebar.
- **Blog posts** — add Markdown to `docs/blog/`.
- **Landing page / styling** — `docs/src/` (React/TSX pages, components, and CSS).
- **Navbar, footer, site config** — `docs/docusaurus.config.ts`.

Then open a pull request. Deploys are handled by a maintainer after merge and
require Cloudflare credentials that are **not** stored in this repo, so cloning or
forking does not grant any ability to deploy.

## License

&copy; 2025 Databricks, Inc. All rights reserved. The source in this notebook is provided subject to the Databricks License [https://databricks.com/db-license-source].  All included or referenced third party libraries are subject to the licenses set forth below.

| library                                | description             | license    | source                                              |
|----------------------------------------|-------------------------|------------|-----------------------------------------------------|
