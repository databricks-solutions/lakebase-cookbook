"""Lakebase engine + idempotent schema bootstrap for agent memory.

Design notes (why it looks like this):

* **App owns its schema.** The app's Postgres role has ``CAN_CONNECT_AND_CREATE``
  on the database, so on startup it *creates* (and therefore *owns*) its own
  tables. Ownership is intrinsic to the role, so it survives redeploys — you do
  not need to re-GRANT table privileges every time the app is redeployed.
  One-time bootstrap: the role needs ``CREATE`` on the target schema (it has only
  ``USAGE`` by default); the setup step / deployer grants that once.
* **Idempotent DDL.** ``ensure_schema`` runs ``CREATE ... IF NOT EXISTS`` inside
  one transaction, so it is a safe no-op on an already-provisioned database.
* **pgvector** powers semantic recall. The ``vector`` extension must be enabled
  on the Lakebase database (see README prerequisites).
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, event, text

from .config import Settings
from .credentials import LakebaseCredentialProvider


def make_engine(settings: Settings, creds: LakebaseCredentialProvider) -> Engine:
    """Create a SQLAlchemy engine whose password is a fresh Lakebase OAuth token."""
    engine = create_engine(settings.pg_dsn, pool_pre_ping=True)

    @event.listens_for(engine, "do_connect")
    def _inject_token(dialect, conn_rec, cargs, cparams):  # noqa: ANN001
        cparams["password"] = creds.get_credential().token

    return engine


def schema_ddl(schema: str, embedding_dim: int) -> list[str]:
    """Ordered, idempotent DDL for the memory store.

    * ``conversations`` — short-term: one row per (user, session) turn.
    * ``memories``      — long-term facts + a pgvector embedding for recall.
    """
    return [
        "CREATE EXTENSION IF NOT EXISTS vector;",
        f'CREATE SCHEMA IF NOT EXISTS "{schema}";',
        f"""CREATE TABLE IF NOT EXISTS "{schema}".conversations (
            id          BIGSERIAL PRIMARY KEY,
            user_id     TEXT NOT NULL,
            session_id  TEXT NOT NULL,
            role        TEXT NOT NULL,
            content     TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );""",
        f"""CREATE TABLE IF NOT EXISTS "{schema}".memories (
            id          BIGSERIAL PRIMARY KEY,
            user_id     TEXT NOT NULL,
            content     TEXT NOT NULL,
            embedding   vector({embedding_dim}),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );""",
        f"CREATE INDEX IF NOT EXISTS conversations_user_session_idx "
        f'ON "{schema}".conversations (user_id, session_id, created_at);',
        f'CREATE INDEX IF NOT EXISTS memories_user_idx ON "{schema}".memories (user_id);',
        # IVFFlat index for cosine similarity recall over the embedding column.
        f"CREATE INDEX IF NOT EXISTS memories_embedding_idx "
        f'ON "{schema}".memories USING ivfflat (embedding vector_cosine_ops) '
        f"WITH (lists = 100);",
    ]


def ensure_schema(engine: Engine, schema: str, embedding_dim: int) -> None:
    """Create the memory schema/tables if absent. Idempotent; safe every startup."""
    with engine.begin() as conn:
        for stmt in schema_ddl(schema, embedding_dim):
            conn.execute(text(stmt))
