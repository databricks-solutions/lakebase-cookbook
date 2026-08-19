"""Lakebase engine + idempotent schema bootstrap for agent memory.

Two persistence concerns share one Lakebase database:

* **Short-term / conversation history** is handled by Chainlit's own SQLAlchemy
  data layer (the ``users`` / ``threads`` / ``steps`` / ``elements`` /
  ``feedbacks`` tables). Registering it gives you the resumable-thread sidebar
  and cross-session chat history for free — see ``create_chainlit_data_layer``.
* **Long-term facts + semantic recall** live in a ``memories`` table with a
  ``pgvector`` embedding column (see ``memory.py``).

Design notes:

* **App owns its schema.** The app's Postgres role has ``CAN_CONNECT_AND_CREATE``
  on the database, so on startup it *creates* (and therefore *owns*) its tables.
  Ownership is intrinsic to the role, so it survives redeploys — no need to
  re-GRANT table privileges after each ``bundle deploy``. One-time bootstrap: the
  role needs ``CREATE`` on the schema (it has only ``USAGE`` by default); the
  deployer grants that once.
* **Idempotent DDL.** ``ensure_schema`` runs ``CREATE ... IF NOT EXISTS`` in one
  transaction, so it is a safe no-op on an already-provisioned database.
"""

from __future__ import annotations

from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from sqlalchemy import Engine, create_engine, event, text

from .config import Settings
from .credentials import LakebaseCredentialProvider

# Chainlit 2.11 data-layer schema. These unqualified public tables are what the
# Chainlit UI reads/writes for the thread sidebar and resume. Kept verbatim to
# match the version Chainlit expects.
CHAINLIT_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS users (
        "id" UUID PRIMARY KEY,
        "identifier" TEXT NOT NULL UNIQUE,
        "metadata" JSONB NOT NULL,
        "createdAt" TEXT
    );""",
    """CREATE TABLE IF NOT EXISTS threads (
        "id" UUID PRIMARY KEY,
        "createdAt" TEXT,
        "name" TEXT,
        "userId" UUID,
        "userIdentifier" TEXT,
        "tags" TEXT[],
        "metadata" JSONB,
        FOREIGN KEY ("userId") REFERENCES users("id") ON DELETE CASCADE
    );""",
    """CREATE TABLE IF NOT EXISTS steps (
        "id" UUID PRIMARY KEY,
        "name" TEXT NOT NULL,
        "type" TEXT NOT NULL,
        "threadId" UUID NOT NULL,
        "parentId" UUID,
        "streaming" BOOLEAN NOT NULL,
        "waitForAnswer" BOOLEAN,
        "isError" BOOLEAN,
        "metadata" JSONB,
        "tags" TEXT[],
        "input" TEXT,
        "output" TEXT,
        "createdAt" TEXT,
        "command" TEXT,
        "start" TEXT,
        "end" TEXT,
        "generation" JSONB,
        "showInput" TEXT,
        "language" TEXT,
        "indent" INT,
        "defaultOpen" BOOLEAN,
        "autoCollapse" BOOLEAN,
        "modes" JSONB,
        "icon" TEXT,
        FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
    );""",
    """CREATE TABLE IF NOT EXISTS elements (
        "id" UUID PRIMARY KEY,
        "threadId" UUID,
        "type" TEXT,
        "url" TEXT,
        "chainlitKey" TEXT,
        "name" TEXT NOT NULL,
        "display" TEXT,
        "objectKey" TEXT,
        "size" TEXT,
        "page" INT,
        "language" TEXT,
        "forId" UUID,
        "mime" TEXT,
        "props" JSONB,
        FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
    );""",
    """CREATE TABLE IF NOT EXISTS feedbacks (
        "id" UUID PRIMARY KEY,
        "forId" UUID NOT NULL,
        "threadId" UUID NOT NULL,
        "value" INT NOT NULL,
        "comment" TEXT,
        FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
    );""",
]


def make_engine(settings: Settings, creds: LakebaseCredentialProvider) -> Engine:
    """Create a SQLAlchemy engine whose password is a fresh Lakebase OAuth token."""
    engine = create_engine(settings.pg_dsn, pool_pre_ping=True)

    @event.listens_for(engine, "do_connect")
    def _inject_token(dialect, conn_rec, cargs, cparams):  # noqa: ANN001
        cparams["password"] = creds.get_credential().token

    return engine


def create_chainlit_data_layer(
    settings: Settings, creds: LakebaseCredentialProvider
) -> SQLAlchemyDataLayer:
    """Chainlit SQLAlchemy data layer backed by Lakebase (drives the thread
    sidebar + resume). Injects a fresh OAuth token on every new connection and
    pins ``search_path`` to the example's schema so Chainlit's unqualified table
    names resolve there (isolating this example from anything else in the DB)."""
    data_layer = SQLAlchemyDataLayer(settings.pg_dsn)
    engine = data_layer.engine
    sync_engine = getattr(engine, "sync_engine", engine)
    schema = settings.pg_schema

    @event.listens_for(sync_engine, "do_connect")
    def _inject_token(dialect, conn_rec, cargs, cparams):  # noqa: ANN001
        cparams["password"] = creds.get_credential().token
        opts = cparams.get("options", "")
        cparams["options"] = f"{opts} -c search_path={schema},public".strip()

    return data_layer


EMBEDDING_INDEX_NAME = "memories_embedding_hnsw_idx"
# The IVFFlat index this example shipped before switching to HNSW. Retired by
# name so an existing database converges on the new index without operator
# action -- see the comment on the DROP in memories_ddl.
LEGACY_EMBEDDING_INDEX_NAME = "memories_embedding_idx"


def memories_ddl(schema: str, embedding_dim: int) -> list[str]:
    """Long-term facts + pgvector semantic-recall table (schema-qualified)."""
    return [
        "CREATE EXTENSION IF NOT EXISTS vector;",
        f'CREATE SCHEMA IF NOT EXISTS "{schema}";',
        f"""CREATE TABLE IF NOT EXISTS "{schema}".memories (
            id          BIGSERIAL PRIMARY KEY,
            user_id     TEXT NOT NULL,
            content     TEXT NOT NULL,
            embedding   vector({embedding_dim}),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );""",
        f'CREATE INDEX IF NOT EXISTS memories_user_idx ON "{schema}".memories (user_id);',
        # Retire the IVFFlat index this example used to create. Renaming rather
        # than reusing the old name is what makes the switch actually take effect:
        # CREATE INDEX IF NOT EXISTS matches on NAME only, never on definition, so
        # keeping the name would leave an existing IVFFlat index in place forever.
        # Same drop-legacy-then-create-under-a-new-name migration the
        # Genie-caching stores use. Both statements run in ensure_schema's single
        # transaction, so a failed build rolls the drop back and the old index
        # survives.
        f'DROP INDEX IF EXISTS "{schema}".{LEGACY_EMBEDDING_INDEX_NAME};',
        # HNSW with cosine distance (vector_cosine_ops) for the semantic-recall
        # ANN scan. HNSW rather than IVFFlat because this DDL runs at startup,
        # i.e. against an empty table on a fresh database: IVFFlat derives its
        # lists from a k-means training step over the rows present at build time,
        # so an empty-table build produces a poorly-clustered index (pgvector even
        # warns "ivfflat index created with little data"). HNSW has no training
        # step and can be built empty. Same index type and parameters as the
        # graphrag example and the Genie-caching stores.
        f"CREATE INDEX IF NOT EXISTS {EMBEDDING_INDEX_NAME} "
        f'ON "{schema}".memories USING hnsw '
        f"(embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);",
    ]


def ensure_schema(engine: Engine, schema: str, embedding_dim: int) -> None:
    """Create the example's schema, the Chainlit data-layer tables, and the
    memories table if absent. Idempotent; safe to run on every startup.

    Everything lives in the dedicated ``schema`` so the example is isolated from
    anything else in the database. The Chainlit tables use unqualified names, so
    we pin ``search_path`` to ``schema`` while creating them."""
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}";'))
        # Include public so the pgvector `vector` type (created in public)
        # resolves while our schema is first on the path. SET LOCAL scopes this to
        # the DDL transaction: a plain SET is committed with the block and then
        # leaks to every later user of the pooled connection, because the pool's
        # reset issues ROLLBACK, which does not undo a committed SET.
        conn.execute(text(f'SET LOCAL search_path TO "{schema}", public;'))
        for stmt in CHAINLIT_DDL:
            conn.execute(text(stmt))
        for stmt in memories_ddl(schema, embedding_dim):
            conn.execute(text(stmt))
