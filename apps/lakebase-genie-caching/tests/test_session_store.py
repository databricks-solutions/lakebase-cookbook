"""Tests for session_store with mocked database calls."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.models import MessageRole
from backend.services.session_store import SessionStore


@pytest.fixture
def store():
    return SessionStore()


@pytest.fixture
def mock_db():
    with patch("backend.services.session_store.execute_raw", new_callable=AsyncMock) as m:
        yield m


class TestCreateSession:
    @pytest.mark.asyncio
    async def test_creates_session(self, store, mock_db):
        mock_db.return_value = []
        session = await store.create_session("user-1")
        assert session.user_id == "user-1"
        assert session.session_id  # UUID generated
        assert len(session.session_id) == 36  # UUID format
        mock_db.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_has_timestamps(self, store, mock_db):
        mock_db.return_value = []
        session = await store.create_session("user-1")
        assert session.created_at is not None
        assert session.updated_at is not None
        assert session.created_at == session.updated_at


class TestGetSession:
    @pytest.mark.asyncio
    async def test_found(self, store, mock_db):
        now = datetime.now(timezone.utc)
        mock_db.return_value = [{
            "session_id": "s1",
            "user_id": "u1",
            "title": "My Chat",
            "created_at": now,
            "updated_at": now,
            "genie_conversation_ids": {"space-1": "conv-1"},
        }]
        session = await store.get_session("s1")
        assert session is not None
        assert session.session_id == "s1"
        assert session.title == "My Chat"
        assert session.genie_conversation_ids == {"space-1": "conv-1"}

    @pytest.mark.asyncio
    async def test_not_found(self, store, mock_db):
        mock_db.return_value = []
        session = await store.get_session("nonexistent")
        assert session is None

    @pytest.mark.asyncio
    async def test_genie_ids_as_json_string(self, store, mock_db):
        now = datetime.now(timezone.utc)
        mock_db.return_value = [{
            "session_id": "s1",
            "user_id": "u1",
            "title": None,
            "created_at": now,
            "updated_at": now,
            "genie_conversation_ids": '{"space-1": "conv-1"}',
        }]
        session = await store.get_session("s1")
        assert session.genie_conversation_ids == {"space-1": "conv-1"}

    @pytest.mark.asyncio
    async def test_genie_ids_none(self, store, mock_db):
        now = datetime.now(timezone.utc)
        mock_db.return_value = [{
            "session_id": "s1",
            "user_id": "u1",
            "title": None,
            "created_at": now,
            "updated_at": now,
            "genie_conversation_ids": None,
        }]
        session = await store.get_session("s1")
        assert session.genie_conversation_ids == {}


class TestSetTitle:
    @pytest.mark.asyncio
    async def test_set_title(self, store, mock_db):
        mock_db.return_value = []
        await store.set_title("s1", "New Title")
        mock_db.assert_called_once()
        call_sql = mock_db.call_args[0][0]
        assert "title IS NULL" in call_sql  # Only sets if not already titled


class TestRename:
    @pytest.mark.asyncio
    async def test_rename(self, store, mock_db):
        mock_db.return_value = []
        result = await store.rename("s1", "Renamed Title")
        assert result is True
        mock_db.assert_called_once()
        call_sql = mock_db.call_args[0][0]
        assert "title IS NULL" not in call_sql  # Unconditional update
        assert "title = :title" in call_sql


class TestAddMessage:
    @pytest.mark.asyncio
    async def test_add_message(self, store, mock_db):
        mock_db.return_value = []
        msg = await store.add_message("s1", MessageRole.USER, "Hello!")
        assert msg.session_id == "s1"
        assert msg.role == MessageRole.USER
        assert msg.content == "Hello!"
        assert msg.id  # UUID generated
        # Should make 2 DB calls: INSERT message + UPDATE session updated_at
        assert mock_db.call_count == 2


class TestGetHistory:
    @pytest.mark.asyncio
    async def test_returns_messages(self, store, mock_db):
        now = datetime.now(timezone.utc)
        mock_db.return_value = [
            {"id": "m1", "session_id": "s1", "role": "user", "content": "Hi", "created_at": now},
            {"id": "m2", "session_id": "s1", "role": "assistant", "content": "Hello!", "created_at": now},
        ]
        messages = await store.get_history("s1")
        assert len(messages) == 2
        assert messages[0].role == MessageRole.USER
        assert messages[1].role == MessageRole.ASSISTANT

    @pytest.mark.asyncio
    async def test_empty_history(self, store, mock_db):
        mock_db.return_value = []
        messages = await store.get_history("s1")
        assert messages == []


class TestGetRecentSessions:
    @pytest.mark.asyncio
    async def test_returns_sessions(self, store, mock_db):
        now = datetime.now(timezone.utc)
        mock_db.return_value = [
            {
                "session_id": "s1", "user_id": "u1", "title": "Chat 1",
                "created_at": now, "updated_at": now,
                "genie_conversation_ids": {},
            },
            {
                "session_id": "s2", "user_id": "u1", "title": None,
                "created_at": now, "updated_at": now,
                "genie_conversation_ids": {},
            },
        ]
        sessions = await store.get_recent_sessions("u1")
        assert len(sessions) == 2
        assert sessions[0].title == "Chat 1"
        assert sessions[1].title is None
