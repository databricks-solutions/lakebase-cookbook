"""Pydantic models for the Lakebase Genie Caching."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --- Request / Response models ---


class AskRequest(BaseModel):
    question: str
    session_id: Optional[str] = None
    user_id: str = "unknown"


class CompareRequest(BaseModel):
    question: str
    user_id: str = "unknown"


class FeedbackRequest(BaseModel):
    trace_id: str
    rating: int = Field(..., ge=-1, le=1, description="-1=thumbs down, 1=thumbs up")
    user_id: str = "unknown"


class CacheStatus(str, Enum):
    HIT = "hit"
    MISS = "miss"
    REJECTED = "rejected"
    # The cache could not be consulted at all (e.g. Lakebase unreachable). Kept
    # distinct from MISS so an outage is visible in the UI and metrics instead of
    # looking like ordinary cache behaviour.
    UNAVAILABLE = "unavailable"


class AskResponse(BaseModel):
    question: str
    rewritten_question: Optional[str] = None
    intent: Optional[str] = None
    sql: Optional[str] = None
    description: Optional[str] = None
    columns: Optional[list[str]] = None
    data: Optional[list[list]] = None
    row_count: Optional[int] = None
    cache_status: CacheStatus
    similarity_score: Optional[float] = None
    latency_ms: float
    genie_latency_ms: Optional[float] = None
    trace_id: str
    session_id: str
    session_title: Optional[str] = None
    memory_context: Optional[list[str]] = None
    genie_steps: Optional[list[dict]] = None
    follow_up_questions: Optional[list[str]] = None
    mlflow_trace_url: Optional[str] = None
    selected_space_id: Optional[str] = None
    selected_space_title: Optional[str] = None
    sub_results: Optional[list[dict]] = None  # multi-space supervisor results
    supervisor_plan: Optional[list[dict]] = None  # supervisor routing plan


class FeedbackResponse(BaseModel):
    trace_id: str
    rating: int
    cached: bool = False


# --- Cache models ---


class RecordType(str, Enum):
    FAQ = "faq"
    TRACE = "trace"


class CacheEntry(BaseModel):
    id: str
    query_text: str
    query_normalized: str
    cached_sql: str
    genie_space_id: str
    hit_count: int = 0
    created_at: datetime
    updated_at: datetime
    record_type: str = "trace"
    ttl_expiry: Optional[datetime] = None
    parameterized_sql: Optional[str] = None
    parameters: Optional[dict] = None
    metadata: Optional[dict] = None
    pinned: bool = False


class CacheSearchResult(BaseModel):
    entry: CacheEntry
    similarity_score: float


class FAQUploadRequest(BaseModel):
    question: str
    sql: str
    genie_space_id: str
    metadata: Optional[dict] = None


# --- Session / STM models ---


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Message(BaseModel):
    id: str
    session_id: str
    role: MessageRole
    content: str
    created_at: datetime


class Session(BaseModel):
    session_id: str
    user_id: str
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    genie_conversation_ids: dict[str, str] = {}  # {space_id: conversation_id}


# --- User Memory models ---


class MemoryType(str, Enum):
    PREFERENCE = "preference"
    CORRECTION = "correction"
    AVOIDANCE = "avoidance"
    DEFINITION = "definition"
    IDENTITY = "identity"


class MemoryEntry(BaseModel):
    id: str
    user_id: str
    content: str
    memory_type: MemoryType = MemoryType.PREFERENCE
    score: float = 1.0
    recurrence_count: int = 1
    last_seen_at: datetime
    created_at: datetime
    archived_at: Optional[datetime] = None


# --- Trace / Feedback models ---


class Trace(BaseModel):
    id: str
    session_id: str
    user_id: str
    question: str
    rewritten_question: Optional[str] = None
    sql: Optional[str] = None
    cache_status: CacheStatus
    similarity_score: Optional[float] = None
    latency_ms: float
    genie_latency_ms: Optional[float] = None
    genie_space_id: Optional[str] = None
    rating: Optional[int] = None
    created_at: datetime
    sub_results: Optional[list[dict]] = None  # per-space details for multi-space queries
