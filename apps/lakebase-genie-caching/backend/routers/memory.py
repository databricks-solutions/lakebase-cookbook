"""Memory inspection endpoints: STM (sessions) and User Memory browsing."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.models import MemoryEntry, Message, Session
from backend.services.authz import require_self
from backend.services.memory_store import memory_store
from backend.services.session_store import session_store
from backend.services.trace_store import trace_store

router = APIRouter(prefix="/api/memory", tags=["memory"])


# --- Response models ---

class SessionListResponse(BaseModel):
    sessions: list[Session]


class SessionHistoryResponse(BaseModel):
    session: Session | None
    messages: list[Message]


class MemoryListResponse(BaseModel):
    entries: list[MemoryEntry]


class MetricsResponse(BaseModel):
    total_queries: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_rejections: int = 0
    hit_rate: float = 0.0
    avg_latency_hit_ms: float = 0.0
    avg_latency_miss_ms: float = 0.0
    latency_savings_ms: float = 0.0
    cache_size: int = 0


# --- STM: Sessions & Messages ---

@router.get("/sessions/{user_id}", response_model=SessionListResponse)
async def get_sessions(
    request: Request, user_id: str, limit: int = 20
) -> SessionListResponse:
    """List recent conversation sessions for a user (Short-Term Memory)."""
    require_self(request, user_id)
    sessions = await session_store.get_recent_sessions(user_id, limit=limit)
    return SessionListResponse(sessions=sessions)


@router.get("/sessions/{user_id}/{session_id}", response_model=SessionHistoryResponse)
async def get_session_history(
    request: Request, user_id: str, session_id: str, limit: int = 50
) -> SessionHistoryResponse:
    """Get full message history for a specific session."""
    require_self(request, user_id)
    session = await session_store.get_session(session_id)
    messages = await session_store.get_history(session_id, limit=limit)
    return SessionHistoryResponse(session=session, messages=messages)


class RenameRequest(BaseModel):
    title: str


@router.put("/sessions/{session_id}/rename")
async def rename_session(request: Request, session_id: str, req: RenameRequest):
    """Rename a conversation session."""
    # This route has no user_id in the path, so resolve the owner from the
    # session itself before allowing the write.
    existing = await session_store.get_session(session_id)
    if existing is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Session not found")
    require_self(request, existing.user_id)

    await session_store.rename(session_id, req.title)
    session = await session_store.get_session(session_id)
    return {"ok": True, "session": session}


# --- User Memory ---

@router.get("/entries/{user_id}", response_model=MemoryListResponse)
async def get_memory_entries(
    request: Request, user_id: str, limit: int = 30
) -> MemoryListResponse:
    """List user memory entries (preferences, insights, patterns)."""
    require_self(request, user_id)
    entries = await memory_store.list_entries(user_id, limit=limit)
    return MemoryListResponse(entries=entries)


@router.delete("/entries/{user_id}/{entry_id}")
async def delete_memory_entry(request: Request, user_id: str, entry_id: str) -> dict:
    """Soft-delete a memory entry and add it to the blocklist."""
    require_self(request, user_id)
    await memory_store.delete(entry_id)
    return {"deleted": True, "id": entry_id}


@router.post("/entries/{user_id}/{entry_id}/restore")
async def restore_memory_entry(request: Request, user_id: str, entry_id: str) -> dict:
    """Restore a soft-deleted memory entry and remove it from the blocklist."""
    require_self(request, user_id)
    found = await memory_store.restore(entry_id)
    if not found:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Memory entry not found or not archived")
    return {"restored": True, "id": entry_id}


@router.delete("/entries/{user_id}")
async def clear_all_memory_entries(request: Request, user_id: str) -> dict:
    """Soft-delete ALL memory entries for a user and blocklist them."""
    require_self(request, user_id)
    count = await memory_store.clear_all(user_id)
    return {"cleared": True, "count": count}


# --- Session deletion ---

@router.delete("/sessions/{user_id}/{session_id}")
async def delete_session(request: Request, user_id: str, session_id: str) -> dict:
    """Delete a single conversation session and its messages."""
    require_self(request, user_id)
    await session_store.delete_session(session_id)
    return {"deleted": True, "session_id": session_id}


@router.delete("/sessions/{user_id}")
async def clear_all_sessions(request: Request, user_id: str) -> dict:
    """Delete ALL sessions (and messages) for a user."""
    require_self(request, user_id)
    count = await session_store.clear_all(user_id)
    return {"cleared": True, "count": count}


# --- Metrics ---

@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics() -> MetricsResponse:
    from backend.services.cache_store import cache_store

    metrics = await trace_store.get_metrics()
    cache_size = await cache_store.count()
    return MetricsResponse(
        cache_size=cache_size,
        **metrics,
    )
