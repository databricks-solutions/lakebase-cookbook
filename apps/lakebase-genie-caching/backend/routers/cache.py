"""Cache management endpoints, including FAQ upload."""

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.config import config
from backend.models import CacheEntry, FAQUploadRequest
from backend.services.authz import require_admin
from backend.services.cache_store import cache_store
from backend.services.graph import get_mlflow_trace_base_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cache", tags=["cache"])


class CacheListResponse(BaseModel):
    entries: list[CacheEntry]
    total: int


class ThresholdUpdate(BaseModel):
    threshold: float


class EvictResponse(BaseModel):
    age: int = 0
    stale: int = 0
    overflow: int = 0
    total: int = 0


class FAQUploadResponse(BaseModel):
    entry: CacheEntry


class FAQBulkUploadResponse(BaseModel):
    added: int
    failed: int
    entries: list[CacheEntry]


@router.get("/entries", response_model=CacheListResponse)
async def list_cache_entries(limit: int = 50, offset: int = 0) -> CacheListResponse:
    entries = await cache_store.list_entries(limit=limit, offset=offset)
    total = await cache_store.count()
    return CacheListResponse(entries=entries, total=total)


@router.delete("/entries/{entry_id}")
async def delete_cache_entry(request: Request, entry_id: str) -> dict:
    # Entries are shared infrastructure and carry no per-caller ownership, so
    # deletion is admin-only rather than open to whoever knows the id.
    require_admin(request)
    await cache_store.delete(entry_id)
    return {"deleted": True, "id": entry_id}


@router.delete("/entries")
async def clear_all_cache_entries(request: Request) -> dict:
    """Delete ALL cache entries."""
    require_admin(request)
    count = await cache_store.clear_all()
    return {"cleared": True, "count": count}


@router.get("/threshold")
async def get_threshold() -> dict:
    return {"threshold": config.cache.similarity_threshold}


@router.put("/threshold")
async def update_threshold(request: Request, update: ThresholdUpdate) -> dict:
    """Set the Tier-1 similarity threshold for the whole app."""
    require_admin(request)
    if not 0.0 < update.threshold <= 1.0:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=422,
            detail="threshold must be in (0, 1]; a value of 0 would make the cache match anything.",
        )
    if update.threshold < config.cache.answer_morph_threshold:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=422,
            detail=(
                "threshold must be >= answer_morph_threshold "
                f"({config.cache.answer_morph_threshold}); a direct hit cannot be "
                "less similar than an adaptation candidate."
            ),
        )
    config.cache.similarity_threshold = update.threshold
    return {"threshold": config.cache.similarity_threshold}


class PinUpdate(BaseModel):
    pinned: bool


@router.put("/entries/{entry_id}/pin")
async def set_pin(request: Request, entry_id: str, update: PinUpdate) -> dict:
    """Pin or unpin a cache entry. Pinned entries are exempt from eviction."""
    require_admin(request)
    found = await cache_store.set_pinned(entry_id, update.pinned)
    if not found:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Cache entry not found")
    return {"id": entry_id, "pinned": update.pinned}


@router.get("/trace-base-url")
async def trace_base_url() -> dict:
    """Return the MLflow trace base URL for constructing deep-links."""
    return {"base_url": get_mlflow_trace_base_url()}


@router.post("/evict", response_model=EvictResponse)
async def evict_cache(request: Request, max_age_days: int | None = None) -> EvictResponse:
    """Evict stale cache entries workspace-wide. Admin-only."""
    require_admin(request)
    if max_age_days is not None and max_age_days < 1:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=422,
            detail="max_age_days must be >= 1; 0 would evict the entire cache.",
        )
    stats = await cache_store.evict(max_age_days)
    return EvictResponse(
        age=stats.get("age", 0),
        stale=stats.get("stale", 0),
        overflow=stats.get("overflow", 0),
        total=stats["age"] + stats["stale"] + stats["overflow"],
    )


# ---------------------------------------------------------------------------
# FAQ Upload endpoints
# ---------------------------------------------------------------------------


async def _parameterize_faq(question: str, sql: str) -> tuple[str | None, dict | None]:
    """Extract entities and build a :param template for an FAQ entry.

    Reuses the same prompts/logic as the batch cache pipeline so that FAQ
    entries get parameterized the same way trace-promoted entries do.
    """
    if not config.cache.parameterize_on_ingest:
        return None, None

    try:
        from backend.pipelines.cache_pipeline import _extract_entities, _parameterize_sql

        entities = await _extract_entities(question, sql)
        if not entities:
            return None, None
        parameterized_sql = await _parameterize_sql(sql, entities)
        if parameterized_sql:
            logger.info(
                f"FAQ parameterized: entities={list(entities.keys())}, "
                f"placeholders={sum(1 for k in entities if f':{k}' in parameterized_sql)}"
            )
            return parameterized_sql, entities
    except Exception as e:
        logger.warning(f"FAQ parameterization failed (non-fatal): {e}")

    return None, None


@router.post("/faq", response_model=FAQUploadResponse)
async def upload_faq(request: Request, req: FAQUploadRequest) -> FAQUploadResponse:
    """Upload a single curated FAQ entry (question→SQL) to the cache.

    Automatically parameterizes the SQL with :param placeholders when
    ``parameterize_on_ingest`` is enabled, enabling Databricks-style
    parameter substitution at query time.
    """
    # FAQ entries are published to every user, so curation is admin-only.
    require_admin(request)
    parameterized_sql, parameters = await _parameterize_faq(req.question, req.sql)
    entry = await cache_store.add_faq(
        question=req.question,
        sql=req.sql,
        space_id=req.genie_space_id,
        metadata=req.metadata,
        parameterized_sql=parameterized_sql,
        parameters=parameters,
    )
    return FAQUploadResponse(entry=entry)


@router.post("/faq/bulk", response_model=FAQBulkUploadResponse)
async def upload_faq_bulk(request: Request, items: list[FAQUploadRequest]) -> FAQBulkUploadResponse:
    """Bulk upload curated FAQ entries (question→SQL) to the cache.

    Each entry is automatically parameterized with :param placeholders.
    """
    require_admin(request)
    entries: list[CacheEntry] = []
    failed = 0
    for item in items:
        try:
            parameterized_sql, parameters = await _parameterize_faq(item.question, item.sql)
            entry = await cache_store.add_faq(
                question=item.question,
                sql=item.sql,
                space_id=item.genie_space_id,
                metadata=item.metadata,
                parameterized_sql=parameterized_sql,
                parameters=parameters,
            )
            entries.append(entry)
        except Exception:
            failed += 1
    return FAQBulkUploadResponse(added=len(entries), failed=failed, entries=entries)
