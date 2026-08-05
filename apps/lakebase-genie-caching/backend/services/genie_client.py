"""Genie Conversation API client using the official databricks-ai-bridge Genie class.

Wraps `databricks_ai_bridge.genie.Genie` with:
  - Execution step tracking (status + duration_ms) for the frontend SSE timeline
  - Structured data return (columns, data arrays) instead of markdown/DataFrame
  - Async wrapper for FastAPI integration
  - Rate-limit retry logic

MLflow tracing is handled by the upstream Genie class and produces:
  ask_question
    start_conversation
    poll_for_result
      poll_result
        genie_timeline
          submitted / filtering_context / asking_ai / pending_warehouse / executing_query
        poll_query_results
          parse_query_result
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional
from unittest.mock import patch

import pandas as pd
from databricks.sdk import WorkspaceClient
from databricks_ai_bridge.genie import (
    Genie,
    GenieResponse as BridgeGenieResponse,
)

from backend.config import config

if TYPE_CHECKING:
    from backend.services.auth_context import AuthContext

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 1.0
MAX_DELAY = 30.0

_STATUS_LABELS = {
    "SUBMITTED": "Submitted to Genie...",
    "FILTERING_CONTEXT": "Retrieving metadata...",
    "FETCHING_METADATA": "Retrieving metadata...",
    "ASKING_AI": "AI is generating SQL...",
    "PENDING_WAREHOUSE": "Waiting for warehouse...",
    "EXECUTING_QUERY": "Executing query on warehouse...",
    "COMPLETED": "Complete",
    "FAILED": "Failed",
    "CANCELLED": "Cancelled",
    "QUERY_RESULT_EXPIRED": "Query result expired",
}


@dataclass
class GenieResponse:
    """Our adapter response that wraps the bridge response with extra metadata."""
    status: str
    sql: Optional[str] = None
    columns: Optional[list[str]] = None
    data: Optional[list[list]] = None
    row_count: Optional[int] = None
    description: Optional[str] = None
    error: Optional[str] = None
    latency_ms: float = 0
    execution_steps: list[dict] = field(default_factory=list)
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    follow_up_questions: list[str] = field(default_factory=list)


class TrackedGenie(Genie):
    """Subclass of the official Genie that captures execution step timings.

    The upstream Genie.poll_for_result() tracks status transitions for MLflow
    spans but doesn't expose them as data. We intercept the internal API calls
    to capture transition timestamps for our frontend timeline.
    """

    def __init__(self, space_id: str, client: Optional[WorkspaceClient] = None):
        super().__init__(
            space_id=space_id,
            client=client,
            return_pandas=True,
        )
        self.execution_steps: list[dict] = []
        self.follow_up_questions: list[str] = []
        self.message_id: Optional[str] = None
        self.text_attachment_content: Optional[str] = None
        self._step_start_time: float = 0
        self._overall_start: float = 0
        self._last_status: Optional[str] = None

    def _record_transition(self, new_status: str):
        """Record a status transition with duration of the previous step."""
        now = time.time()
        duration_ms = round((now - self._step_start_time) * 1000) if self._step_start_time else 0
        self.execution_steps.append({
            "status": new_status,
            "label": _STATUS_LABELS.get(new_status, new_status),
            "elapsed_s": round(now - self._overall_start, 2),
            "duration_ms": duration_ms,
        })
        self._step_start_time = now
        self._last_status = new_status

    def ask_question(self, question, conversation_id=None):
        """Override to capture execution step timings and follow-up questions."""
        self.execution_steps = []
        self.follow_up_questions = []
        self.message_id = None
        self.text_attachment_content = None
        self._overall_start = time.time()
        self._step_start_time = time.time()
        self._last_status = None

        original_do = self.genie._api.do

        def intercepting_do(method, path, *args, **kwargs):
            resp = original_do(method, path, *args, **kwargs)

            if method == "GET" and "/messages/" in path and "query-result" not in path:
                status = resp.get("status", "UNKNOWN")
                if status != self._last_status:
                    self._record_transition(status)

                # Capture message_id for feedback API
                if resp.get("message_id"):
                    self.message_id = resp["message_id"]

                # Extract follow-up questions and text attachments from completed response
                if status == "COMPLETED":
                    for att in resp.get("attachments", []):
                        sq = att.get("suggested_questions")
                        if sq and isinstance(sq, dict):
                            self.follow_up_questions = sq.get("questions", [])
                        text = att.get("text")
                        if text and isinstance(text, dict) and text.get("content"):
                            self.text_attachment_content = text["content"]

            return resp

        with patch.object(self.genie._api, "do", side_effect=intercepting_do):
            return super().ask_question(question, conversation_id)


def _bridge_to_our_response(
    bridge_resp: BridgeGenieResponse,
    execution_steps: list[dict],
    latency_ms: float,
    follow_up_questions: list[str] | None = None,
    message_id: str | None = None,
    text_attachment_content: str | None = None,
) -> GenieResponse:
    """Convert a databricks-ai-bridge GenieResponse to our GenieResponse format."""

    result = bridge_resp.result
    sql = bridge_resp.query or None
    description = bridge_resp.description or None
    # Prefer explicitly captured text attachment; fall back to bridge attribute
    text_content = (
        text_attachment_content
        or getattr(bridge_resp, "text_attachment_content", None)
        or None
    )
    columns = None
    data = None
    row_count = None
    status = "COMPLETED"
    error = None

    if isinstance(result, pd.DataFrame):
        if not result.empty:
            columns = list(result.columns)
            # Convert DataFrame to JSON-safe Python primitives
            # (pandas Timestamps, NaT, numpy types → str/None/native)
            data = json.loads(result.to_json(orient="values", date_format="iso"))
            row_count = len(data)
        else:
            columns = list(result.columns) if len(result.columns) > 0 else None
            data = []
            row_count = 0
    elif isinstance(result, str):
        if result.startswith("Genie query failed") or result.startswith("Genie query timed out"):
            status = "FAILED"
            error = result
        elif result == "EMPTY":
            columns = []
            data = []
            row_count = 0
        elif not sql:
            if not description:
                description = result if result else text_content

    # When Genie returns 0 rows, it often sends a text attachment with an
    # explanation (e.g. "No data found for ...").  Use that as the description
    # so downstream code has Genie's own narrative instead of a generic message.
    if row_count == 0 and text_content and not description:
        description = text_content

    if not sql and not description and text_content:
        description = text_content

    return GenieResponse(
        status=status,
        sql=sql,
        columns=columns,
        data=data,
        row_count=row_count,
        description=description,
        error=error,
        latency_ms=latency_ms,
        execution_steps=execution_steps,
        conversation_id=bridge_resp.conversation_id,
        message_id=message_id,
        follow_up_questions=follow_up_questions or [],
    )


def _fetch_follow_up_questions(
    api,
    space_id: str,
    conversation_id: str,
    message_id: str,
    retries: int = 3,
    delay: float = 0.5,
) -> list[str]:
    """Re-fetch a completed message to pick up late-arriving suggested_questions.

    The Genie API generates follow-up suggestions asynchronously.  For SQL
    queries the suggestions often aren't ready when the bridge first sees
    COMPLETED, so we poll the message endpoint a few more times.
    """
    for _ in range(retries):
        time.sleep(delay)
        try:
            resp = api.do(
                "GET",
                f"/api/2.0/genie/spaces/{space_id}/conversations/{conversation_id}/messages/{message_id}",
            )
            for att in resp.get("attachments", []):
                sq = att.get("suggested_questions")
                if sq and isinstance(sq, dict):
                    questions = sq.get("questions", [])
                    if questions:
                        logger.debug(f"Fetched {len(questions)} follow-up questions on retry")
                        return questions
        except Exception as e:
            logger.debug(f"Follow-up question fetch failed: {e}")
    return []


async def ask_genie(
    question: str,
    space_id: str | None = None,
    conversation_id: str | None = None,
    auth: "AuthContext | None" = None,
) -> GenieResponse:
    """Ask a question to the Genie Space.

    Uses the official databricks-ai-bridge Genie class for:
      - Proper MLflow tracing with nested spans
      - Robust result parsing with type handling
      - Attachment normalization

    Adds on top:
      - execution_steps with per-step duration_ms for frontend timeline
      - Structured columns/data return format
      - Rate-limit retry
      - Async wrapper
      - Conversation continuity via conversation_id

    Args:
        question: The user's question.
        space_id: Genie space ID (defaults to config).
        conversation_id: If provided, continues an existing Genie conversation
            instead of starting a new one.
        auth: Caller identity. When it carries a user token, Genie runs
            on-behalf-of the caller so Unity Catalog grants are enforced per
            user. Omitted / SP context falls back to the app service principal,
            which is only appropriate for background work -- see
            :mod:`backend.services.auth_context`.
    """
    sid = space_id or (config.genie.spaces[0].space_id if config.genie.spaces else None)
    if not sid:
        raise ValueError("No space_id provided and no default spaces configured")

    # Build the caller-scoped client once, off the event loop's critical path.
    client = auth.workspace_client() if auth is not None else None

    def _call():
        start = time.time()

        for attempt in range(MAX_RETRIES):
            try:
                genie = TrackedGenie(space_id=sid, client=client)
                bridge_resp = genie.ask_question(question, conversation_id=conversation_id)
                latency_ms = (time.time() - start) * 1000

                # For SQL queries, suggested_questions may arrive slightly after
                # the initial COMPLETED status.  Re-fetch the message once to
                # pick up any late-arriving follow-up suggestions.
                follow_ups = genie.follow_up_questions
                if not follow_ups and genie.message_id and bridge_resp.conversation_id:
                    follow_ups = _fetch_follow_up_questions(
                        genie.genie._api,
                        sid,
                        bridge_resp.conversation_id,
                        genie.message_id,
                    )

                return _bridge_to_our_response(
                    bridge_resp,
                    genie.execution_steps,
                    latency_ms,
                    follow_ups,
                    genie.message_id,
                    text_attachment_content=genie.text_attachment_content,
                )

            except Exception as e:
                error_str = str(e)
                if attempt < MAX_RETRIES - 1 and ("429" in error_str or "RATE_LIMIT" in error_str):
                    delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                    logger.warning(f"Genie rate limited (attempt {attempt + 1}), retrying in {delay:.1f}s")
                    time.sleep(delay)
                    continue
                else:
                    latency_ms = (time.time() - start) * 1000
                    logger.error(f"Genie API error: {e}")
                    return GenieResponse(
                        status="FAILED",
                        error=str(e),
                        latency_ms=latency_ms,
                    )

        latency_ms = (time.time() - start) * 1000
        return GenieResponse(
            status="FAILED",
            error="Max retries exceeded",
            latency_ms=latency_ms,
        )

    return await asyncio.to_thread(_call)


def _sanitize_sql(sql: str) -> str:
    """Strip accidental JSON-escaping artefacts from cached SQL."""
    s = sql.strip()
    if s.startswith('"') and s.endswith('"'):
        try:
            import json as _json
            s = _json.loads(s)
        except Exception:
            s = s[1:-1]
    s = s.replace("\\n", "\n").replace("\\t", "\t")
    return s.strip()


async def execute_cached_sql(
    sql: str,
    auth: "AuthContext | None" = None,
) -> tuple[list[str], list[list], int]:
    """Execute a cached SQL query on the warehouse and return columns, data, row_count.

    The cache stores **SQL, not result sets**: every hit re-executes the query, so
    rows are never replayed from storage. Combined with running as the caller
    whenever a token is available, that means the warehouse and Unity Catalog
    decide what comes back on each request.

    Identity follows the same rule as ``ask_genie``: use the caller's token when
    one is present, otherwise the app's service principal. That keeps the app
    working when user authorization is not enabled -- an admin-gated Public
    Preview -- which matters because a cache that silently never serves looks like
    a broken feature rather than a missing setting.

    Set ``REQUIRE_USER_AUTH=true`` to refuse the service-principal fallback. Do
    that before pointing this at data where users have differing access: without a
    caller token, a cache hit returns rows fetched with the service principal's
    grants rather than the caller's.

    Raises:
        PermissionError: only when ``REQUIRE_USER_AUTH`` is set and no caller
            token is available. Callers treat this as "cache unusable, ask Genie".
    """
    if config.require_user_auth and (auth is None or not auth.can_query_as_user):
        raise PermissionError(
            "REQUIRE_USER_AUTH is set but no caller token is available, so cached "
            "SQL would run with the app service principal's Unity Catalog access "
            "instead of the caller's. Enable user authorization on the app with "
            "the 'sql' and 'genie' scopes (see README, Security model)."
        )

    def _call():
        w = auth.workspace_client() if auth is not None else WorkspaceClient()
        from databricks.sdk.service.sql import StatementState

        clean_sql = _sanitize_sql(sql)
        response = w.statement_execution.execute_statement(
            warehouse_id=config.genie.warehouse_id,
            statement=clean_sql,
            wait_timeout=f"{config.timeouts.cached_sql}s",
        )

        if response.status and response.status.state == StatementState.SUCCEEDED:
            columns = []
            data = []
            row_count = 0

            if response.manifest and response.manifest.schema and response.manifest.schema.columns:
                columns = [c.name for c in response.manifest.schema.columns]
            if response.result and response.result.data_array:
                data = response.result.data_array
                row_count = len(data)

            return columns, data, row_count
        else:
            error = ""
            if response.status and response.status.error:
                error = response.status.error.message or "Unknown error"
            raise RuntimeError(f"SQL execution failed: {error}")

    return await asyncio.to_thread(_call)
