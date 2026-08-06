"""Memory pipeline: extract + maintain memories for a single user.

1. Fetch recent rated traces for this user from MLflow
2. Extract memories (preferences, corrections, avoidances) via LLM
3. Store/update in the memory store
4. Apply decay + eviction for this user
"""

import logging

from backend.models import MemoryType
from backend.pipelines.cache_pipeline import _extract_memories_from_trace, _TYPE_MAP
from backend.services.cache_store import cache_store
from backend.services.memory_store import memory_store
from backend.services.trace_store import trace_store

logger = logging.getLogger(__name__)


async def run_memory_pipeline(user_id: str, max_traces: int = 50) -> dict:
    """Extract memories from this user's recent traces, then run maintenance."""

    all_traces = await trace_store.get_recent_traces(limit=200)

    user_traces = [
        t for t in all_traces
        if t.user_id == user_id and t.question
    ][:max_traces]

    extracted = 0
    added = 0
    updated = 0
    blocked = 0
    skipped = 0

    for trace in user_traces:
        memory_key = f"mem:{trace.id}"
        if await cache_store.is_promoted(memory_key):
            skipped += 1
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
                    blocked += 1
                elif result.recurrence_count > 1:
                    updated += 1
                else:
                    added += 1

            extracted += 1
        except Exception as e:
            logger.warning(f"Memory extraction failed for trace {trace.id}: {e}")

        await cache_store.record_promotion(memory_key)

    decayed = await memory_store.apply_decay(user_id)
    evicted = await memory_store.evict()

    logger.info(
        f"Memory pipeline for {user_id}: "
        f"traces={len(user_traces)}, extracted={extracted}, "
        f"added={added}, updated={updated}, blocked={blocked}, "
        f"skipped={skipped}, decayed={decayed}, evicted={evicted}"
    )
    return {
        "traces_found": len(user_traces),
        "traces_extracted": extracted,
        "added": added,
        "updated": updated,
        "blocked": blocked,
        "skipped": skipped,
        "decayed": decayed,
        "evicted": evicted,
    }
