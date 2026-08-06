"""Shared fixtures for the test suite.

All tests that need DB/external services mock them. No live Databricks
or Lakebase connections are required.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Async helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_execute_raw():
    """Patch backend.services.db.execute_raw with an AsyncMock."""
    with patch("backend.services.db.execute_raw", new_callable=AsyncMock) as m:
        yield m


@pytest.fixture
def mock_get_embedding():
    """Patch get_embedding to return a deterministic 1024-dim vector."""
    fake_embedding = [0.1] * 1024

    async def _fake(text: str):
        return fake_embedding

    with patch("backend.services.embedding.get_embedding", side_effect=_fake) as m:
        m.return_value_factory = lambda: fake_embedding
        yield m


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def now():
    return datetime.now(timezone.utc)
