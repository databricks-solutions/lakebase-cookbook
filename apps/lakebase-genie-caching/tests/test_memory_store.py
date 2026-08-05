"""Tests for UserMemoryStore with mocked DB (execute_raw) and embedding service."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from backend.services.memory_store import UserMemoryStore
from backend.models import MemoryEntry, MemoryType

FAKE_EMBEDDING = [0.1, 0.2, 0.3]


def _make_store():
    return UserMemoryStore()


def _patch_deps():
    """Return a context manager that patches execute_raw and get_embedding."""
    mock_exec = AsyncMock()
    mock_embed = AsyncMock(return_value=FAKE_EMBEDDING)
    return (
        patch("backend.services.memory_store.execute_raw", mock_exec),
        patch("backend.services.memory_store.get_embedding", mock_embed),
        mock_exec,
        mock_embed,
    )


# ---------------------------------------------------------------------------
# add_or_update
# ---------------------------------------------------------------------------

class TestAddOrUpdate:
    @pytest.mark.asyncio
    async def test_insert_new_entry(self):
        store = _make_store()
        p1, p2, mock_exec, mock_embed = _patch_deps()
        mock_exec.side_effect = [
            [],   # is_blocked -> no blocklist match
            [],   # dedup check -> no existing match
            None, # INSERT
        ]
        with p1, p2:
            entry = await store.add_or_update("u1", "Prefers dark mode")

        assert entry is not None
        assert entry.user_id == "u1"
        assert entry.content == "Prefers dark mode"
        assert entry.score == 1.0
        assert entry.recurrence_count == 1

    @pytest.mark.asyncio
    async def test_boost_existing_entry(self):
        store = _make_store()
        p1, p2, mock_exec, mock_embed = _patch_deps()
        now = datetime.now(timezone.utc)
        mock_exec.side_effect = [
            [],   # is_blocked
            [{    # dedup found
                "id": "existing-1",
                "score": 1.5,
                "recurrence_count": 2,
                "created_at": now,
                "memory_type": "preference",
                "similarity": 0.95,
            }],
            None, # UPDATE
        ]
        with p1, p2:
            entry = await store.add_or_update("u1", "Prefers dark mode")

        assert entry is not None
        assert entry.id == "existing-1"
        assert entry.score == 1.6
        assert entry.recurrence_count == 3

    @pytest.mark.asyncio
    async def test_blocked_returns_none(self):
        store = _make_store()
        p1, p2, mock_exec, mock_embed = _patch_deps()
        mock_exec.side_effect = [
            [{"1": 1}],  # is_blocked -> match found
        ]
        with p1, p2:
            entry = await store.add_or_update("u1", "blocked content")

        assert entry is None


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

class TestSearch:
    @pytest.mark.asyncio
    async def test_returns_entries_sorted_by_similarity(self):
        store = _make_store()
        now = datetime.now(timezone.utc)
        p1, p2, mock_exec, mock_embed = _patch_deps()
        mock_exec.return_value = [
            {
                "id": "m1", "user_id": "u1", "content": "Prefers SQL",
                "memory_type": "preference", "score": 2.0,
                "recurrence_count": 3, "last_seen_at": now,
                "created_at": now, "archived_at": None, "similarity": 0.95,
            },
            {
                "id": "m2", "user_id": "u1", "content": "Uses dark mode",
                "memory_type": "preference", "score": 1.0,
                "recurrence_count": 1, "last_seen_at": now,
                "created_at": now, "archived_at": None, "similarity": 0.80,
            },
        ]
        with p1, p2:
            results = await store.search("SQL queries", "u1")

        assert len(results) == 2
        assert results[0].content == "Prefers SQL"
        assert isinstance(results[0], MemoryEntry)


# ---------------------------------------------------------------------------
# delete (soft) and restore
# ---------------------------------------------------------------------------

class TestDeleteRestore:
    @pytest.mark.asyncio
    async def test_soft_delete(self):
        store = _make_store()
        p1, p2, mock_exec, mock_embed = _patch_deps()
        mock_exec.side_effect = [
            [{"user_id": "u1", "content": "test", "embedding": "[0.1,0.2,0.3]"}],
            None,  # UPDATE archived_at
            None,  # INSERT into blocklist
        ]
        with p1, p2:
            result = await store.delete("entry-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self):
        store = _make_store()
        p1, p2, mock_exec, mock_embed = _patch_deps()
        mock_exec.return_value = []
        with p1, p2:
            result = await store.delete("no-such-id")
        assert result is False

    @pytest.mark.asyncio
    async def test_restore(self):
        store = _make_store()
        p1, p2, mock_exec, mock_embed = _patch_deps()
        mock_exec.side_effect = [
            [{"id": "entry-1"}],  # UPDATE RETURNING id
            [{"content": "restored content"}],  # SELECT content
            None,  # DELETE from blocklist
        ]
        with p1, p2:
            result = await store.restore("entry-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_restore_not_archived_returns_false(self):
        store = _make_store()
        p1, p2, mock_exec, mock_embed = _patch_deps()
        mock_exec.return_value = []
        with p1, p2:
            result = await store.restore("entry-1")
        assert result is False


# ---------------------------------------------------------------------------
# is_blocked
# ---------------------------------------------------------------------------

class TestIsBlocked:
    @pytest.mark.asyncio
    async def test_blocked(self):
        store = _make_store()
        p1, p2, mock_exec, mock_embed = _patch_deps()
        mock_exec.return_value = [{"1": 1}]
        with p1, p2:
            assert await store.is_blocked(FAKE_EMBEDDING, "u1") is True

    @pytest.mark.asyncio
    async def test_not_blocked(self):
        store = _make_store()
        p1, p2, mock_exec, mock_embed = _patch_deps()
        mock_exec.return_value = []
        with p1, p2:
            assert await store.is_blocked(FAKE_EMBEDDING, "u1") is False


# ---------------------------------------------------------------------------
# apply_decay
# ---------------------------------------------------------------------------

class TestApplyDecay:
    @pytest.mark.asyncio
    async def test_returns_count(self):
        store = _make_store()
        p1, p2, mock_exec, mock_embed = _patch_deps()
        mock_exec.return_value = [{"id": "m1"}, {"id": "m2"}]
        with p1, p2:
            count = await store.apply_decay("u1")
        assert count == 2


# ---------------------------------------------------------------------------
# evict
# ---------------------------------------------------------------------------

class TestEvict:
    @pytest.mark.asyncio
    async def test_evicts_and_blocklists(self):
        store = _make_store()
        p1, p2, mock_exec, mock_embed = _patch_deps()
        mock_exec.side_effect = [
            [{"id": "m1", "user_id": "u1", "content": "old", "embedding": "[0.1,0.2]"}],
            None,  # _add_to_blocklist INSERT
            [{"id": "m1"}],  # UPDATE SET archived_at RETURNING
        ]
        with p1, p2:
            count = await store.evict()
        assert count == 1
