"""Session store (STM) - conversation history per session."""

import asyncio
import json as _json
import logging
import uuid
from datetime import datetime, timezone

from backend.config import config
from backend.models import Message, MessageRole, Session
from backend.services.db import execute_raw, is_schema_ownership_error

logger = logging.getLogger(__name__)


async def _execute_optional_schema_change(sql: str, description: str) -> None:
    """Run additive DDL, skipping ownership errors on handoff databases."""
    try:
        await execute_raw(sql)
    except Exception as e:
        if is_schema_ownership_error(e):
            logger.warning("Skipping session schema change (%s): %s", description, e)
            return
        raise


class SessionStore:
    """Manages conversation sessions and message history (Short-Term Memory)."""

    async def initialize(self) -> None:
        """Create sessions and messages tables."""
        await execute_raw("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                genie_conversation_ids JSONB DEFAULT '{}'::jsonb
            )
        """)
        # Additive migrations
        await _execute_optional_schema_change(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS genie_conversation_ids JSONB DEFAULT '{}'::jsonb",
            "add genie_conversation_ids",
        )
        await _execute_optional_schema_change(
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS title TEXT",
            "add title",
        )
        await execute_raw("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(session_id),
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await _execute_optional_schema_change(
            "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at)",
            "create messages session index",
        )
        logger.info("Session store initialized")

    async def create_session(self, user_id: str) -> Session:
        """Create a new conversation session."""
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        await execute_raw(
            "INSERT INTO sessions (session_id, user_id, created_at, updated_at) VALUES (:sid, :uid, :now, :now)",
            {"sid": session_id, "uid": user_id, "now": now},
        )
        return Session(session_id=session_id, user_id=user_id, created_at=now, updated_at=now)

    async def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID."""
        results = await execute_raw(
            "SELECT * FROM sessions WHERE session_id = :sid", {"sid": session_id}
        )
        if not results:
            return None
        return self._row_to_session(results[0])

    @staticmethod
    def _row_to_session(r: dict) -> Session:
        conv_ids = r.get("genie_conversation_ids") or {}
        if isinstance(conv_ids, str):
            conv_ids = _json.loads(conv_ids)
        return Session(
            session_id=r["session_id"],
            user_id=r["user_id"],
            title=r.get("title"),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            genie_conversation_ids=conv_ids,
        )

    async def set_title(self, session_id: str, title: str) -> None:
        """Set a short descriptive title for the session (only if not yet titled)."""
        await execute_raw(
            "UPDATE sessions SET title = :title WHERE session_id = :sid AND title IS NULL",
            {"title": title, "sid": session_id},
        )

    async def rename(self, session_id: str, title: str) -> bool:
        """Rename a session (unconditional title update)."""
        await execute_raw(
            "UPDATE sessions SET title = :title, updated_at = NOW() WHERE session_id = :sid",
            {"title": title, "sid": session_id},
        )
        return True

    async def set_genie_conversation_id(
        self, session_id: str, space_id: str, conversation_id: str
    ) -> None:
        """Store a Genie conversation ID for a specific space in this session.

        Uses JSONB merge so each space maintains its own conversation independently.
        """
        import json
        patch = json.dumps({space_id: conversation_id})
        await execute_raw(
            "UPDATE sessions SET genie_conversation_ids = COALESCE(genie_conversation_ids, '{}'::jsonb) || :patch::jsonb WHERE session_id = :sid",
            {"patch": patch, "sid": session_id},
        )

    async def add_message(self, session_id: str, role: MessageRole, content: str) -> Message:
        """Add a message to a session (parallel DB calls)."""
        msg_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        await asyncio.gather(
            execute_raw(
                """INSERT INTO messages (id, session_id, role, content, created_at)
                   VALUES (:id, :sid, :role, :content, :now)""",
                {"id": msg_id, "sid": session_id, "role": role.value, "content": content, "now": now},
            ),
            execute_raw(
                "UPDATE sessions SET updated_at = :now WHERE session_id = :sid",
                {"now": now, "sid": session_id},
            ),
        )
        return Message(id=msg_id, session_id=session_id, role=role, content=content, created_at=now)

    async def get_history(self, session_id: str, limit: int = 20) -> list[Message]:
        """Get conversation history for a session, ordered chronologically."""
        results = await execute_raw(
            """SELECT id, session_id, role, content, created_at
               FROM messages WHERE session_id = :sid
               ORDER BY created_at ASC LIMIT :limit""",
            {"sid": session_id, "limit": limit},
        )
        return [
            Message(
                id=r["id"],
                session_id=r["session_id"],
                role=MessageRole(r["role"]),
                content=r["content"],
                created_at=r["created_at"],
            )
            for r in results
        ]

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session and all its messages."""
        await execute_raw("DELETE FROM messages WHERE session_id = :sid", {"sid": session_id})
        await execute_raw("DELETE FROM sessions WHERE session_id = :sid", {"sid": session_id})
        return True

    async def clear_all(self, user_id: str) -> int:
        """Delete ALL sessions (and their messages) for a user."""
        sessions = await execute_raw(
            "SELECT session_id FROM sessions WHERE user_id = :uid", {"uid": user_id}
        )
        if not sessions:
            return 0
        sids = [s["session_id"] for s in sessions]
        for sid in sids:
            await execute_raw("DELETE FROM messages WHERE session_id = :sid", {"sid": sid})
        results = await execute_raw(
            "DELETE FROM sessions WHERE user_id = :uid RETURNING session_id", {"uid": user_id}
        )
        count = len(results)
        if count:
            logger.info(f"Cleared {count} sessions for user {user_id}")
        return count

    async def evict(self, max_age_days: int | None = None) -> int:
        """Delete sessions untouched for ``max_age_days``. Returns the count.

        Sessions and their messages otherwise grow without bound: nothing expired
        them, so a workspace with steady usage accumulated a row per conversation
        forever. Messages are removed first because they hold a foreign key to
        sessions.
        """
        age_days = max_age_days if max_age_days is not None else config.session.max_age_days
        if age_days < 1:
            raise ValueError(f"max_age_days must be >= 1; got {age_days}")

        stale = await execute_raw(
            "SELECT session_id FROM sessions "
            "WHERE updated_at < NOW() - (INTERVAL '1 day' * :age_days)",
            {"age_days": int(age_days)},
        )
        if not stale:
            return 0

        for row in stale:
            await execute_raw(
                "DELETE FROM messages WHERE session_id = :sid", {"sid": row["session_id"]}
            )
        results = await execute_raw(
            "DELETE FROM sessions "
            "WHERE updated_at < NOW() - (INTERVAL '1 day' * :age_days) "
            "RETURNING session_id",
            {"age_days": int(age_days)},
        )
        count = len(results)
        if count:
            logger.info(f"Evicted {count} sessions older than {age_days} days")
        return count

    async def get_recent_sessions(self, user_id: str, limit: int = 10) -> list[Session]:
        """Get recent sessions for a user."""
        results = await execute_raw(
            """SELECT * FROM sessions WHERE user_id = :uid
               ORDER BY updated_at DESC LIMIT :limit""",
            {"uid": user_id, "limit": limit},
        )
        return [self._row_to_session(r) for r in results]


session_store = SessionStore()
