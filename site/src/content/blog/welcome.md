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

One fully worked example is **[GraphRAG](/docs/examples/graphrag/)** — a
knowledge-graph-augmented RAG served entirely from Lakebase, pairing a pgvector
semantic seed with recursive-CTE graph traversal. There's also a
**[FastAPI backend on Lakebase](/docs/examples/lakebase-fastapi/)** and a
**[Branching CI/CD](/docs/examples/branching-cicd/)** workflow.

More examples — AI memory, feature store, and reverse ETL — are on the way.

## Contributing

Have a pattern worth sharing? Fork the repository, add your example, and open a
pull request. Docs live as Markdown and appear in the sidebar automatically.
