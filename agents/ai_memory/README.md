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
