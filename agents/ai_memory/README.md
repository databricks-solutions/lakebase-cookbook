# AI Memory — durable agent memory on Lakebase Postgres

Give an agent **persistent, queryable memory** backed by a single governed
Lakebase Postgres store: short-term conversation history (with a resumable
thread sidebar) and long-term facts with semantic recall over `pgvector`. A
minimal Chainlit chat app demonstrates both; the reusable code lives in
`agent_memory/`.

## What you get

| Layer | What it stores | How it's used |
|-------|----------------|---------------|
| **Short-term** | Conversation threads (Chainlit's SQLAlchemy data layer) | Resumable thread sidebar + cross-session history, backed by Lakebase |
| **Long-term facts** | Durable user facts ("prefers metric units") | Survive across sessions (`remember` / `list_memories`) |
| **Semantic recall** | `pgvector` embedding of each fact | Cosine-similarity lookup of the most relevant memories (`recall`) |

> **Scope.** This example is deliberately focused on the *memory* story — chat
> persistence and pgvector recall. It uses a single Databricks Foundation Model
> for replies and does **not** demonstrate agent routing, Genie, MAS endpoints,
> or streaming. For a fuller reference implementation that calls a **Genie One**
> agent (via the managed Genie MCP), a **Multi-Agent Supervisor (MAS)** serving
> endpoint, and streams responses — while using this same Lakebase chat-history
> pattern — see the
> [**bi-hub-app**](https://github.com/rohit-db/bi-hub-app) reference app.

- **App owns its schema.** The app service principal creates (and therefore
  owns) its tables on startup, so schema access survives redeploys — no manual
  re-grant of table privileges after each `bundle deploy`.
- **On-platform embeddings.** A Databricks Foundation Model endpoint
  (`databricks-bge-large-en` by default) produces embeddings — no third-party
  API key.
- **Fully bundle-driven.** Every workspace-specific value is a DAB variable.

## Architecture

```
User --> Chainlit App (Databricks App)
             |                           +-----------------------------------+
             |  threads/steps (history)  |  Lakebase Postgres (schema: aimem)|
             |<------------------------->|                                   |
             |  recall(query) /          |  users/threads/steps/...          |
             |  remember(fact)           |         (Chainlit data layer)     |
             |-------------------------->|  memories + pgvector              |
             |                           |         (long-term + recall)      |
             |  chat + embed             +-----------------------------------+
             v
   Databricks Foundation Models
   (chat model + embedding endpoint)
```

Short-term history uses **Chainlit's SQLAlchemy data layer** (the
`users`/`threads`/`steps` tables), which drives the resumable-thread sidebar.
Long-term facts + recall use the `memories` table with a `pgvector` column.
Everything lives in a dedicated `aimem` schema, created and owned by the app
**service principal**, which mints short-lived OAuth tokens (auto-refreshed) as
the Postgres password. Chat and embeddings use Databricks Foundation Model
serving endpoints.

### Semantic-recall index

`memories.embedding` is indexed with **HNSW** using `vector_cosine_ops`
(`m = 16`, `ef_construction = 64`) — the same index type and parameters as the
[`graphrag`](../graphrag/) example, so the two pgvector examples agree.

HNSW rather than IVFFlat because `ensure_schema` runs at application **startup**,
which means the index is always created against an **empty table**. IVFFlat
derives its lists from a k-means training step over the rows present at build
time; built empty it clusters poorly (pgvector warns `ivfflat index created with
little data`) and recall degrades once the table grows enough for the planner to
start using the index. HNSW has no training step, so an empty-table build is
sound. See [`smoketest/`](smoketest/) for the offline contract test.

### Upgrading a database created before the HNSW switch

`CREATE INDEX IF NOT EXISTS` matches on **name only** — Postgres never compares the
definition — so reusing the old index name would leave an existing IVFFlat index in
place forever. Instead the HNSW index gets a new name (`memories_embedding_hnsw_idx`)
and the legacy `memories_embedding_idx` is dropped by name, which is the same
migration the [Genie-caching](../../apps/lakebase-genie-caching/) stores use. An
existing database therefore converges on HNSW on the next start, with no operator
step. Both statements run in `ensure_schema`'s single transaction, so if the build
fails the drop rolls back and the old index survives.

**On a large existing table, do it out of band first.** The drop takes
`ACCESS EXCLUSIVE` on `memories` for the rest of that transaction, so the rebuild
blocks reads and writes until it commits — measured at roughly 13 s for 20k rows on a
1024-dim column, and it is the app's startup path, so a big table can exceed the
platform's health-check window. To avoid that, build the index yourself before
deploying (neither `CONCURRENTLY` statement may run inside a transaction block):

```sql
CREATE INDEX CONCURRENTLY memories_embedding_hnsw_idx
    ON "<schema>".memories USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
DROP INDEX CONCURRENTLY "<schema>".memories_embedding_idx;
```

Raising `maintenance_work_mem` for the session speeds the build up considerably. On
the next start both statements are then no-ops. Verify with:

```sql
SELECT i.relname, am.amname, x.indisvalid
FROM pg_index x
JOIN pg_class i ON i.oid = x.indexrelid
JOIN pg_class t ON t.oid = x.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
JOIN pg_am am ON am.oid = i.relam
WHERE n.nspname = '<schema>' AND t.relname = 'memories' AND am.amname = 'hnsw';
```

### Run the offline smoke test

```bash
cd agents/ai_memory
uv sync
uv run python smoketest/aimem_index_smoketest.py
```

Checks the index contract without any Lakebase or model endpoint: the index type and
opclass, that the switch actually takes effect on an existing database, parameter
parity with the `graphrag` example, re-runnable DDL, statement ordering, and schema
and dimension parameterisation.

### Two limitations worth knowing

**`EMBEDDING_DIM` does not migrate an existing table.** `CREATE TABLE IF NOT
EXISTS` leaves an existing `embedding vector(n)` column alone, so pointing
`embedding_endpoint` at a model of a different dimensionality and changing
`EMBEDDING_DIM` will fail at insert time with `expected <n> dimensions`. Changing
dimensionality means migrating the column and re-embedding every stored fact.

**Per-user recall relies on a planner choice, not a guarantee.** `recall()` filters
`WHERE user_id = :u` and pgvector applies that filter *after* the ANN scan, which is
bounded by `hnsw.ef_search` (default 40). Measured at 20k rows: with the ANN path
forced, a user owning 0.5% of rows got 0.08 of 5 requested memories back and 92% of
queries returned nothing; `hnsw.iterative_scan = relaxed_order` restored a full 5 of
5. In practice the `memories_user_idx` btree saves you — at those small shares the
planner prefers a btree scan plus an exact sort, and only switches to the ANN index
at ~25% share, where truncation costs nothing. Keep that btree, and set
`hnsw.iterative_scan` if you ever query the embedding without a selective filter.

## Deploy with Asset Bundles

**Prerequisites**

- A **Lakebase** project + branch + database. The database must have the
  **`vector` (pgvector) extension** available (the app runs
  `CREATE EXTENSION IF NOT EXISTS vector`).
- The app creates and owns its own `aimem` schema on startup, so the app service
  principal needs **`CREATE` on the database** (granted once):
  `GRANT CREATE ON DATABASE <db> TO "<app-service-principal-id>";`
- **Authentication must be enabled** on the app. Chainlit only persists threads
  (the resumable sidebar) for an authenticated user; on Databricks Apps the
  forwarded SSO identity is used (see `header_auth` in `app.py`).
- A Databricks **Foundation Model embedding endpoint** (default
  `databricks-bge-large-en`) and a chat endpoint (`databricks-claude-sonnet-4-5`).

**Deploy**

```bash
databricks bundle validate -t demo
databricks bundle deploy -t demo \
  --var lakebase_branch="projects/<project>/branches/<branch>" \
  --var lakebase_database="projects/<project>/branches/<branch>/databases/<id>" \
  --var lakebase_instance="<your-lakebase-instance-name>"
databricks bundle run ai_memory -t demo   # or open the deployed app
```

Then chat with the app. Say `remember: I prefer metric units` to store a
long-term fact; later questions recall it automatically.

## Configuration

| Variable / env | What it does | Default |
|----------------|--------------|---------|
| `lakebase_branch` | Lakebase project/branch path | `projects/CHANGE_ME/branches/production` |
| `lakebase_database` | Full Lakebase database resource path (Postgres binding) | `.../databases/CHANGE_ME` |
| `lakebase_instance` | Lakebase database instance name (mints OAuth credentials) | `CHANGE_ME` |
| `lakebase_catalog` / `lakebase_schema` | UC catalog / Postgres schema | `default` / `public` |
| `embedding_endpoint` | Foundation Model embedding endpoint | `databricks-bge-large-en` |
| `EMBEDDING_DIM` | Embedding dimensionality (must match the model) | `1024` |
| `CHAINLIT_AUTH_SECRET` | Chainlit auth cookie signing secret | set per deployment |

## Local development

```bash
uv sync
cp .env.example .env      # fill in your workspace + Lakebase values
uv run chainlit run app.py -w
```

Locally the Databricks SDK resolves your CLI profile for both Lakebase
credentials and Foundation Model calls; set `PGHOST`/`PGUSER`/etc. in `.env`.
