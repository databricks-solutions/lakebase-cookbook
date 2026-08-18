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

## Operational guardrails

Defaults that keep retrieval fast, precise, and cost-predictable on real Lakebase:

- **Bound `max_hops` to 2 on dense graphs.** Recursive-CTE cost is *density-driven*: at 4 hops on a
  dense graph the walk approaches a full-graph scan (seconds), while 2 hops stays in the tens of ms
  even at ~1M nodes / 10M edges. Raise hops only on sparse graphs.
- **Set a `seed_floor` under distractor-heavy corpora.** Weak semantic seeds drag unrelated subgraphs
  into the ranking and dilute precision; a cosine floor drops them. **Calibrate the floor to
  your embedding model's actual similarity distribution** — it is not a portable constant.
  Measured on live Lakebase with `databricks-gte-large-en`, this example graph's node
  similarities span only `0.38`-`0.71`, so a `0.3` floor changes nothing while `0.555` drops
  every distractor and keeps every on-topic node (the on-topic supplier below the floor still
  arrives via graph expansion). Cosine ranges
  `[-1, 1]`, so the default `-1.0` keeps all seeds (identical to no floor). See `:seed_floor` in
  [`sql/graphrag_retrieval.sql`](sql/graphrag_retrieval.sql).
- **Keep a minimum Lakebase compute above zero for latency-sensitive serving.** After scale-to-zero,
  the first query pays a cold-start penalty (several× the warm latency) while index pages load in.
- **Seed with plain pgvector, not a BM25+vector hybrid.** Lexical fusion adds latency and can *hurt*
  ranking on this workload — the relationship recall comes from graph expansion, not lexical overlap.
- **Treat the HNSW build as a one-time cost that scales with corpus size** (seconds at 10⁴ nodes,
  minutes at 10⁵), independent of query latency. Storing embeddings as `halfvec` (fp16) cuts the
  embedding-plus-HNSW-index storage ~2.5× vs fp32 (measured) at negligible recall cost — a cheap
  lever for large graphs.
- **Route simple, single-entity questions to the managed path first.** If a question needs no
  multi-hop traversal, ontology-enriched Genie or a plain vector lookup is cheaper; reserve GraphRAG
  for genuinely relational / multi-hop queries.

## Cross-stack interop (`gold_triplets`)

The `nodes` / `edges` tables map to a portable **8-column triplet shape** — `subject_id, subject_type,
predicate, object_id, object_type, confidence, source_method, source_agent` — so the same graph can be
emitted or consumed by other graph stacks (Spark/Python builders, other engines) **without migration**.
It's a column contract, not a dependency. See [`sql/gold_triplets_mapping.sql`](sql/gold_triplets_mapping.sql).

## Layout

```
graphrag/
├── databricks.yml       # Asset Bundle — deploys the build/query notebook as a job
├── pyproject.toml       # uv deps + ruff config
├── sql/
│   ├── schema.sql              # nodes / edges / node_embeddings + HNSW / ltree / pg_trgm
│   ├── graphrag_retrieval.sql  # hybrid: pgvector seed (+ seed_floor) → recursive-CTE expansion → ranked context
│   └── gold_triplets_mapping.sql  # portable 8-column triplet view over nodes/edges (cross-stack interop)
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
