"""Embedding generation using Databricks Foundation Model API."""

import logging
from functools import lru_cache

from databricks.sdk import WorkspaceClient

from backend.config import config

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_client() -> WorkspaceClient:
    return WorkspaceClient()


async def get_embedding(text: str) -> list[float]:
    """Generate embedding for a single text using the Foundation Model API."""
    import asyncio

    def _call():
        w = _get_client()
        response = w.serving_endpoints.query(
            name=config.embedding.model_endpoint,
            input=[text],
        )
        return response.data[0].embedding

    return await asyncio.to_thread(_call)
