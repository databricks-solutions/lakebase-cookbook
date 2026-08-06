"""Tests for Pydantic models: validation, serialization, defaults."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.models import (
    AskRequest,
    AskResponse,
    CacheEntry,
    CacheSearchResult,
    CacheStatus,
    FAQUploadRequest,
    FeedbackRequest,
    FeedbackResponse,
    MemoryEntry,
    Message,
    MessageRole,
    RecordType,
    Session,
    Trace,
)


class TestAskRequest:
    def test_basic_creation(self):
        req = AskRequest(question="What is the revenue?")
        assert req.question == "What is the revenue?"
        assert req.session_id is None
        assert req.user_id == "unknown"

    def test_with_all_fields(self):
        req = AskRequest(question="test", session_id="sess-1", user_id="user-1")
        assert req.session_id == "sess-1"
        assert req.user_id == "user-1"

    def test_empty_question_allowed(self):
        req = AskRequest(question="")
        assert req.question == ""

    def test_missing_question_raises(self):
        with pytest.raises(ValidationError):
            AskRequest()


class TestFeedbackRequest:
    def test_thumbs_up(self):
        req = FeedbackRequest(trace_id="t1", rating=1)
        assert req.rating == 1

    def test_thumbs_down(self):
        req = FeedbackRequest(trace_id="t1", rating=-1)
        assert req.rating == -1

    def test_zero_rating(self):
        req = FeedbackRequest(trace_id="t1", rating=0)
        assert req.rating == 0

    def test_invalid_rating_too_high(self):
        with pytest.raises(ValidationError):
            FeedbackRequest(trace_id="t1", rating=2)

    def test_invalid_rating_too_low(self):
        with pytest.raises(ValidationError):
            FeedbackRequest(trace_id="t1", rating=-2)


class TestCacheStatus:
    def test_enum_values(self):
        assert CacheStatus.HIT == "hit"
        assert CacheStatus.MISS == "miss"
        assert CacheStatus.REJECTED == "rejected"

    def test_string_coercion(self):
        assert CacheStatus("hit") == CacheStatus.HIT


class TestRecordType:
    def test_enum_values(self):
        assert RecordType.FAQ == "faq"
        assert RecordType.TRACE == "trace"


class TestAskResponse:
    def test_minimal_response(self):
        resp = AskResponse(
            question="test",
            cache_status=CacheStatus.MISS,
            latency_ms=150.0,
            trace_id="t1",
            session_id="s1",
        )
        assert resp.sql is None
        assert resp.columns is None
        assert resp.data is None
        assert resp.description is None
        assert resp.sub_results is None
        assert resp.supervisor_plan is None

    def test_full_response(self):
        resp = AskResponse(
            question="test",
            rewritten_question="rewritten test",
            intent="data_query",
            sql="SELECT 1",
            description="A number",
            columns=["col1"],
            data=[[1]],
            row_count=1,
            cache_status=CacheStatus.HIT,
            similarity_score=0.95,
            latency_ms=50.0,
            genie_latency_ms=40.0,
            trace_id="t1",
            session_id="s1",
            session_title="My session",
            memory_context=["preference1"],
            follow_up_questions=["What else?"],
            mlflow_trace_url="https://example.com/trace",
            selected_space_id="space-1",
            selected_space_title="Space One",
            sub_results=[{"space_id": "s1", "sql": "SELECT 1"}],
            supervisor_plan=[{"agent": "s1", "task": "get data"}],
        )
        assert resp.rewritten_question == "rewritten test"
        assert len(resp.sub_results) == 1
        assert len(resp.supervisor_plan) == 1

    def test_serialization_round_trip(self):
        resp = AskResponse(
            question="test",
            cache_status="hit",
            latency_ms=100.0,
            trace_id="t1",
            session_id="s1",
        )
        data = resp.model_dump()
        assert data["cache_status"] == "hit"
        resp2 = AskResponse(**data)
        assert resp2.question == resp.question


class TestCacheEntry:
    def test_defaults(self):
        now = datetime.now(timezone.utc)
        entry = CacheEntry(
            id="e1",
            query_text="revenue by quarter",
            query_normalized="revenue quarter",
            cached_sql="SELECT * FROM revenue",
            genie_space_id="space-1",
            created_at=now,
            updated_at=now,
        )
        assert entry.hit_count == 0
        assert entry.record_type == "trace"
        assert entry.parameters is None
        assert entry.metadata is None


class TestCacheSearchResult:
    def test_creation(self):
        now = datetime.now(timezone.utc)
        entry = CacheEntry(
            id="e1", query_text="q", query_normalized="q",
            cached_sql="SQL", genie_space_id="s1",
            created_at=now, updated_at=now,
        )
        result = CacheSearchResult(entry=entry, similarity_score=0.92)
        assert result.similarity_score == 0.92
        assert result.entry.id == "e1"


class TestFAQUploadRequest:
    def test_required_fields(self):
        req = FAQUploadRequest(question="q", sql="SELECT 1", genie_space_id="s1")
        assert req.metadata is None

    def test_with_metadata(self):
        req = FAQUploadRequest(
            question="q", sql="SELECT 1", genie_space_id="s1",
            metadata={"source": "admin"},
        )
        assert req.metadata["source"] == "admin"


class TestSession:
    def test_defaults(self):
        now = datetime.now(timezone.utc)
        s = Session(session_id="s1", user_id="u1", created_at=now, updated_at=now)
        assert s.title is None
        assert s.genie_conversation_ids == {}

    def test_with_conversation_ids(self):
        now = datetime.now(timezone.utc)
        s = Session(
            session_id="s1", user_id="u1",
            created_at=now, updated_at=now,
            genie_conversation_ids={"space-1": "conv-1"},
        )
        assert s.genie_conversation_ids["space-1"] == "conv-1"


class TestMessage:
    def test_creation(self):
        now = datetime.now(timezone.utc)
        msg = Message(
            id="m1", session_id="s1", role=MessageRole.USER,
            content="Hello", created_at=now,
        )
        assert msg.role == MessageRole.USER

    def test_role_enum(self):
        assert MessageRole.USER == "user"
        assert MessageRole.ASSISTANT == "assistant"
        assert MessageRole.SYSTEM == "system"


class TestTrace:
    def test_minimal(self):
        now = datetime.now(timezone.utc)
        t = Trace(
            id="t1", session_id="s1", user_id="u1",
            question="test", cache_status=CacheStatus.MISS,
            latency_ms=100.0, created_at=now,
        )
        assert t.sql is None
        assert t.sub_results is None
        assert t.rating is None

    def test_with_sub_results(self):
        now = datetime.now(timezone.utc)
        t = Trace(
            id="t1", session_id="s1", user_id="u1",
            question="test", cache_status=CacheStatus.MISS,
            latency_ms=100.0, created_at=now,
            sub_results=[
                {"sub_question": "q1", "sql": "SELECT 1", "space_id": "sp1"},
                {"sub_question": "q2", "sql": "SELECT 2", "space_id": "sp2"},
            ],
        )
        assert len(t.sub_results) == 2
        assert t.sub_results[0]["space_id"] == "sp1"


class TestMemoryEntry:
    def test_defaults(self):
        now = datetime.now(timezone.utc)
        e = MemoryEntry(
            id="m1", user_id="u1", content="Prefers SQL",
            last_seen_at=now, created_at=now,
        )
        assert e.score == 1.0
        assert e.recurrence_count == 1
