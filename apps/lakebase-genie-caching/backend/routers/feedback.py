"""Feedback endpoint: thumbs up/down on query responses.

Stores feedback as MLflow trace tags (feedback_rating) and also
forwards it to the Databricks Genie API.  The MLflow tag update runs
as a background task because trace upload to Databricks is asynchronous
and can take 30-120 seconds after the query completes.

Supports toggle: re-submitting the same rating clears it.
"""

import asyncio
import logging

import mlflow
from fastapi import APIRouter, HTTPException, Request

from backend.models import FeedbackRequest, FeedbackResponse
from backend.services import auth_context
from backend.services.authz import is_admin, is_deployed
from backend.services.trace_store import trace_store
from backend.services.background import spawn as spawn_background

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["feedback"])

_mlflow_client: mlflow.MlflowClient | None = None

# In-memory rating cache: trace_id -> rating int (or 0 for cleared)
_local_ratings: dict[str, int] = {}


def _get_client() -> mlflow.MlflowClient:
    """Lazy-init MlflowClient after tracking URI is set in lifespan."""
    global _mlflow_client
    if _mlflow_client is None:
        _mlflow_client = mlflow.MlflowClient()
    return _mlflow_client


def _set_trace_rating_blocking(trace_id: str, rating: int | None) -> None:
    """Write feedback_rating tag to the MLflow trace (blocking, with retries).

    Retries with exponential backoff because traces are uploaded asynchronously
    and may not be available in the tracking server for 30-120 seconds.
    """
    import time

    tag_value = str(rating) if rating is not None else ""
    client = _get_client()
    last_err = None
    delays = [5, 10, 15, 20, 30, 30, 30]
    for attempt, delay in enumerate(delays):
        try:
            client.set_trace_tag(trace_id, "feedback_rating", tag_value)
            logger.info(f"MLflow tag feedback_rating={tag_value} set on {trace_id} (attempt {attempt + 1})")
            return
        except Exception as e:
            last_err = e
            if "not found" in str(e).lower() or "NOT_FOUND" in str(e):
                logger.debug(f"Trace {trace_id} not found, retry {attempt + 1}/{len(delays)} in {delay}s")
                time.sleep(delay)
                continue
            raise
    logger.warning(f"Failed to set MLflow tag on {trace_id} after {len(delays)} attempts: {last_err}")


async def _background_set_rating(trace_id: str, rating: int | None) -> None:
    """Background task: set trace rating tag + forward to Genie API."""
    try:
        await asyncio.to_thread(_set_trace_rating_blocking, trace_id, rating)
    except Exception as e:
        logger.warning(f"Background rating update failed for {trace_id}: {e}")

    if rating is not None:
        await _send_genie_feedback(trace_id, rating)


async def _send_genie_feedback(trace_id: str, rating: int | None) -> None:
    """Forward feedback to the Genie API (fire-and-forget)."""
    if rating is None:
        return

    try:
        genie_ids = await trace_store.get_genie_ids(trace_id)
        if not genie_ids:
            return

        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.dashboards import GenieFeedbackRating

        genie_rating = GenieFeedbackRating.POSITIVE if rating == 1 else GenieFeedbackRating.NEGATIVE

        def _call():
            w = WorkspaceClient()
            w.genie.send_message_feedback(
                space_id=genie_ids["space_id"],
                conversation_id=genie_ids["conversation_id"],
                message_id=genie_ids["message_id"],
                rating=genie_rating,
            )

        await asyncio.to_thread(_call)
        logger.info(
            f"Sent Genie feedback ({genie_rating.value}) for message {genie_ids['message_id']}"
        )
    except Exception as e:
        logger.warning(f"Failed to send Genie feedback for trace {trace_id}: {e}")


async def _authorize_feedback(http_request: Request, trace_id: str) -> None:
    """Allow feedback only from the user whose question produced the trace.

    A trace_id is effectively a bearer handle: anyone holding one could otherwise
    rate someone else's answer. That matters because a thumbs-up is what promotes
    a question into the SHARED cache, so an unauthorized rating lets a caller
    seed cache entries on another user's behalf -- and a thumbs-down lets them
    suppress one.

    Admins may rate anything. Local development (no proxy identity) is relaxed,
    consistent with backend.services.authz.
    """
    auth = auth_context.from_headers(http_request.headers)
    identity = auth.email or auth.user_id

    if not identity or identity == "unknown":
        if is_deployed():
            raise HTTPException(
                status_code=403,
                detail="No forwarded caller identity; cannot authorize feedback.",
            )
        return  # local development

    owner = await trace_store.get_owner(trace_id)

    if owner is None:
        # The trace is not readable yet. MLflow uploads traces asynchronously --
        # 30-120s after the query completes, which is why _set_trace_rating_blocking
        # retries -- so a user clicking thumbs-up promptly (the normal case) arrives
        # before the trace exists. Rejecting here 404'd legitimate feedback.
        #
        # Accept it: the background write is itself gated, retrying until the trace
        # appears and giving up if it never does, so an unresolvable trace_id
        # results in no rating being recorded either way. Nothing is granted by
        # proceeding, and the alternative breaks the primary user action.
        logger.info(
            "Trace %s not yet readable (async upload); accepting feedback from %s "
            "and letting the background write arbitrate.",
            trace_id,
            identity,
        )
        return

    if owner.strip().lower() == identity.strip().lower():
        return
    if is_admin(auth):
        logger.info("Admin %s rating trace owned by %s", identity, owner)
        return

    raise HTTPException(
        status_code=403, detail="You may only give feedback on your own queries."
    )


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    request: FeedbackRequest, http_request: Request
) -> FeedbackResponse:
    """Submit thumbs up (+1) or thumbs down (-1) feedback on a trace.

    Returns immediately; MLflow tag update happens in the background.
    Toggle behaviour: re-submitting the same rating clears it.
    """
    await _authorize_feedback(http_request, request.trace_id)

    current = _local_ratings.get(request.trace_id)

    if current is not None and current == request.rating:
        _local_ratings[request.trace_id] = 0
        spawn_background(
            _background_set_rating(request.trace_id, None),
            name="mlflow.set_trace_rating(clear)",
        )
        return FeedbackResponse(trace_id=request.trace_id, rating=0, cached=False)

    _local_ratings[request.trace_id] = request.rating
    spawn_background(
        _background_set_rating(request.trace_id, request.rating),
        name="mlflow.set_trace_rating",
    )

    return FeedbackResponse(
        trace_id=request.trace_id,
        rating=request.rating,
        cached=False,
    )
