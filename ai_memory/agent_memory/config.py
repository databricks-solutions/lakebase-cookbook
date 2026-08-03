"""Configuration for the AI Memory example.

Every workspace-specific value comes from an environment variable (set via the
DAB app resource / app.yml, or a local ``.env``). Nothing workspace-specific is
hardcoded — see ``.env.example`` and ``databricks.yml``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Lakebase Postgres connection. PGHOST/PGPORT/PGUSER are auto-injected by the
    # Databricks App Postgres resource binding; PGDATABASE + instance are set in
    # app.yml / .env.
    pg_host: str
    pg_port: int
    pg_user: str
    pg_database: str
    pg_schema: str
    pg_sslmode: str
    # Lakebase database *instance* name — used to mint OAuth credentials.
    lakebase_instance: str

    # Databricks Foundation Model embedding endpoint (on-platform embeddings for
    # semantic recall). Defaults to the workspace's hosted BGE endpoint.
    embedding_endpoint: str
    # Embedding dimensionality of the chosen model (bge-large-en = 1024).
    embedding_dim: int

    @property
    def pg_dsn(self) -> str:
        # Password is injected per-connection via the SQLAlchemy do_connect hook,
        # so it is intentionally absent here.
        return (
            f"postgresql+psycopg://{self.pg_user}@{self.pg_host}:{self.pg_port}"
            f"/{self.pg_database}?sslmode={self.pg_sslmode}"
        )


def load_settings() -> Settings:
    return Settings(
        pg_host=os.environ.get("PGHOST", "localhost"),
        pg_port=int(os.environ.get("PGPORT", "5432")),
        pg_user=os.environ.get("PGUSER", ""),
        pg_database=os.environ.get("PGDATABASE", "databricks_postgres"),
        pg_schema=os.environ.get("LAKEBASE_SCHEMA", "public"),
        pg_sslmode=os.environ.get("PGSSLMODE", "require"),
        lakebase_instance=os.environ.get("LAKEBASE_INSTANCE", ""),
        embedding_endpoint=os.environ.get("EMBEDDING_ENDPOINT", "databricks-bge-large-en"),
        embedding_dim=int(os.environ.get("EMBEDDING_DIM", "1024")),
    )
