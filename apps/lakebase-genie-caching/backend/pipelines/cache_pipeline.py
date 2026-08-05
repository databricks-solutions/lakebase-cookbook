"""Unified offline pipeline: cache promotion + memory extraction from MLflow traces.

Cache promotion (thumbs-up only):
  1. Read thumbs-up cache-miss traces from MLflow
  2. Optionally parameterize SQL (entity extraction + template generation)
  3. Insert into semantic cache (Lakebase)

Memory extraction (all traces):
  1. Read recent data-query traces from MLflow
  2. Extract typed memories via LLM:
     - thumbs-up   -> preferences, definitions
     - thumbs-down -> corrections, avoidances
     - all         -> definitions (business terms)
  3. Check embedding-based blocklist before inserting
  4. Upsert into memory store (dedup + recurrence boosting)

When parameterize_on_ingest is enabled (default), the cache pipeline uses a
fast LLM to extract entities and parameterize SQL.
"""

import asyncio
import json
import logging

from backend.config import config
from backend.models import MemoryType, RecordType
from backend.services.cache_store import cache_store
from backend.services.memory_store import memory_store
from backend.services.trace_store import trace_store

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM prompts for entity extraction and SQL parameterization (cache)
# ---------------------------------------------------------------------------

EXTRACT_ENTITIES_PROMPT = """You are an entity extraction system. Given a user question and the SQL that answered it, extract key entity values that appear as literal values in the SQL.

Return a JSON object where keys are descriptive parameter names and values are the literal values found in both the question and the SQL.

Rules:
- Only extract entities whose values appear as literals in the SQL (strings, numbers, dates)
- Use short, descriptive snake_case parameter names (e.g. "phase", "disease", "company_name", "year", "count_threshold")
- If there are no extractable entities (the query has no variable parts), return an empty object: {{}}
- Return ONLY valid JSON, no other text

User question: {question}
SQL: {sql}

JSON:"""

PARAMETERIZE_SQL_PROMPT = """You are a SQL parameterization system. Given a SQL query and a JSON object of entity key-value pairs, replace the literal values in the SQL with named parameter placeholders using :param_name syntax.

Rules:
- Replace ONLY the exact literal values specified in the entities JSON
- Use the exact parameter names from the entities JSON with a : prefix (e.g. :phase, :year)
- Do NOT change any other part of the SQL (table names, column names, functions, operators, etc.)
- Keep the SQL structure and formatting identical otherwise
- Return ONLY the modified SQL, no explanation or markdown

SQL: {sql}

Entities: {entities}

Parameterized SQL:"""


# ---------------------------------------------------------------------------
# LLM prompts for memory extraction
# ---------------------------------------------------------------------------

# Few-shot examples are deliberately domain-neutral: this asset ships to field
# engineers and customers who point it at their own Genie spaces, and examples
# from one industry bias extraction toward that industry's vocabulary.
EXTRACT_MEMORIES_PROMPT = """Analyze this user message for EXPLICIT instructions, self-descriptions, corrections, or definitions that should be remembered for future queries.

ONLY extract a memory if the user is EXPLICITLY telling the system something. A regular data question is NOT a memory — it's just a query.

EXTRACT a memory when the user says things like:
- "I'm a demand forecasting analyst" → identity (who the user is)
- "My name is Dr. Chen" → identity (personal info)
- "I work in the finance department" → identity (role/domain)
- "I mainly work with subscription data" → identity (area of focus)
- "I'm a supply chain analyst" → identity (job role)
- "I only care about EMEA data" → preference (explicit filter instruction)
- "Always break it down by quarter" → preference (explicit display instruction)
- "When I say recent, I mean last 6 months" → definition (explicit term definition)
- "By 'active account' I mean status = subscribed" → definition (explicit term mapping)
- "No, that's wrong, I meant net revenue not gross" → correction (explicit correction)
- "Don't include internal test accounts in the results" → avoidance (explicit exclusion)

DO NOT extract a memory when the user asks a normal question like:
- "Show me EMEA subscriptions" → just a query, NOT a preference for EMEA
- "What is the most common plan tier?" → just a question, NOT a preference
- "How many accounts started in 2024?" → just a question about a specific date

Memory types:
- "identity": Facts about WHO the user is — their name, role, department, domain expertise, or area of focus
- "preference": Explicit instruction about how the user ALWAYS wants data filtered, grouped, or displayed
- "definition": Explicit definition of what a business term means to this user
- "correction": Explicit correction of a misunderstanding by the system
- "avoidance": Explicit instruction to ALWAYS exclude something

User's message: {question}
Context (SQL if any): {sql}

Rules:
- Return 0-2 memories maximum
- ONLY extract if the user is GIVING AN INSTRUCTION or DESCRIBING THEMSELVES, not just asking a question
- A topic mentioned in a question is NOT a preference — "show me X" ≠ "I always want X"
- When in doubt, return an empty array []
- Return ONLY valid JSON

JSON:"""


# ---------------------------------------------------------------------------
# LLM helper
# ---------------------------------------------------------------------------

async def _call_fast_llm(prompt: str, max_tokens: int = 512) -> str:
    """Call the fast LLM endpoint using raw HTTP."""
    def _call():
        import urllib.request
        from databricks.sdk import WorkspaceClient

        w = WorkspaceClient()
        host = w.config.host.rstrip("/")
        headers = w.config.authenticate()

        url = f"{host}/serving-endpoints/{config.llm.assistant_endpoint}/invocations"
        payload = json.dumps({
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.0,
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers={
            **headers,
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()

    return await asyncio.to_thread(_call)


def _strip_code_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()


# ---------------------------------------------------------------------------
# Cache: entity extraction + parameterization
# ---------------------------------------------------------------------------

async def _extract_entities(question: str, sql: str) -> dict:
    try:
        prompt = EXTRACT_ENTITIES_PROMPT.format(question=question, sql=sql)
        raw = await _call_fast_llm(prompt, max_tokens=256)
        entities = json.loads(_strip_code_fences(raw))
        if isinstance(entities, dict):
            return entities
        logger.warning(f"Entity extraction returned non-dict: {type(entities)}")
        return {}
    except Exception as e:
        logger.warning(f"Entity extraction failed: {e}")
        return {}


async def _parameterize_sql(sql: str, entities: dict) -> str | None:
    if not entities:
        return None
    try:
        prompt = PARAMETERIZE_SQL_PROMPT.format(sql=sql, entities=json.dumps(entities))
        raw = await _call_fast_llm(prompt, max_tokens=1024)
        parameterized = _strip_code_fences(raw)
        if ":" in parameterized and any(f":{k}" in parameterized for k in entities):
            return parameterized
        logger.warning("Parameterized SQL has no placeholders, discarding")
        return None
    except Exception as e:
        logger.warning(f"SQL parameterization failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Memory: extraction from traces
# ---------------------------------------------------------------------------

_TYPE_MAP = {
    "preference": MemoryType.PREFERENCE,
    "correction": MemoryType.CORRECTION,
    "avoidance": MemoryType.AVOIDANCE,
    "definition": MemoryType.DEFINITION,
    "identity": MemoryType.IDENTITY,
}


async def _extract_memories_from_trace(question: str, sql: str | None, is_negative: bool = False) -> list[dict]:
    """Use LLM to extract typed memories from a user message.

    Only extracts explicit instructions, corrections, or definitions —
    not topic preferences inferred from regular queries.
    """
    prompt = EXTRACT_MEMORIES_PROMPT.format(
        question=question, sql=sql or "(no SQL)"
    )

    try:
        raw = await _call_fast_llm(prompt, max_tokens=512)
        parsed = json.loads(_strip_code_fences(raw))
        if isinstance(parsed, list):
            return [
                m for m in parsed
                if isinstance(m, dict) and "type" in m and "content" in m
                and m["type"] in _TYPE_MAP
            ]
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Memory extraction failed: {e}")

    return []


# ---------------------------------------------------------------------------
# Cache: single entry promotion
# ---------------------------------------------------------------------------


def _is_configured_space(space_id: str | None) -> bool:
    """True when space_id is one this deployment is configured to serve.

    Guards promotion against foreign traces in the shared archive table.
    """
    if not space_id:
        return False
    return any(s.space_id == space_id for s in config.genie.spaces)


async def _cache_single_entry(
    query: str,
    sql: str,
    space_id: str,
    trace_id: str,
    original_question: str,
) -> tuple[bool, bool]:
    """Cache a single query/SQL pair. Returns (added, parameterized).

    Only the SQL is stored -- never the assistant's answer text. Each cache hit
    re-executes the SQL, so results are produced fresh rather than replayed.
    """
    existing = await cache_store.search(query, space_id=space_id)
    if existing and existing.similarity_score >= 0.93:
        return False, False

    parameterized_sql = None
    parameters = None
    was_parameterized = False

    if config.cache.parameterize_on_ingest:
        entities = await _extract_entities(query, sql)
        if entities:
            parameterized_sql = await _parameterize_sql(sql, entities)
            if parameterized_sql:
                parameters = entities
                was_parameterized = True
                logger.info(
                    f"Parameterized cache entry: entities={entities}, "
                    f"template has {sum(1 for k in entities if f':{k}' in parameterized_sql)} placeholders"
                )

    await cache_store.add(
        query=query,
        sql=sql,
        space_id=space_id,
        record_type=RecordType.TRACE,
        parameterized_sql=parameterized_sql,
        parameters=parameters,
        metadata={"source_trace_id": trace_id, "original_question": original_question},
    )
    return True, was_parameterized


# ---------------------------------------------------------------------------
# Main unified pipeline
# ---------------------------------------------------------------------------

async def run_cache_pipeline(limit: int = 100) -> dict:
    """Promote thumbs-up traces to cache AND extract memories from all traces.

    Cache promotion: only thumbs-up cache-miss traces with SQL.
    Memory extraction: all data-query traces (positive -> preferences/definitions,
    negative -> corrections/avoidances).
    """
    # ── Phase 1: Cache Promotion (thumbs-up only) ──
    thumbs_up_traces = await trace_store.get_thumbs_up_uncached(limit=limit)
    cache_added = 0
    cache_skipped = 0
    cache_already_promoted = 0
    parameterized_count = 0

    for trace in thumbs_up_traces:
        # Claim atomically rather than check-then-act: a scheduled run and a
        # UI-triggered run overlapping would otherwise both see "not promoted"
        # and both write a cache entry for this trace.
        if not await cache_store.claim_promotion(trace.id):
            cache_already_promoted += 1
            continue

        if not trace.sql:
            cache_skipped += 1
            continue

        # Multi-space trace: decompose into per-space cache entries
        sub_count = len(trace.sub_results) if trace.sub_results else 0
        logger.info(
            f"Processing trace {trace.id}: sub_results={sub_count}, "
            f"question='{trace.question[:80]}'"
        )
        if trace.sub_results and len(trace.sub_results) > 1:
            logger.info(
                f"Multi-step trace {trace.id}: promoting {len(trace.sub_results)} sub-results"
            )
            for i, sub in enumerate(trace.sub_results):
                sub_sql = sub.get("sql")
                sub_space = sub.get("space_id")
                sub_question = sub.get("sub_question")

                if not sub_sql or not sub_space or not sub_question:
                    logger.info(
                        f"  Sub-result {i}: SKIPPED (missing fields: "
                        f"sql={bool(sub_sql)}, space_id={bool(sub_space)}, "
                        f"sub_question={bool(sub_question)})"
                    )
                    cache_skipped += 1
                    continue

                if sub.get("cache_hit"):
                    logger.info(f"  Sub-result {i}: SKIPPED (was a cache hit)")
                    continue

                logger.info(
                    f"  Sub-result {i}: caching '{sub_question[:80]}' "
                    f"(space={sub_space[:12]}..., sql={len(sub_sql)} chars)"
                )
                if not _is_configured_space(sub_space):
                    cache_skipped += 1
                    continue

                was_added, was_param = await _cache_single_entry(
                    query=sub_question, sql=sub_sql, space_id=sub_space,
                    trace_id=trace.id, original_question=trace.question,
                )
                if was_added:
                    cache_added += 1
                    if was_param:
                        parameterized_count += 1
                else:
                    cache_skipped += 1

            continue

        # Single-space trace: extract description from first sub_result if available
        #
        # Only promote a trace whose space is one this deployment is configured for.
        # The trace archive is a persistent Unity Catalog table that outlives any
        # single deployment, so it accumulates traces from every app that ever
        # pointed at it -- including ones configured with entirely different Genie
        # spaces. Falling back to spaces[0] mis-filed those foreign traces against
        # the first configured space, so a fresh deployment's cache came up
        # pre-populated with another deployment's questions, bound to a space whose
        # data has nothing to do with them.
        space_id = trace.genie_space_id
        if not space_id or not _is_configured_space(space_id):
            cache_skipped += 1
            continue
        query = trace.rewritten_question or trace.question

        was_added, was_param = await _cache_single_entry(
            query=query, sql=trace.sql, space_id=space_id,
            trace_id=trace.id, original_question=trace.question,
        )
        if was_added:
            cache_added += 1
            if was_param:
                parameterized_count += 1
        else:
            cache_skipped += 1

    # Run cache eviction
    eviction_stats = await cache_store.evict()

    # ── Phase 2: Memory Extraction (all traces) ──
    memory_added = 0
    memory_updated = 0
    memory_blocked = 0
    memory_traces_processed = 0

    # We use promoted_trace_ids to also track memory processing.
    # Add a separate tracking key so we can process traces for memory
    # even if they were already promoted for cache.
    all_traces = await trace_store.get_recent_traces(limit=limit)

    # Group by user_id for efficient memory operations
    user_traces: dict[str, list] = {}
    for trace in all_traces:
        if not trace.user_id or not trace.question:
            continue
        user_traces.setdefault(trace.user_id, []).append(trace)

    for user_id, traces in user_traces.items():
        for trace in traces:
            memory_key = f"mem:{trace.id}"
            if not await cache_store.claim_promotion(memory_key):
                continue

            try:
                memories = await _extract_memories_from_trace(
                    trace.question, trace.sql,
                )
                for mem in memories:
                    mem_type = _TYPE_MAP.get(mem["type"], MemoryType.PREFERENCE)
                    result = await memory_store.add_or_update(
                        user_id=user_id,
                        content=mem["content"],
                        memory_type=mem_type,
                    )
                    if result is None:
                        memory_blocked += 1
                    elif result.recurrence_count > 1:
                        memory_updated += 1
                    else:
                        memory_added += 1

                memory_traces_processed += 1
            except Exception as e:
                logger.warning(f"Memory extraction failed for trace {trace.id}: {e}")


        # Apply decay and evict stale memories for this user
        await memory_store.apply_decay(user_id)

    memory_evicted = await memory_store.evict()

    logger.info(
        f"Unified pipeline: "
        f"cache(added={cache_added}, param={parameterized_count}, skip={cache_skipped}, "
        f"already={cache_already_promoted}, evicted={eviction_stats}), "
        f"memory(added={memory_added}, updated={memory_updated}, blocked={memory_blocked}, "
        f"traces={memory_traces_processed}, evicted={memory_evicted})"
    )
    return {
        "cache": {
            "added": cache_added,
            "skipped": cache_skipped,
            "already_promoted": cache_already_promoted,
            "parameterized": parameterized_count,
            "total_traces": len(thumbs_up_traces),
            "eviction": eviction_stats,
        },
        "memory": {
            "added": memory_added,
            "updated": memory_updated,
            "blocked": memory_blocked,
            "traces_processed": memory_traces_processed,
            "evicted": memory_evicted,
        },
    }
