"""Semantic cache store with abstract base class and Lakebase pgvector implementation.

The cache stores **SQL only** -- never result sets, and never the assistant's
natural-language answer. Every hit re-executes the cached SQL, so what a caller
sees is decided by the warehouse and Unity Catalog at request time rather than
replayed from storage.

Supports two record types:
  - TRACE: auto-populated from thumbs-up traces (offline pipeline)
  - FAQ:   curated question/SQL pairs uploaded by admins

Entries can optionally have parameterized SQL templates with entity placeholders
that are populated at query time via the online pipeline.

Entity-masked template embeddings enable structural matching: when entities are
extracted at ingest, the question is re-embedded with entity values replaced by
``[PARAM]`` placeholders. At search time both the regular and template embeddings
are compared, so queries with different entities but identical structure match.
"""

import json
import logging
import re
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from backend.config import config
from backend.models import CacheEntry, CacheSearchResult, RecordType
from backend.services.db import execute_raw, is_schema_ownership_error
from backend.services.embedding import get_embedding
from backend.services.preprocessor import normalize_query

logger = logging.getLogger(__name__)


def _sanitize_sql(sql: str) -> str:
    """Strip accidental JSON-escaping artefacts from stored SQL."""
    s = sql.strip()
    if s.startswith('"') and s.endswith('"'):
        try:
            s = json.loads(s)
        except Exception:
            s = s[1:-1]
    s = s.replace("\\n", "\n").replace("\\t", "\t")
    return s.strip()


def mask_entities(question: str, entities: dict) -> str:
    """Replace extracted entity values in a question with [PARAM_NAME] placeholders.

    Only masks literal values (strings, numbers) — table and column names
    are structural and must remain intact.  Matching is case-insensitive.

    When the full SQL literal doesn't appear verbatim in the NL question,
    falls back to matching individual words of the entity value (longest
    first, minimum 4 chars, whole-word only) so the structural template
    still captures the slot.
    """
    masked = question

    for key in sorted(entities.keys(), key=lambda k: len(str(entities[k])), reverse=True):
        value = entities[key]
        if value is None:
            continue
        val_str = str(value)

        # Try 1: exact full-value match (case-insensitive)
        full_pattern = re.compile(re.escape(val_str), re.IGNORECASE)
        if full_pattern.search(masked):
            masked = full_pattern.sub(f"[{key}]", masked)
            continue

        # Try 2: match individual words of the entity value (longest first,
        # min 4 chars, whole-word boundary) for when the SQL literal form
        # differs from the natural language form in the question.
        words = [w for w in val_str.split() if len(w) >= 4]
        words.sort(key=len, reverse=True)
        for word in words:
            word_pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
            if word_pattern.search(masked):
                masked = word_pattern.sub(f"[{key}]", masked)
                break

    return masked


class BaseCacheStore(ABC):
    """Abstract base class for semantic cache stores."""

    @abstractmethod
    async def initialize(self) -> None:
        ...

    @abstractmethod
    async def search(
        self,
        query: str,
        space_id: str | None = None,
        embedding: list[float] | None = None,
    ) -> CacheSearchResult | None:
        ...

    @abstractmethod
    async def add(
        self,
        query: str,
        sql: str,
        space_id: str,
        record_type: str = RecordType.TRACE,
        parameterized_sql: str | None = None,
        parameters: dict | None = None,
        metadata: dict | None = None,
    ) -> CacheEntry:
        ...

    @abstractmethod
    async def add_faq(
        self,
        question: str,
        sql: str,
        space_id: str,
        metadata: dict | None = None,
    ) -> CacheEntry:
        ...

    @abstractmethod
    async def get(self, entry_id: str) -> CacheEntry | None:
        ...

    @abstractmethod
    async def delete(self, entry_id: str) -> bool:
        ...

    @abstractmethod
    async def list_entries(self, limit: int = 50, offset: int = 0) -> list[CacheEntry]:
        ...

    @abstractmethod
    async def increment_hit(self, entry_id: str) -> None:
        ...

    @abstractmethod
    async def evict(self, max_age_days: int | None = None) -> dict:
        ...

    @abstractmethod
    async def count(self) -> int:
        ...

    @abstractmethod
    async def clear_all(self) -> int:
        """Delete ALL cache entries. Returns the number of entries removed."""
        ...


def _row_to_entry(r: dict) -> CacheEntry:
    """Convert a database row dict to a CacheEntry, handling new nullable columns."""
    params = r.get("parameters")
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except (json.JSONDecodeError, TypeError):
            params = None

    meta = r.get("metadata")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (json.JSONDecodeError, TypeError):
            meta = None

    return CacheEntry(
        id=r["id"],
        query_text=r["query_text"],
        query_normalized=r["query_normalized"],
        cached_sql=r.get("cached_sql") or "",
        genie_space_id=r.get("genie_space_id") or "",
        hit_count=r.get("hit_count") or 0,
        created_at=r["created_at"],
        updated_at=r.get("updated_at") or r["created_at"],
        record_type=r.get("record_type") or "trace",
        ttl_expiry=r.get("ttl_expiry"),
        parameterized_sql=r.get("parameterized_sql"),
        parameters=params,
        metadata=meta,
        pinned=bool(r.get("pinned", False)),
    )


# Column list used by search/list/get queries
_SELECT_COLS = (
    "id, query_text, query_normalized, cached_sql, genie_space_id, "
    "hit_count, created_at, updated_at, record_type, ttl_expiry, "
    "parameterized_sql, parameters, metadata, pinned"
)


async def _execute_optional_schema_change(sql: str, description: str) -> None:
    """Run additive DDL, skipping ownership errors on handoff databases."""
    try:
        await execute_raw(sql)
    except Exception as e:
        if is_schema_ownership_error(e):
            logger.warning("Skipping cache schema change (%s): %s", description, e)
            return
        raise


class LakebaseCacheStore(BaseCacheStore):
    """Cache store backed by Lakebase PostgreSQL with pgvector."""

    async def initialize(self) -> None:
        """Create table, indexes, and run additive migration for new columns."""
        dim = config.embedding.dimensions
        await execute_raw("CREATE EXTENSION IF NOT EXISTS vector")
        await execute_raw(f"""
            CREATE TABLE IF NOT EXISTS cache_entries (
                id TEXT PRIMARY KEY,
                query_text TEXT NOT NULL,
                query_normalized TEXT NOT NULL,
                query_embedding vector({dim}) NOT NULL,
                cached_sql TEXT NOT NULL,
                genie_space_id TEXT NOT NULL,
                hit_count INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await _execute_optional_schema_change(
            "DROP INDEX IF EXISTS idx_cache_embedding",
            "drop legacy embedding index",
        )
        await _execute_optional_schema_change("""
            CREATE INDEX IF NOT EXISTS idx_cache_embedding_hnsw
            ON cache_entries USING hnsw (query_embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """, "create embedding HNSW index")

        # --- Additive migration for new columns ---
        await _execute_optional_schema_change(
            "ALTER TABLE cache_entries ADD COLUMN IF NOT EXISTS record_type TEXT DEFAULT 'trace'",
            "add record_type",
        )
        await _execute_optional_schema_change(
            "ALTER TABLE cache_entries ADD COLUMN IF NOT EXISTS parameterized_sql TEXT",
            "add parameterized_sql",
        )
        await _execute_optional_schema_change(
            "ALTER TABLE cache_entries ADD COLUMN IF NOT EXISTS parameters JSONB DEFAULT '{}'",
            "add parameters",
        )
        await _execute_optional_schema_change(
            "ALTER TABLE cache_entries ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'",
            "add metadata",
        )
        await _execute_optional_schema_change(
            "ALTER TABLE cache_entries ADD COLUMN IF NOT EXISTS pinned BOOLEAN DEFAULT FALSE",
            "add pinned",
        )
        await _execute_optional_schema_change(
            f"ALTER TABLE cache_entries ADD COLUMN IF NOT EXISTS template_embedding vector({dim})",
            "add template_embedding",
        )
        await _execute_optional_schema_change("""
            CREATE INDEX IF NOT EXISTS idx_cache_template_embedding_hnsw
            ON cache_entries USING hnsw (template_embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """, "create template embedding HNSW index")

        await _execute_optional_schema_change(
            "ALTER TABLE cache_entries ADD COLUMN IF NOT EXISTS ttl_expiry TIMESTAMPTZ",
            "add ttl_expiry",
        )
        # The cache stores SQL only. These two columns held the assistant's
        # natural-language answer (cached_answer) and a near-duplicate of
        # cached_sql (result); both are dropped so no answer text is retained.
        await _execute_optional_schema_change(
            "ALTER TABLE cache_entries DROP COLUMN IF EXISTS cached_answer",
            "drop cached_answer (SQL-only cache)",
        )
        await _execute_optional_schema_change(
            "ALTER TABLE cache_entries DROP COLUMN IF EXISTS result",
            "drop result (duplicated cached_sql)",
        )

        # Clean up a column from an abandoned design. An earlier iteration
        # partitioned the cache per identity via scope_key; that was dropped in
        # favour of a shared cache whose permission boundary is at execution time
        # (cached SQL runs as the caller -- see backend.services.auth_context).
        # Any database created by that iteration still carries the column with no
        # code reading or writing it, which is confusing residue rather than a
        # bug. Dropping it is safe precisely because nothing references it.
        await _execute_optional_schema_change(
            "ALTER TABLE cache_entries DROP COLUMN IF EXISTS scope_key",
            "drop abandoned scope_key column",
        )


        # Backfill: strip accidental JSON quoting from cached_sql
        await execute_raw(
            "UPDATE cache_entries SET cached_sql = REPLACE(REPLACE("
            "TRIM(BOTH '\"' FROM cached_sql), E'\\\\n', E'\\n'), E'\\\\t', E'\\t')"
            " WHERE cached_sql LIKE :pattern",
            {"pattern": '"%'},
        )

        # Promotion tracking: prevents re-ingestion of deleted/evicted entries
        await execute_raw("""
            CREATE TABLE IF NOT EXISTS promoted_trace_ids (
                trace_id TEXT PRIMARY KEY,
                promoted_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Backfill: seed promoted_trace_ids from existing cache entries' metadata
        await execute_raw("""
            INSERT INTO promoted_trace_ids (trace_id, promoted_at)
            SELECT metadata->>'source_trace_id', created_at
            FROM cache_entries
            WHERE metadata->>'source_trace_id' IS NOT NULL
            ON CONFLICT DO NOTHING
        """)

        logger.info("Cache store initialized (Lakebase pgvector, parameterized schema)")

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        space_id: str | None = None,
        embedding: list[float] | None = None,
    ) -> CacheSearchResult | None:
        """Search for the single best semantically similar cached query.

        Delegates to ``search_candidates`` and returns the top result.
        """
        candidates = await self.search_candidates(
            query, space_id=space_id, embedding=embedding, limit=1
        )
        return candidates[0] if candidates else None

    async def search_candidates(
        self,
        query: str,
        space_id: str | None = None,
        embedding: list[float] | None = None,
        limit: int | None = None,
    ) -> list[CacheSearchResult]:
        """Search cache returning up to ``limit`` candidates ranked by similarity.

        Uses ``answer_morph_threshold`` (0.75) as the floor so both direct hits
        (>=0.90) and SQL adaptation candidates (0.75-0.90) are returned.
        Entries past their ``ttl_expiry`` are excluded.

        The cache is shared across users on purpose: a question one person asks
        should speed up the same question for everyone. Access control lives at
        execution time instead -- cached SQL runs as the caller, so Unity Catalog
        decides who can see the data (see backend.services.auth_context).
        """
        if embedding is None:
            embedding = await get_embedding(query)
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

        search_threshold = config.cache.answer_morph_threshold
        top_k = limit or config.cache.top_k

        space_filter = ""
        params: dict = {
            "embedding": embedding_str,
            "threshold": search_threshold,
            "max_results": top_k,
        }

        if space_id:
            space_filter = "AND genie_space_id = :space_id"
            params["space_id"] = space_id


        results = await execute_raw(
            f"""
            SELECT {_SELECT_COLS},
                   GREATEST(
                       1 - (query_embedding <=> :embedding::vector),
                       COALESCE(1 - (template_embedding <=> :embedding::vector), 0)
                   ) AS similarity
            FROM cache_entries
            WHERE GREATEST(
                      1 - (query_embedding <=> :embedding::vector),
                      COALESCE(1 - (template_embedding <=> :embedding::vector), 0)
                  ) >= :threshold
                  AND (ttl_expiry IS NULL OR ttl_expiry > NOW())
                  {space_filter}
            ORDER BY similarity DESC
            LIMIT :max_results
            """,
            params,
        )

        if not results:
            return []

        return [
            CacheSearchResult(entry=_row_to_entry(r), similarity_score=r["similarity"])
            for r in results
        ]

    # ------------------------------------------------------------------
    # Add (generic)
    # ------------------------------------------------------------------

    async def add(
        self,
        query: str,
        sql: str,
        space_id: str,
        record_type: str = RecordType.TRACE,
        parameterized_sql: str | None = None,
        parameters: dict | None = None,
        metadata: dict | None = None,
    ) -> CacheEntry:
        """Add a new cache entry (trace or FAQ with SQL).

        When ``parameters`` are provided, an entity-masked template embedding
        is automatically computed and stored alongside the regular embedding.

        Only SQL is stored. The assistant's answer text is deliberately not
        persisted: every cache hit re-executes the SQL, so results are produced
        fresh under the caller's identity rather than replayed.
        A ``ttl_expiry`` is automatically computed from ``config.cache.ttl_hours``.
        """
        from datetime import timedelta
        entry_id = str(uuid.uuid4())
        normalized = normalize_query(query)
        sql = _sanitize_sql(sql)
        if parameterized_sql:
            parameterized_sql = _sanitize_sql(parameterized_sql)
        embedding = await get_embedding(query)
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
        now = datetime.now(timezone.utc)
        ttl_expiry = now + timedelta(hours=config.cache.ttl_hours)

        # Compute template embedding from entity-masked question
        tmpl_embedding_str: str | None = None
        if parameters:
            masked = mask_entities(query, parameters)
            if masked != query:
                tmpl_embedding = await get_embedding(masked)
                tmpl_embedding_str = "[" + ",".join(str(x) for x in tmpl_embedding) + "]"
                logger.info(f"Template embedding from masked question: '{masked}'")

        params_json = json.dumps(parameters) if parameters else "{}"
        meta_json = json.dumps(metadata) if metadata else "{}"

        await execute_raw(
            f"""
            INSERT INTO cache_entries (
                id, query_text, query_normalized, query_embedding,
                cached_sql, genie_space_id, hit_count, created_at, updated_at,
                record_type, ttl_expiry,
                parameterized_sql, parameters, metadata,
                template_embedding
            ) VALUES (
                :id, :query_text, :normalized, :embedding::vector,
                :sql, :space_id, 0, :now, :now,
                :record_type, :ttl_expiry,
                :parameterized_sql, :parameters::jsonb, :metadata::jsonb,
                :tmpl_embedding::vector
            )
            ON CONFLICT (id) DO NOTHING
            """,
            {
                "id": entry_id,
                "query_text": query,
                "normalized": normalized,
                "embedding": embedding_str,
                "sql": sql,
                "space_id": space_id,
                "now": now,
                "record_type": record_type,
                "ttl_expiry": ttl_expiry,
                "parameterized_sql": parameterized_sql,
                "parameters": params_json,
                "metadata": meta_json,
                "tmpl_embedding": tmpl_embedding_str,
            },
        )

        return CacheEntry(
            id=entry_id,
            query_text=query,
            query_normalized=normalized,
            cached_sql=sql,
            genie_space_id=space_id,
            hit_count=0,
            created_at=now,
            updated_at=now,
            record_type=record_type,
            ttl_expiry=ttl_expiry,
            parameterized_sql=parameterized_sql,
            parameters=parameters,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Add FAQ
    # ------------------------------------------------------------------

    async def add_faq(
        self,
        question: str,
        sql: str,
        space_id: str,
        metadata: Optional[dict] = None,
        parameterized_sql: Optional[str] = None,
        parameters: Optional[dict] = None,
    ) -> CacheEntry:
        """Add a curated FAQ entry to the cache.

        FAQ entries are question→SQL pairs scoped to a specific Genie space.
        On cache hit the SQL is executed against the warehouse, just like
        trace-based cache entries.

        When ``parameterized_sql`` and ``parameters`` are provided, the entry
        stores a SQL template with ``:param`` placeholders and an entity-masked
        ``template_embedding`` so that structurally identical queries with
        different entity values match at high similarity.
        """
        entry_id = str(uuid.uuid4())
        normalized = normalize_query(question)
        embedding = await get_embedding(question)
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
        now = datetime.now(timezone.utc)

        # Compute template embedding from entity-masked question
        tmpl_embedding_str: str | None = None
        if parameters:
            masked = mask_entities(question, parameters)
            if masked != question:
                tmpl_embedding = await get_embedding(masked)
                tmpl_embedding_str = "[" + ",".join(str(x) for x in tmpl_embedding) + "]"
                logger.info(f"FAQ template embedding from: '{masked}'")

        meta_json = json.dumps(metadata) if metadata else "{}"
        params_json = json.dumps(parameters) if parameters else "{}"

        await execute_raw(
            f"""
            INSERT INTO cache_entries (
                id, query_text, query_normalized, query_embedding,
                cached_sql, genie_space_id, hit_count, created_at, updated_at,
                record_type, ttl_expiry,
                parameterized_sql, parameters, metadata, pinned,
                template_embedding
            ) VALUES (
                :id, :query_text, :normalized, :embedding::vector,
                :sql, :space_id, 0, :now, :now,
                :record_type, NULL,
                :parameterized_sql, :parameters::jsonb, :metadata::jsonb, TRUE,
                :tmpl_embedding::vector
            )
            ON CONFLICT (id) DO NOTHING
            """,
            {
                "id": entry_id,
                "query_text": question,
                "normalized": normalized,
                "embedding": embedding_str,
                "sql": sql,
                "space_id": space_id,
                "now": now,
                "record_type": RecordType.FAQ,
                "parameterized_sql": parameterized_sql,
                "parameters": params_json,
                "metadata": meta_json,
                "tmpl_embedding": tmpl_embedding_str,
            },
        )

        return CacheEntry(
            id=entry_id,
            query_text=question,
            query_normalized=normalized,
            cached_sql=sql,
            genie_space_id=space_id,
            hit_count=0,
            created_at=now,
            updated_at=now,
            record_type=RecordType.FAQ,
            parameterized_sql=parameterized_sql,
            parameters=parameters,
            metadata=metadata,
            pinned=True,
        )

    # ------------------------------------------------------------------
    # Get / List / Delete
    # ------------------------------------------------------------------

    async def get(self, entry_id: str) -> CacheEntry | None:
        results = await execute_raw(
            f"SELECT {_SELECT_COLS} FROM cache_entries WHERE id = :id",
            {"id": entry_id},
        )
        if not results:
            return None
        return _row_to_entry(results[0])

    async def delete(self, entry_id: str) -> bool:
        # Extract source_trace_id before deleting so we can prevent re-promotion
        rows = await execute_raw(
            "SELECT metadata->>'source_trace_id' AS trace_id FROM cache_entries WHERE id = :id",
            {"id": entry_id},
        )
        await execute_raw("DELETE FROM cache_entries WHERE id = :id", {"id": entry_id})
        if rows and rows[0].get("trace_id"):
            await self.record_promotion(rows[0]["trace_id"])
        return True

    async def list_entries(self, limit: int = 50, offset: int = 0) -> list[CacheEntry]:
        results = await execute_raw(
            f"SELECT {_SELECT_COLS} FROM cache_entries ORDER BY created_at DESC LIMIT :limit OFFSET :offset",
            {"limit": limit, "offset": offset},
        )
        return [_row_to_entry(r) for r in results]

    async def increment_hit(self, entry_id: str) -> None:
        await execute_raw(
            "UPDATE cache_entries SET hit_count = hit_count + 1, updated_at = NOW() WHERE id = :id",
            {"id": entry_id},
        )

    async def evict(self, max_age_days: int | None = None) -> dict:
        """Run all eviction strategies and return per-strategy counts.

        Strategies (in order):
          0. TTL: remove entries past their ttl_expiry
          1. Age: remove entries older than max_age_days (default 90)
          2. Stale: remove entries not hit in stale_days (default 7),
             using updated_at which is refreshed on every cache hit
          3. Overflow: if total entries exceed max_entries (default 10000),
             remove the least valuable (lowest hit_count, oldest updated_at)
        """
        stats = {"ttl": 0, "age": 0, "stale": 0, "overflow": 0}

        # 0. TTL: entries past their ttl_expiry (skip pinned)
        ttl_results = await execute_raw(
            "DELETE FROM cache_entries WHERE ttl_expiry IS NOT NULL AND ttl_expiry < NOW() AND NOT pinned RETURNING id"
        )
        stats["ttl"] = len(ttl_results)

        # Intervals and LIMIT are bound as parameters rather than interpolated.
        # These are int-typed config values today, but /api/tuning makes them
        # writable at runtime, so string interpolation here would put request
        # input into SQL text.

        # 1. Age-based: entries created more than N days ago (skip pinned)
        age_days = max_age_days or config.cache.max_age_days
        age_results = await execute_raw(
            "DELETE FROM cache_entries "
            "WHERE created_at < NOW() - (INTERVAL '1 day' * :age_days) "
            "AND NOT pinned RETURNING id",
            {"age_days": int(age_days)},
        )
        stats["age"] = len(age_results)

        # 2. Stale: entries not hit (updated_at not refreshed) in N days (skip pinned)
        stale_days = config.cache.stale_days
        stale_results = await execute_raw(
            "DELETE FROM cache_entries "
            "WHERE updated_at < NOW() - (INTERVAL '1 day' * :stale_days) "
            "AND NOT pinned RETURNING id",
            {"stale_days": int(stale_days)},
        )
        stats["stale"] = len(stale_results)

        # 3. Overflow: keep only the top max_entries by value (skip pinned)
        max_entries = config.cache.max_entries
        current_count = await self.count()
        if current_count > max_entries:
            excess = current_count - max_entries
            overflow_results = await execute_raw(
                """DELETE FROM cache_entries
                    WHERE id IN (
                        SELECT id FROM cache_entries
                        WHERE NOT pinned
                        ORDER BY hit_count ASC, updated_at ASC
                        LIMIT :excess
                    )
                    RETURNING id""",
                {"excess": int(excess)},
            )
            stats["overflow"] = len(overflow_results)

        total = stats["ttl"] + stats["age"] + stats["stale"] + stats["overflow"]
        if total:
            logger.info(
                f"Cache eviction: {total} total "
                f"(ttl={stats['ttl']}, age={stats['age']}, stale={stats['stale']}, overflow={stats['overflow']})"
            )
        return stats

    async def set_pinned(self, entry_id: str, pinned: bool) -> bool:
        results = await execute_raw(
            "UPDATE cache_entries SET pinned = :pinned WHERE id = :id RETURNING id",
            {"id": entry_id, "pinned": pinned},
        )
        return len(results) > 0

    # ------------------------------------------------------------------
    # Promotion tracking
    # ------------------------------------------------------------------

    async def is_promoted(self, trace_id: str) -> bool:
        results = await execute_raw(
            "SELECT 1 FROM promoted_trace_ids WHERE trace_id = :id",
            {"id": trace_id},
        )
        return len(results) > 0

    async def claim_promotion(self, trace_id: str) -> bool:
        """Atomically claim ``trace_id`` for promotion.

        Returns True if this caller won the claim, False if it was already
        claimed. Prefer this over ``is_promoted`` + ``record_promotion``: those
        two calls are check-then-act, so a scheduled run and a UI-triggered run
        overlapping can both see "not promoted" and both write a cache entry for
        the same trace. The unique primary key on trace_id makes a single
        INSERT ... ON CONFLICT the arbiter instead.
        """
        results = await execute_raw(
            "INSERT INTO promoted_trace_ids (trace_id) VALUES (:id) "
            "ON CONFLICT (trace_id) DO NOTHING RETURNING trace_id",
            {"id": trace_id},
        )
        return len(results) > 0

    async def record_promotion(self, trace_id: str) -> None:
        await execute_raw(
            "INSERT INTO promoted_trace_ids (trace_id) VALUES (:id) ON CONFLICT DO NOTHING",
            {"id": trace_id},
        )

    async def count(self) -> int:
        results = await execute_raw("SELECT COUNT(*) as cnt FROM cache_entries")
        return results[0]["cnt"] if results else 0

    async def clear_all(self) -> int:
        results = await execute_raw("DELETE FROM cache_entries RETURNING id")
        count = len(results)
        if count:
            logger.info(f"Cleared all {count} cache entries")
        return count


# Singleton instance
cache_store = LakebaseCacheStore()
