---
title: Lakebase Cookbook
sidebar_label: Introduction
sidebar_position: 1
description: Examples and guides to accelerate your Databricks Lakebase projects.
---

# Lakebase Cookbook

Examples and guides to accelerate your **Databricks Lakebase** projects.

Lakebase is Databricks' fully-managed, Postgres-compatible OLTP database, built
for transactional workloads that sit alongside your lakehouse.

- **Announcement blog:** [databricks.com/product/lakebase](https://www.databricks.com/product/lakebase)
- **Official documentation:** [docs.databricks.com/aws/en/oltp](https://docs.databricks.com/aws/en/oltp/)

## Examples in this cookbook

| Example | Description |
|---------|-------------|
| [Genie Caching](/docs/examples/genie-caching/) | Genie API gateway with a Lakebase (pgvector) semantic query cache |
| [GraphRAG](/docs/examples/graphrag/) | Knowledge-graph-augmented RAG with pgvector seeding and recursive-CTE graph traversal |
| [Branching CI/CD](/docs/examples/branching-cicd/) | Validate schema changes on an isolated Lakebase branch in GitHub CI/CD, with an AI impact report per PR |
| [AI Memory](/docs/examples/ai-memory/) | AI memory patterns backed by Lakebase |
| [Apps](/docs/examples/apps/) | Sample applications on Lakebase |
| [Feature Store](/docs/examples/feature-store/) | Feature store integration |
| [Reverse ETL](/docs/examples/reverse-etl/) | Reverse ETL patterns |

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

Guidelines:

- Resources related to your example must be deployable via Databricks Asset Bundles
- Keep database configurations small to reduce spend
- Use `uv` as the package manager
- Use `ruff` as the linter
