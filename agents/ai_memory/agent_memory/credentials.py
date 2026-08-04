"""Lakebase OAuth credential provider.

Lakebase Postgres does not use a static password. Instead you mint a short-lived
OAuth token with the Databricks SDK and use it as the Postgres password. Tokens
expire (~1h), so this provider caches the current token and transparently
refreshes it shortly before expiry. Inject the token via a SQLAlchemy
``do_connect`` event (see ``db.py``) so every new connection gets a fresh one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from threading import Lock

from databricks.sdk import WorkspaceClient
from pydantic import BaseModel, field_validator


class Credential(BaseModel):
    token: str
    expiration_time: datetime

    @field_validator("expiration_time")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.astimezone(UTC)

    def valid_for(self) -> timedelta:
        return self.expiration_time - datetime.now(UTC)


class LakebaseCredentialProvider:
    """Thread-safe, self-refreshing Lakebase credential cache.

    ``instance_name`` is the Lakebase database *instance* name whose credential
    is minted. It is workspace-specific and supplied via configuration, never
    hardcoded.
    """

    def __init__(self, instance_name: str):
        self._instance_name = instance_name
        self._lock = Lock()
        self._cached: Credential | None = None

    def _client(self) -> WorkspaceClient:
        # On Databricks Apps the runtime injects the app service principal's
        # OAuth env credentials; locally the SDK resolves your CLI profile.
        return WorkspaceClient()

    def get_credential(self) -> Credential:
        with self._lock:
            if self._cached and self._cached.valid_for() > timedelta(minutes=1):
                return self._cached

            w = self._client()
            cred = w.database.generate_database_credential(
                request_id=str(uuid.uuid4()),
                instance_names=[self._instance_name],
            )
            self._cached = Credential(token=cred.token, expiration_time=cred.expiration_time)
            return self._cached

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None
