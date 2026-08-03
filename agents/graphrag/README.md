# GraphRAG on Lakebase

Knowledge-graph-augmented RAG served entirely from **Lakebase** (managed Postgres). Classic RAG
retrieves text chunks by vector similarity and misses *relationships* ("which suppliers cover the
products whose demand is surging, and what substitutes share those suppliers?"). GraphRAG adds a
knowledge graph so retrieval can **traverse relationships**, not just match text.

## How it works

- **Graph store** — `nodes` + `edges` relational tables (typed, JSONB props).
- **Traversal** — a **recursive CTE** walks edges out from a seed, bounded by `max_hops`.
- **Semantic seed** — **pgvector** HNSW (cosine) finds the entry nodes for a question.
- **Hybrid retrieval** — seed with vectors, expand along the graph, rank by a blended
  `seed_similarity × 0.5^hop` score. See [`sql/graphrag_retrieval.sql`](sql/graphrag_retrieval.sql).

A generic Databricks **model-serving** endpoint supplies embeddings and answer synthesis — swap in
whichever provider your workspace has registered. Nothing here is cloud-specific.

## Honest capability note

Lakebase is managed Postgres — there is **no native property-graph engine** (no Apache AGE, no
Cypher). This example builds GraphRAG on relational + vector primitives, all verified as supported
Lakebase extensions:

| Need | How | Extension |
| --- | --- | --- |
| Graph store | `nodes` / `edges` tables | core |
| Multi-hop traversal | recursive CTE (`WITH RECURSIVE`) | core |
| Hierarchies | `ltree` paths | `ltree` |
| Semantic seed | pgvector HNSW, cosine (`<=>`) | `vector` |
| Fuzzy entity link | trigram similarity | `pg_trgm` |

Position it as *"graph traversal via recursive CTEs + semantic retrieval via pgvector"* — great for
bounded k-hop operational retrieval; **not** a billion-edge graph-analytics engine.

## Layout

```
graphrag/
├── databricks.yml       # Asset Bundle — deploys the build/query notebook as a job
├── pyproject.toml       # uv deps + ruff config
├── sql/
│   ├── schema.sql              # nodes / edges / node_embeddings + HNSW / ltree / pg_trgm
│   └── graphrag_retrieval.sql  # hybrid: pgvector seed → recursive-CTE expansion → ranked context
├── graph_build.py       # pure assemble_graph(dims, enrichment) → (nodes, edges); guards the FK
├── graph_retrieve.py    # pure in-memory twin of the retrieval SQL (for offline dev/test)
├── notebooks/
│   └── graphrag_build_and_query.py   # build the graph, embed, write to Lakebase, query
└── smoketest/
    └── graphrag_logic_smoketest.py   # offline validation (no Lakebase needed)
```

## Run the offline smoke test

Validates the retrieval + build logic with no Lakebase, no model endpoint:

```bash
cd graphrag
uv run --python 3.11 --with duckdb --with numpy smoketest/graphrag_logic_smoketest.py
```

25 assertions: semantic seed, graph expansion surfacing connected context flat RAG misses,
dangling-edge guard, blended-score ranking, depth bound.

## Deploy (Asset Bundle)

```bash
cd graphrag
# set your Lakebase database path + endpoints, then:
databricks bundle deploy -t dev \
  --var lakebase_database="projects/<id>/branches/production/databases/<db>"
databricks bundle run graphrag_build -t dev
```

The bundle deploys `notebooks/graphrag_build_and_query.py` as a job. The notebook assembles a
small example supply-chain graph and embeds its nodes via your embedding endpoint out of the box.

> **The two Lakebase I/O cells are scaffolding you complete** (marked ✍️ COMPLETE THIS): the
> Postgres connection is workspace-specific, so the notebook documents the exact
> credential/connection pattern (Databricks-issued OAuth token → apply `sql/schema.sql` → INSERT
> the graph → run `sql/graphrag_retrieval.sql`) rather than hardcoding an instance. The
> **retrieval logic itself is fully validated offline** by the smoke test below, so you can trust
> the query before you wire the connection.

## Prerequisites

- Databricks workspace with **Lakebase (Autoscaling)** enabled
- A model-serving **embeddings** endpoint and a **chat** endpoint registered in the workspace
- `databricks` CLI + `uv`

---

*Adapted from a Databricks Field Engineering AWS-integration asset (Unity AI Gateway + Amazon
Bedrock variant); this cookbook version is cloud-agnostic.*
