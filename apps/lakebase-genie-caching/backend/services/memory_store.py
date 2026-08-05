"""Unified User Memory store backed by Lakebase pgvector.

Consolidates long-term memory and user preferences into a single semantic
memory per user.  Each entry is a learned fact, preference, correction,
avoidance, or definition extracted from MLflow traces.

Features:
- Typed memories: preference, correction, avoidance, definition
- Embedding-based semantic retrieval for query-time context
- Score with recurrence boosting and time-based decay
- Deduplication via high-similarity check on insert
- Soft-delete (archived_at) so memories can be restored
- Embedding-based blocklist to prevent re-extraction of deleted memories
"""

import logging
import uuid
from datetime import datetime, timezone

from backend.config import config
from backend.models import MemoryEntry, MemoryType
from backend.services.db import execute_raw, is_schema_ownership_error
from backend.services.embedding import get_embedding

logger = logging.getLogger(__name__)

_ACTIVE_FILTER = "archived_at IS NULL"


async def _execute_optional_schema_change(sql: str, description: str) -> None:
    """Run additive DDL, skipping ownership errors on handoff databases."""
    try:
        await execute_raw(sql)
    except Exception as e:
        if is_schema_ownership_error(e):
            logger.warning("Skipping memory schema change (%s): %s", description, e)
            return
        raise


class UserMemoryStore:
    """Unified per-user memory with typed entries, soft-delete, and blocklist."""

    async def initialize(self) -> None:
        dim = config.embedding.dimensions
        await execute_raw(f"""
            CREATE TABLE IF NOT EXISTS user_memory (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL,
                memory_type TEXT DEFAULT 'preference',
                embedding vector({dim}) NOT NULL,
                score FLOAT DEFAULT 1.0,
                recurrence_count INTEGER DEFAULT 1,
                last_seen_at TIMESTAMPTZ DEFAULT NOW(),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                archived_at TIMESTAMPTZ
            )
        """)
        # Migrate: add columns if upgrading from an older schema
        await _execute_optional_schema_change(
            "ALTER TABLE user_memory ADD COLUMN IF NOT EXISTS memory_type TEXT DEFAULT 'preference'",
            "add memory_type",
        )
        await _execute_optional_schema_change(
            "ALTER TABLE user_memory ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ",
            "add archived_at",
        )
        await _execute_optional_schema_change(
            "DROP INDEX IF EXISTS idx_memory_embedding",
            "drop legacy memory embedding index",
        )
        await _execute_optional_schema_change(
            """CREATE INDEX IF NOT EXISTS idx_memory_embedding_hnsw
               ON user_memory USING hnsw (embedding vector_cosine_ops)
               WITH (m = 16, ef_construction = 64)""",
            "create memory HNSW index",
        )
        await _execute_optional_schema_change(
            "CREATE INDEX IF NOT EXISTS idx_memory_user ON user_memory(user_id)",
            "create memory user index",
        )

        # Blocklist table: stores embeddings of memories the user explicitly deleted
        await execute_raw(f"""
            CREATE TABLE IF NOT EXISTS memory_blocklist (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding vector({dim}) NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await _execute_optional_schema_change(
            "DROP INDEX IF EXISTS idx_blocklist_embedding",
            "drop legacy blocklist embedding index",
        )
        await _execute_optional_schema_change(
            """CREATE INDEX IF NOT EXISTS idx_blocklist_embedding_hnsw
               ON memory_blocklist USING hnsw (embedding vector_cosine_ops)
               WITH (m = 16, ef_construction = 64)""",
            "create blocklist HNSW index",
        )
        await _execute_optional_schema_change(
            "CREATE INDEX IF NOT EXISTS idx_blocklist_user ON memory_blocklist(user_id)",
            "create blocklist user index",
        )
        logger.info("User memory store initialized (with blocklist)")

    # ------------------------------------------------------------------
    # Blocklist
    # ------------------------------------------------------------------

    async def _add_to_blocklist(self, user_id: str, content: str, embedding: list[float]) -> None:
        """Add a memory to the blocklist so it won't be re-extracted."""
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
        bid = str(uuid.uuid4())
        await execute_raw(
            f"""INSERT INTO memory_blocklist (id, user_id, content, embedding, created_at)
                VALUES (:id, :uid, :content, :embedding::vector, NOW())
                ON CONFLICT DO NOTHING""",
            {"id": bid, "uid": user_id, "content": content, "embedding": embedding_str},
        )

    async def is_blocked(self, embedding: list[float], user_id: str) -> bool:
        """Check if a memory is semantically similar to a blocklisted entry."""
        threshold = config.memory.blocklist_threshold
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
        results = await execute_raw(
            f"""SELECT 1 FROM memory_blocklist
                WHERE user_id = :uid
                  AND 1 - (embedding <=> :embedding::vector) >= :threshold
                LIMIT 1""",
            {"uid": user_id, "embedding": embedding_str, "threshold": threshold},
        )
        return bool(results)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        user_id: str,
        top_k: int | None = None,
        memory_types: list[MemoryType] | None = None,
    ) -> list[MemoryEntry]:
        """Retrieve top-k active memories ranked by semantic similarity.

        Persistent memory types (identity, preference, avoidance) are always
        included regardless of similarity to the query, since they represent
        user-level context that should inform every interaction. Topic-specific
        types (correction, definition) are filtered by similarity threshold.
        """
        k = top_k or config.memory.top_k
        embedding = await get_embedding(query)
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

        type_filter = ""
        if memory_types:
            type_list = ", ".join(f"'{t.value}'" for t in memory_types)
            type_filter = f"AND memory_type IN ({type_list})"

        results = await execute_raw(
            f"""
            SELECT id, user_id, content, memory_type, score, recurrence_count,
                   last_seen_at, created_at, archived_at,
                   1 - (embedding <=> :embedding::vector) AS similarity
            FROM user_memory
            WHERE user_id = :user_id
              AND {_ACTIVE_FILTER}
              AND (
                  memory_type IN ('identity', 'preference', 'avoidance')
                  OR 1 - (embedding <=> :embedding::vector) >= :threshold
              )
              {type_filter}
            ORDER BY similarity DESC, score DESC
            LIMIT :k
            """,
            {
                "embedding": embedding_str,
                "user_id": user_id,
                "threshold": config.memory.similarity_threshold,
                "k": k,
            },
        )

        return [_row_to_entry(r) for r in results]

    # ------------------------------------------------------------------
    # Add / Update
    # ------------------------------------------------------------------

    async def add_or_update(
        self,
        user_id: str,
        content: str,
        memory_type: MemoryType = MemoryType.PREFERENCE,
    ) -> MemoryEntry | None:
        """Add a memory entry, or boost score if a semantically similar one exists.

        Returns None if the memory is blocked (user previously deleted it).
        """
        embedding = await get_embedding(content)
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
        now = datetime.now(timezone.utc)

        # Blocklist check
        if await self.is_blocked(embedding, user_id):
            logger.debug(f"Memory blocked for user {user_id}: {content[:60]}")
            return None

        # Dedup: check if a very similar active memory already exists
        existing = await execute_raw(
            f"""
            SELECT id, score, recurrence_count, created_at, memory_type,
                   1 - (embedding <=> :embedding::vector) AS similarity
            FROM user_memory
            WHERE user_id = :uid AND {_ACTIVE_FILTER}
              AND 1 - (embedding <=> :embedding::vector) >= 0.85
            ORDER BY similarity DESC LIMIT 1
            """,
            {"embedding": embedding_str, "uid": user_id},
        )

        if existing:
            eid = existing[0]["id"]
            new_count = existing[0]["recurrence_count"] + 1
            new_score = min(existing[0]["score"] + 0.1, 5.0)
            await execute_raw(
                """UPDATE user_memory SET score = :score, recurrence_count = :count,
                          last_seen_at = :now WHERE id = :id""",
                {"score": new_score, "count": new_count, "now": now, "id": eid},
            )
            return MemoryEntry(
                id=eid, user_id=user_id, content=content,
                memory_type=MemoryType(existing[0].get("memory_type", "preference")),
                score=new_score, recurrence_count=new_count,
                last_seen_at=now, created_at=existing[0].get("created_at", now),
            )
        else:
            entry_id = str(uuid.uuid4())
            await execute_raw(
                f"""
                INSERT INTO user_memory (id, user_id, content, memory_type, embedding,
                                         score, recurrence_count, last_seen_at, created_at)
                VALUES (:id, :uid, :content, :mtype, :embedding::vector, 1.0, 1, :now, :now)
                """,
                {"id": entry_id, "uid": user_id, "content": content,
                 "mtype": memory_type.value, "embedding": embedding_str, "now": now},
            )
            return MemoryEntry(
                id=entry_id, user_id=user_id, content=content,
                memory_type=memory_type,
                score=1.0, recurrence_count=1, last_seen_at=now, created_at=now,
            )

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    async def list_entries(
        self,
        user_id: str,
        limit: int = 30,
        include_archived: bool = False,
    ) -> list[MemoryEntry]:
        """List memories for a user, ordered by score."""
        archive_filter = "" if include_archived else f"AND {_ACTIVE_FILTER}"
        results = await execute_raw(
            f"""SELECT id, user_id, content, memory_type, score, recurrence_count,
                       last_seen_at, created_at, archived_at
                FROM user_memory WHERE user_id = :uid {archive_filter}
                ORDER BY score DESC, last_seen_at DESC LIMIT :limit""",
            {"uid": user_id, "limit": limit},
        )
        return [_row_to_entry(r) for r in results]

    # ------------------------------------------------------------------
    # Delete (soft) & Restore
    # ------------------------------------------------------------------

    async def delete(self, entry_id: str) -> bool:
        """Soft-delete a memory and add it to the blocklist."""
        # Fetch the entry's content and embedding before archiving
        rows = await execute_raw(
            "SELECT user_id, content, embedding FROM user_memory WHERE id = :id",
            {"id": entry_id},
        )
        if not rows:
            return False

        now = datetime.now(timezone.utc)
        await execute_raw(
            "UPDATE user_memory SET archived_at = :now WHERE id = :id",
            {"now": now, "id": entry_id},
        )

        # Add to blocklist so the pipeline doesn't re-extract this
        row = rows[0]
        embedding_raw = row.get("embedding")
        if embedding_raw:
            if isinstance(embedding_raw, str):
                embedding_raw = embedding_raw.strip("[]")
                emb_list = [float(x) for x in embedding_raw.split(",")]
            elif isinstance(embedding_raw, list):
                emb_list = embedding_raw
            else:
                emb_list = None

            if emb_list:
                await self._add_to_blocklist(row["user_id"], row["content"], emb_list)
                logger.info(f"Memory {entry_id[:8]} soft-deleted and added to blocklist")
            else:
                logger.info(f"Memory {entry_id[:8]} soft-deleted (no embedding for blocklist)")
        else:
            logger.info(f"Memory {entry_id[:8]} soft-deleted (no embedding for blocklist)")

        return True

    async def restore(self, entry_id: str) -> bool:
        """Restore a soft-deleted memory by clearing archived_at."""
        result = await execute_raw(
            "UPDATE user_memory SET archived_at = NULL WHERE id = :id AND archived_at IS NOT NULL RETURNING id",
            {"id": entry_id},
        )
        if result:
            # Also remove from blocklist so it doesn't get blocked again
            rows = await execute_raw(
                "SELECT content FROM user_memory WHERE id = :id", {"id": entry_id}
            )
            if rows:
                await execute_raw(
                    "DELETE FROM memory_blocklist WHERE user_id = (SELECT user_id FROM user_memory WHERE id = :id) AND content = :content",
                    {"id": entry_id, "content": rows[0]["content"]},
                )
            logger.info(f"Memory {entry_id[:8]} restored")
            return True
        return False

    async def clear_all(self, user_id: str) -> int:
        """Soft-delete ALL active memory entries for a user and blocklist them."""
        # First add all active entries to blocklist
        active = await execute_raw(
            f"SELECT content, embedding FROM user_memory WHERE user_id = :uid AND {_ACTIVE_FILTER}",
            {"uid": user_id},
        )
        for row in active:
            embedding_raw = row.get("embedding")
            if embedding_raw:
                if isinstance(embedding_raw, str):
                    embedding_raw = embedding_raw.strip("[]")
                    emb_list = [float(x) for x in embedding_raw.split(",")]
                elif isinstance(embedding_raw, list):
                    emb_list = embedding_raw
                else:
                    continue
                await self._add_to_blocklist(user_id, row["content"], emb_list)

        now = datetime.now(timezone.utc)
        results = await execute_raw(
            f"UPDATE user_memory SET archived_at = :now WHERE user_id = :uid AND {_ACTIVE_FILTER} RETURNING id",
            {"uid": user_id, "now": now},
        )
        count = len(results)
        if count:
            logger.info(f"Soft-deleted {count} memory entries for user {user_id}")
        return count

    # ------------------------------------------------------------------
    # Decay & Eviction
    # ------------------------------------------------------------------

    async def apply_decay(self, user_id: str) -> int:
        """Apply recency decay to memories not seen recently."""
        rate = config.memory.decay_rate
        results = await execute_raw(
            f"""UPDATE user_memory
                SET score = GREATEST(score - {rate}, 0)
                WHERE user_id = :uid AND {_ACTIVE_FILTER}
                  AND last_seen_at < NOW() - INTERVAL '7 days'
                RETURNING id""",
            {"uid": user_id},
        )
        return len(results)

    async def evict(self, max_age_days: int | None = None) -> int:
        """Evict (soft-delete) memories below score threshold or older than max_age_days.

        Also adds evicted entries to the blocklist.
        """
        threshold = config.memory.score_threshold
        days = max_age_days or config.memory.max_age_days

        # Fetch entries to be evicted so we can blocklist them
        to_evict = await execute_raw(
            f"""SELECT id, user_id, content, embedding FROM user_memory
                WHERE {_ACTIVE_FILTER}
                  AND (score < :threshold OR created_at < NOW() - INTERVAL '{days} days')""",
            {"threshold": threshold},
        )

        for row in to_evict:
            embedding_raw = row.get("embedding")
            if embedding_raw:
                if isinstance(embedding_raw, str):
                    embedding_raw = embedding_raw.strip("[]")
                    emb_list = [float(x) for x in embedding_raw.split(",")]
                elif isinstance(embedding_raw, list):
                    emb_list = embedding_raw
                else:
                    continue
                await self._add_to_blocklist(row["user_id"], row["content"], emb_list)

        now = datetime.now(timezone.utc)
        results = await execute_raw(
            f"""UPDATE user_memory SET archived_at = :now
                WHERE {_ACTIVE_FILTER}
                  AND (score < :threshold OR created_at < NOW() - INTERVAL '{days} days')
                RETURNING id""",
            {"threshold": threshold, "now": now},
        )
        count = len(results)
        if count:
            logger.info(f"Evicted {count} memory entries (soft-delete + blocklist)")
        return count


def _row_to_entry(r: dict) -> MemoryEntry:
    return MemoryEntry(
        id=r["id"],
        user_id=r["user_id"],
        content=r["content"],
        memory_type=MemoryType(r.get("memory_type", "preference")),
        score=r["score"],
        recurrence_count=r["recurrence_count"],
        last_seen_at=r["last_seen_at"],
        created_at=r["created_at"],
        archived_at=r.get("archived_at"),
    )


memory_store = UserMemoryStore()
