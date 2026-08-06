"""Genie Space metadata cache.

Titles and descriptions are resolved from the Genie API once at startup (see
agent_server.sample_questions) and cached here, because the supervisor prompt
renders the full space list on every decomposition and must not make an API call
per request to do it.

Re-exported from backend.services.graph for backwards compatibility.
"""

from backend.config import config


# Genie Space metadata (static, from config — set at deploy time)
# ---------------------------------------------------------------------------

_space_meta_cache: dict[str, dict] = {
    s.space_id: {"title": s.title, "description": s.description, "space_id": s.space_id}
    for s in config.genie.spaces
}


def update_space_metas(spaces: list) -> None:
    """Update the space meta cache (called after titles are resolved at startup)."""
    global _space_meta_cache
    _space_meta_cache = {
        s.space_id: {"title": s.title, "description": s.description, "space_id": s.space_id}
        for s in spaces
    }


def _get_space_meta(space_id: str | None = None) -> dict:
    """Look up Genie space title and description."""
    if space_id is None:
        if _space_meta_cache:
            return next(iter(_space_meta_cache.values()))
        return {"title": "No Space Selected", "description": ""}
    return _space_meta_cache.get(space_id, {"title": "Unknown Space", "description": "", "space_id": space_id or ""})


def _get_all_active_space_metas() -> list[dict]:
    """Return metadata dicts for every active Genie space."""
    return list(_space_meta_cache.values())
