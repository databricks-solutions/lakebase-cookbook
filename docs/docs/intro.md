---
sidebar_position: 1
---

# Lakebase Cookbook

Examples and guides to accelerate your **Databricks Lakebase** projects.

Lakebase is Databricks' fully-managed, Postgres-compatible OLTP database, built
for transactional workloads that sit alongside your lakehouse.

- 📣 **Announcement blog:** [databricks.com/product/lakebase](https://www.databricks.com/product/lakebase)
- 📚 **Official documentation:** [docs.databricks.com/aws/en/oltp](https://docs.databricks.com/aws/en/oltp/)

## Examples in this cookbook

| Example | Description |
|---------|-------------|
| [Genie Caching](./examples/genie-caching.md) | Genie API gateway with a Lakebase (pgvector) semantic query cache |
| [AI Memory](./examples/ai-memory.md) | AI memory patterns backed by Lakebase |
| [Apps](./examples/apps.md) | Sample applications on Lakebase |
| [Feature Store](./examples/feature-store.md) | Feature store integration |
| [Reverse ETL](./examples/reverse-etl.md) | Reverse ETL patterns |

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
