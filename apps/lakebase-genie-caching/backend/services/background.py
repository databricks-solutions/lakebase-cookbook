"""Fire-and-forget background tasks that report their failures.

``asyncio.create_task`` without a done-callback swallows exceptions: if the task
raises, nothing surfaces unless the object is later awaited, and Python's
"Task exception was never retrieved" warning only fires when it is garbage
collected. In this app that meant a failed session-message write, feedback
submission, or session-title generation looked exactly like a success.

These operations are deliberately not awaited -- they must not add latency to the
user's answer -- so the fix is not to await them but to make their failures
visible. ``spawn`` attaches a done-callback that logs, and keeps a strong
reference so the task cannot be collected mid-flight.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Coroutine, Set

logger = logging.getLogger(__name__)

# Strong references to in-flight tasks. Without this the event loop only holds a
# weak reference, so a task can be garbage collected before it finishes.
_pending: Set[asyncio.Task] = set()


def spawn(coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task:
    """Run ``coro`` in the background, logging any failure.

    Args:
        coro: The coroutine to run. Not awaited.
        name: Human-readable label used in the log message when it fails.

    Returns:
        The created task, for callers that want to cancel it later.
    """
    task = asyncio.create_task(coro, name=name)
    _pending.add(task)

    def _report(finished: asyncio.Task) -> None:
        _pending.discard(finished)
        if finished.cancelled():
            logger.debug("Background task cancelled: %s", name)
            return
        error = finished.exception()
        if error is not None:
            logger.error("Background task failed: %s: %s", name, error, exc_info=error)

    task.add_done_callback(_report)
    return task


def pending_count() -> int:
    """Number of background tasks currently in flight (used by tests)."""
    return len(_pending)
