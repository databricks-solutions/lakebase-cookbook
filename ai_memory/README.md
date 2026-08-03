# AI Memory — durable agent memory on Lakebase Postgres

Give an agent **persistent, queryable memory** backed by a single governed
Lakebase Postgres store: short-term conversation history, long-term facts, and
semantic recall over those facts with `pgvector`. A minimal Chainlit chat app
demonstrates all three layers; the reusable code lives in `src/ai_memory/`.

## What you get

| Layer | What it stores | How it's used |
|-------|----------------|---------------|
| **Short-term** | Raw conversation turns per `(user, session)` | Working context window (`recent_turns`) |
| **Long-term facts** | Durable user facts ("prefers metric units") | Survive across sessions (`remember` / `list_memories`) |
| **Semantic recall** | `pgvector` embedding of each fact | Cosine-similarity lookup of the most relevant memories (`recall`) |

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
             |
             |  1. recall(query)         +-------------------------------+
             |-------------------------->|  Lakebase Postgres            |
             |  2. recent_turns()        |                               |
             |                           |  conversations  (short-term)  |
             |  4. add_turn()/remember() |  memories + pgvector           |
             |-------------------------->|            (long-term+recall)  |
             |                           +-------------------------------+
             |  3. chat + embed
             v
   Databricks Foundation Models
   (chat model + embedding endpoint)
```

The app talks to Lakebase as its **service principal**, minting short-lived
OAuth tokens (auto-refreshed) as the Postgres password. Embeddings and chat both
go to Databricks Foundation Model serving endpoints.

## Deploy with Asset Bundles

**Prerequisites**

- A **Lakebase** project + branch + database. The database must have the
  **`vector` (pgvector) extension** available (the app runs
  `CREATE EXTENSION IF NOT EXISTS vector`).
- The app service principal needs **`CREATE` on the target schema** (it has only
  `USAGE` by default). Grant it once:
  `GRANT CREATE ON SCHEMA public TO "<app-service-principal-id>";`
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
