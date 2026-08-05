"""Tests for API routes using FastAPI TestClient.

These tests verify the HTTP layer: correct status codes, request/response
shapes, and proper delegation to service layer (which is mocked).
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.models import (
    CacheStatus, MemoryEntry, Message, MessageRole, Session, Trace,
)


def _make_app():
    """Create a minimal FastAPI app with just the routers under test."""
    from fastapi import FastAPI
    from backend.routers.memory import router as memory_router
    from backend.routers.feedback import router as feedback_router
    app = FastAPI()
    app.include_router(memory_router)
    app.include_router(feedback_router)
    return app


app = _make_app()


class TestMemoryRoutes:
    """Tests for /api/memory/* endpoints."""

    def test_get_sessions(self):
        now = datetime.now(timezone.utc)
        sessions = [
            Session(session_id="s1", user_id="u1", title="Chat 1", created_at=now, updated_at=now),
            Session(session_id="s2", user_id="u1", title=None, created_at=now, updated_at=now),
        ]
        with patch("backend.routers.memory.session_store") as mock_store:
            mock_store.get_recent_sessions = AsyncMock(return_value=sessions)
            client = TestClient(app)
            resp = client.get("/api/memory/sessions/u1?limit=10")

        assert resp.status_code == 200
        data = resp.json()
        assert "sessions" in data
        assert len(data["sessions"]) == 2
        assert data["sessions"][0]["session_id"] == "s1"
        assert data["sessions"][0]["title"] == "Chat 1"
        assert data["sessions"][1]["title"] is None

    def test_get_session_history(self):
        now = datetime.now(timezone.utc)
        session = Session(session_id="s1", user_id="u1", created_at=now, updated_at=now)
        messages = [
            Message(id="m1", session_id="s1", role=MessageRole.USER, content="Hi", created_at=now),
            Message(id="m2", session_id="s1", role=MessageRole.ASSISTANT, content="Hello!", created_at=now),
        ]
        with patch("backend.routers.memory.session_store") as mock_store:
            mock_store.get_session = AsyncMock(return_value=session)
            mock_store.get_history = AsyncMock(return_value=messages)
            client = TestClient(app)
            resp = client.get("/api/memory/sessions/u1/s1")

        assert resp.status_code == 200
        data = resp.json()
        assert data["session"]["session_id"] == "s1"
        assert len(data["messages"]) == 2

    def test_get_session_history_not_found(self):
        with patch("backend.routers.memory.session_store") as mock_store:
            mock_store.get_session = AsyncMock(return_value=None)
            mock_store.get_history = AsyncMock(return_value=[])
            client = TestClient(app)
            resp = client.get("/api/memory/sessions/u1/nonexistent")

        assert resp.status_code == 200
        data = resp.json()
        assert data["session"] is None
        assert data["messages"] == []

    def test_rename_session(self):
        now = datetime.now(timezone.utc)
        updated_session = Session(
            session_id="s1", user_id="u1", title="New Name",
            created_at=now, updated_at=now,
        )
        with patch("backend.routers.memory.session_store") as mock_store:
            mock_store.rename = AsyncMock(return_value=True)
            mock_store.get_session = AsyncMock(return_value=updated_session)
            client = TestClient(app)
            resp = client.put(
                "/api/memory/sessions/s1/rename",
                json={"title": "New Name"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["session"]["title"] == "New Name"
        mock_store.rename.assert_called_once_with("s1", "New Name")

    def test_get_memory_entries(self):
        now = datetime.now(timezone.utc)
        entries = [
            MemoryEntry(
                id="me1", user_id="u1", content="Prefers SQL",
                score=2.5, recurrence_count=3,
                last_seen_at=now, created_at=now,
            ),
        ]
        with patch("backend.routers.memory.memory_store") as mock_mem:
            mock_mem.list_entries = AsyncMock(return_value=entries)
            client = TestClient(app)
            resp = client.get("/api/memory/entries/u1")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["entries"]) == 1
        assert data["entries"][0]["content"] == "Prefers SQL"

    def test_get_metrics(self):
        mock_cs = AsyncMock()
        mock_cs.count = AsyncMock(return_value=42)

        with (
            patch("backend.routers.memory.trace_store") as mock_ts,
            patch("backend.services.cache_store.cache_store", mock_cs),
        ):
            mock_ts.get_metrics = AsyncMock(return_value={
                "total_queries": 100,
                "cache_hits": 30,
                "cache_misses": 65,
                "cache_rejections": 5,
                "hit_rate": 0.3,
                "avg_latency_hit_ms": 50.0,
                "avg_latency_miss_ms": 500.0,
                "latency_savings_ms": 15000.0,
            })
            client = TestClient(app)
            resp = client.get("/api/memory/metrics")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_queries"] == 100
        assert data["cache_hits"] == 30
        assert data["cache_size"] == 42


class TestFeedbackRoutes:
    """Tests for /api/feedback endpoint.

    The feedback handler uses an in-memory rating dict and fires a background
    task (MLflow + Genie API). We patch the background task to avoid real calls.
    """

    def test_submit_feedback_thumbs_up(self):
        with patch("backend.routers.feedback._background_set_rating", new_callable=AsyncMock):
            client = TestClient(app)
            resp = client.post("/api/feedback", json={
                "trace_id": "t1", "rating": 1, "user_id": "u1",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["trace_id"] == "t1"
        assert data["rating"] == 1

    def test_submit_feedback_thumbs_down(self):
        with patch("backend.routers.feedback._background_set_rating", new_callable=AsyncMock):
            client = TestClient(app)
            resp = client.post("/api/feedback", json={
                "trace_id": "t1", "rating": -1,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["rating"] == -1

    def test_submit_feedback_invalid_rating(self):
        client = TestClient(app)
        resp = client.post("/api/feedback", json={
            "trace_id": "t1", "rating": 5,
        })
        assert resp.status_code == 422

    def test_submit_feedback_missing_trace_id(self):
        client = TestClient(app)
        resp = client.post("/api/feedback", json={
            "rating": 1,
        })
        assert resp.status_code == 422
