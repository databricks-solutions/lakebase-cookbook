"""Genie Spaces read-only endpoints.

Spaces are configured at deploy time via GENIE_SPACE_IDS env var in
databricks.yml. Titles and descriptions are auto-resolved from the
Genie API when the frontend loads.
"""

import logging
import os
import asyncio
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from backend.config import config
from agent_server.sample_questions import refresh_genie_spaces_and_samples

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/genie", tags=["genie-spaces"])


def _get_workspace_host() -> str:
    """Resolve the Databricks workspace host URL."""
    host = os.environ.get("DATABRICKS_HOST", "")
    if not host:
        try:
            from databricks.sdk import WorkspaceClient
            w = WorkspaceClient()
            host = w.config.host or ""
        except Exception:
            pass
    host = host.rstrip("/")
    if host and not host.startswith("http"):
        host = f"https://{host}"
    return host


class GenieSpaceInfo(BaseModel):
    space_id: str
    title: str
    description: Optional[str] = None
    genie_room_url: Optional[str] = None


@router.get("/spaces/active", response_model=list[GenieSpaceInfo])
async def get_active(refresh: bool = True):
    """Return configured Genie spaces with fresh metadata from Genie."""
    if refresh:
        try:
            await asyncio.to_thread(refresh_genie_spaces_and_samples, config.genie.spaces, max_per_space=3)
        except Exception as e:
            logger.warning("Could not refresh Genie space metadata: %s", e)

    host = _get_workspace_host()
    return [
        GenieSpaceInfo(
            space_id=s.space_id,
            title=s.title,
            description=s.description or None,
            genie_room_url=f"{host}/genie/rooms/{s.space_id}" if host else None,
        )
        for s in config.genie.spaces
    ]


@router.get("/spaces", response_model=list[GenieSpaceInfo])
async def list_all():
    """Same as active — all configured spaces are active."""
    return await get_active()
