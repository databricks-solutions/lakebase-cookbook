---
title: Welcome to the Lakebase Cookbook
description: A home for practical, deployable examples of building on Databricks Lakebase.
date: 2026-07-28
authors: [databricks]
---

The Lakebase Cookbook is a growing collection of practical, deployable examples
for building on **Databricks Lakebase** — the fully-managed, Postgres-compatible
operational database built into the lakehouse.

Every example here is meant to be deployed via Databricks Asset Bundles, kept
small to limit spend, and built with the tools you already use: `uv` for
packaging and `ruff` for linting.

## What's here today

The first fully worked example is **[Genie Caching](/docs/examples/genie-caching/)** —
a Databricks App that fronts Genie with a Lakebase (pgvector) semantic query
cache, so repeated or similar questions skip NL→SQL and reuse cached SQL against
your warehouse.

More examples — AI memory, apps, feature store, and reverse ETL — are on the way.

## Contributing

Have a pattern worth sharing? Fork the repository, add your example, and open a
pull request. Docs live as Markdown and appear in the sidebar automatically.
