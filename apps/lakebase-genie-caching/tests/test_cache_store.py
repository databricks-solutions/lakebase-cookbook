"""Tests for cache_store: _row_to_entry conversion and mocked store operations."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.models import CacheEntry, RecordType
from backend.services.cache_store import LakebaseCacheStore, _row_to_entry


class TestRowToEntry:
    """Tests for _row_to_entry: converting DB row dicts to CacheEntry models."""

    def test_basic_row(self):
        now = datetime.now(timezone.utc)
        row = {
            "id": "e1",
            "query_text": "revenue by quarter",
            "query_normalized": "revenue quarter",
            "cached_sql": "SELECT * FROM revenue",
            "genie_space_id": "space-1",
            "hit_count": 5,
            "created_at": now,
            "updated_at": now,
            "record_type": "trace",
            "result": "SELECT * FROM revenue",
            "parameterized_sql": None,
            "parameters": None,
            "metadata": None,
        }
        entry = _row_to_entry(row)
        assert entry.id == "e1"
        assert entry.hit_count == 5
        assert entry.record_type == "trace"
        assert entry.parameters is None
        assert entry.metadata is None

    def test_parameters_as_json_string(self):
        now = datetime.now(timezone.utc)
        row = {
            "id": "e1",
            "query_text": "q",
            "query_normalized": "q",
            "cached_sql": "SQL",
            "genie_space_id": "s1",
            "hit_count": 0,
            "created_at": now,
            "updated_at": now,
            "record_type": "trace",
            "result": None,
            "parameterized_sql": "SELECT :phase",
            "parameters": '{"phase": "Phase 3"}',
            "metadata": '{"source": "admin"}',
        }
        entry = _row_to_entry(row)
        assert entry.parameters == {"phase": "Phase 3"}
        assert entry.metadata == {"source": "admin"}

    def test_parameters_as_dict(self):
        now = datetime.now(timezone.utc)
        row = {
            "id": "e1",
            "query_text": "q",
            "query_normalized": "q",
            "cached_sql": "SQL",
            "genie_space_id": "s1",
            "hit_count": 0,
            "created_at": now,
            "updated_at": now,
            "record_type": "faq",
            "result": "SQL",
            "parameterized_sql": None,
            "parameters": {"key": "value"},
            "metadata": {"tag": "test"},
        }
        entry = _row_to_entry(row)
        # Non-string dicts pass through as-is
        assert entry.parameters == {"key": "value"}
        assert entry.metadata == {"tag": "test"}

    def test_invalid_json_parameters(self):
        now = datetime.now(timezone.utc)
        row = {
            "id": "e1",
            "query_text": "q",
            "query_normalized": "q",
            "cached_sql": "SQL",
            "genie_space_id": "s1",
            "hit_count": 0,
            "created_at": now,
            "updated_at": now,
            "record_type": "trace",
            "result": None,
            "parameterized_sql": None,
            "parameters": "not-valid-json",
            "metadata": "also-bad",
        }
        entry = _row_to_entry(row)
        assert entry.parameters is None
        assert entry.metadata is None

    def test_missing_optional_fields(self):
        now = datetime.now(timezone.utc)
        row = {
            "id": "e2",
            "query_text": "q",
            "query_normalized": "q",
            "cached_sql": "",
            "created_at": now,
        }
        entry = _row_to_entry(row)
        assert entry.cached_sql == ""
        assert entry.genie_space_id == ""
        assert entry.hit_count == 0
        assert entry.record_type == "trace"

    def test_updated_at_fallback_to_created_at(self):
        now = datetime.now(timezone.utc)
        row = {
            "id": "e1",
            "query_text": "q",
            "query_normalized": "q",
            "cached_sql": "SQL",
            "genie_space_id": "s1",
            "hit_count": 0,
            "created_at": now,
            "updated_at": None,
            "record_type": "trace",
            "result": None,
            "parameterized_sql": None,
            "parameters": None,
            "metadata": None,
        }
        entry = _row_to_entry(row)
        assert entry.updated_at == now


class TestLakebaseCacheStoreCount:
    """Test cache store operations with mocked DB."""

    @pytest.mark.asyncio
    async def test_count(self):
        with patch("backend.services.cache_store.execute_raw", new_callable=AsyncMock) as mock_db:
            mock_db.return_value = [{"cnt": 42}]
            store = LakebaseCacheStore()
            result = await store.count()
            assert result == 42

    @pytest.mark.asyncio
    async def test_count_empty(self):
        with patch("backend.services.cache_store.execute_raw", new_callable=AsyncMock) as mock_db:
            mock_db.return_value = []
            store = LakebaseCacheStore()
            result = await store.count()
            assert result == 0

    @pytest.mark.asyncio
    async def test_delete(self):
        with patch("backend.services.cache_store.execute_raw", new_callable=AsyncMock) as mock_db:
            mock_db.return_value = []
            store = LakebaseCacheStore()
            result = await store.delete("entry-1")
            assert result is True
            # delete() first extracts source_trace_id, then deletes
            assert mock_db.call_count == 2

    @pytest.mark.asyncio
    async def test_get_found(self):
        now = datetime.now(timezone.utc)
        with patch("backend.services.cache_store.execute_raw", new_callable=AsyncMock) as mock_db:
            mock_db.return_value = [{
                "id": "e1", "query_text": "q", "query_normalized": "q",
                "cached_sql": "SQL", "genie_space_id": "s1", "hit_count": 0,
                "created_at": now, "updated_at": now, "record_type": "trace",
                "result": "SQL", "parameterized_sql": None, "parameters": None,
                "metadata": None,
            }]
            store = LakebaseCacheStore()
            entry = await store.get("e1")
            assert entry is not None
            assert entry.id == "e1"

    @pytest.mark.asyncio
    async def test_get_not_found(self):
        with patch("backend.services.cache_store.execute_raw", new_callable=AsyncMock) as mock_db:
            mock_db.return_value = []
            store = LakebaseCacheStore()
            entry = await store.get("nonexistent")
            assert entry is None

    @pytest.mark.asyncio
    async def test_list_entries(self):
        now = datetime.now(timezone.utc)
        rows = [
            {
                "id": f"e{i}", "query_text": f"q{i}", "query_normalized": f"q{i}",
                "cached_sql": "SQL", "genie_space_id": "s1", "hit_count": i,
                "created_at": now, "updated_at": now, "record_type": "trace",
                "result": "SQL", "parameterized_sql": None, "parameters": None,
                "metadata": None,
            }
            for i in range(3)
        ]
        with patch("backend.services.cache_store.execute_raw", new_callable=AsyncMock) as mock_db:
            mock_db.return_value = rows
            store = LakebaseCacheStore()
            entries = await store.list_entries(limit=3)
            assert len(entries) == 3
            assert entries[0].id == "e0"
            assert entries[2].hit_count == 2

    @pytest.mark.asyncio
    async def test_increment_hit(self):
        with patch("backend.services.cache_store.execute_raw", new_callable=AsyncMock) as mock_db:
            mock_db.return_value = []
            store = LakebaseCacheStore()
            await store.increment_hit("e1")
            mock_db.assert_called_once()
            call_sql = mock_db.call_args[0][0]
            assert "hit_count = hit_count + 1" in call_sql


def test_initialize_drops_the_abandoned_scope_key_column():
    """An abandoned design left an orphan column in already-deployed databases.

    A short-lived iteration partitioned the cache per identity via scope_key.
    That was replaced by a shared cache whose boundary is at execution time, but
    any database created while the migration existed still carries the column
    with nothing reading or writing it. initialize() must clean it up so a
    deployment upgraded in place matches a fresh one.
    """
    import inspect

    from backend.services.cache_store import LakebaseCacheStore

    source = inspect.getsource(LakebaseCacheStore.initialize)

    assert "DROP COLUMN IF EXISTS scope_key" in source

    # And no SQL should still read or write the column.
    from backend.services import cache_store as module

    store_source = inspect.getsource(module)
    offenders = [
        line.strip()
        for line in store_source.splitlines()
        if "scope_key" in line
        and "DROP COLUMN" not in line
        and "drop abandoned" not in line
        and not line.strip().startswith("#")
    ]
    assert not offenders, f"scope_key is still used in SQL: {offenders}"
