"""Managed LangGraph checkpointer backed by Lakebase.

Reuses the same Lakebase database that powers the cache, session, memory,
and trace stores. The checkpointer persists LangGraph state so conversations
can be resumed across requests.

Uses the Databricks-managed async checkpointer context rather than keeping an
app-global psycopg connection alive for the process lifetime.
"""

from contextlib import asynccontextmanager
import logging

from databricks_langchain import AsyncCheckpointSaver

from backend.config import config

logger = logging.getLogger(__name__)


def _checkpointer_kwargs() -> dict:
    """Return Databricks-managed Lakebase checkpointer configuration."""
    lb = config.lakebase
    if lb.is_autoscaling:
        if lb.endpoint_name:
            return {
                "instance_name": None,
                "autoscaling_endpoint": lb.endpoint_name,
                "project": None,
                "branch": None,
            }
        return {
            "instance_name": None,
            "autoscaling_endpoint": None,
            "project": lb.project_name,
            "branch": "production",
        }
    return {
        "instance_name": lb.instance_name,
        "autoscaling_endpoint": None,
        "project": None,
        "branch": None,
    }


@asynccontextmanager
async def lakebase_checkpointer_context():
    """Yield a request-scoped Databricks-managed Lakebase checkpointer."""
    async with AsyncCheckpointSaver(**_checkpointer_kwargs()) as checkpointer:
        yield checkpointer


async def setup_checkpointer() -> None:
    """Run managed checkpointer setup/migrations without retaining a live pool."""
    async with lakebase_checkpointer_context() as checkpointer:
        await checkpointer.setup()
    logger.info("LangGraph managed Lakebase checkpointer setup complete")


async def close_checkpointer() -> None:
    """Compatibility hook: request-scoped checkpointers close themselves."""
    logger.info("LangGraph managed checkpointer has no app-global connection to close")
