"""Embeddings via a Databricks Foundation Model serving endpoint.

Uses the workspace's hosted embedding endpoint (default: ``databricks-bge-large-en``)
through the Databricks SDK's serving client, so no third-party API key is needed.
"""

from __future__ import annotations

from databricks.sdk import WorkspaceClient


class Embedder:
    def __init__(self, endpoint: str):
        self._endpoint = endpoint
        self._w = WorkspaceClient()

    def embed(self, text: str) -> list[float]:
        """Return the embedding vector for a single string."""
        resp = self._w.serving_endpoints.query(name=self._endpoint, input=[text])
        # The serving response exposes embeddings on data[i].embedding.
        return list(resp.data[0].embedding)
