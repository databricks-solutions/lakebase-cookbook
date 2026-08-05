"""Offline pipeline: evict stale entries from cache and user memory."""

import logging

from backend.services.cache_store import cache_store
from backend.services.memory_store import memory_store
from backend.services.session_store import session_store

logger = logging.getLogger(__name__)


async def run_eviction_pipeline(
    cache_max_age_days: int | None = None,
    memory_max_age_days: int | None = None,
    session_max_age_days: int | None = None,
) -> dict:
    """Run eviction across all stores.

    Cache eviction applies three strategies:
      1. Age: entries older than cache_max_age_days (default 90)
      2. Stale: entries not hit in stale_days (default 7)
      3. Overflow: keep only max_entries (default 1000), removing least valuable

    Sessions and their messages are also expired: nothing else removes them, so
    without this the tables grow for the lifetime of the deployment.
    """
    cache_stats = await cache_store.evict(cache_max_age_days)
    memory_evicted = await memory_store.evict(memory_max_age_days)
    try:
        sessions_evicted = await session_store.evict(session_max_age_days)
    except Exception as e:
        # Session eviction is housekeeping; a failure here must not mask the
        # cache and memory results the caller asked for.
        logger.warning("Session eviction failed: %s", e, exc_info=True)
        sessions_evicted = 0

    total_cache = cache_stats["age"] + cache_stats["stale"] + cache_stats["overflow"]
    logger.info(
        f"Eviction pipeline: cache={total_cache} "
        f"(age={cache_stats['age']}, stale={cache_stats['stale']}, overflow={cache_stats['overflow']}), "
        f"memory={memory_evicted}, sessions={sessions_evicted}"
    )
    return {
        "cache_evicted": cache_stats,
        "memory_evicted": memory_evicted,
        "sessions_evicted": sessions_evicted,
    }
