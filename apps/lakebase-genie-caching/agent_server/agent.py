"""Agent handlers registered with MLflow AgentServer.

The @invoke and @stream decorators register these functions to be served
at the /invocations endpoint by the AgentServer in start_server.py.
"""

import logging
import uuid
from typing import Generator

import mlflow
from mlflow.entities import SpanType
from mlflow.genai.agent_server import invoke, stream
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
)

from agent_server.utils import extract_question, extract_session_id, extract_user_id

logger = logging.getLogger(__name__)


class _Helper(ResponsesAgent):
    """Minimal concrete subclass solely for helper method access."""
    def predict(self, request):
        raise NotImplementedError

_helper = _Helper()


@invoke()
async def handle_invoke(request: ResponsesAgentRequest) -> ResponsesAgentResponse:
    """Non-streaming invocation: runs the full LangGraph pipeline and returns."""
    from backend.services.graph import run_pipeline

    question = extract_question(request)
    user_id = extract_user_id(request)
    session_id = extract_session_id(request)

    if not question:
        return ResponsesAgentResponse(
            output=[_helper.create_text_output_item(
                text="Please provide a question.",
                id=f"msg_{uuid.uuid4().hex[:8]}",
            )]
        )

    response, _events = await run_pipeline(question, session_id, user_id)

    text = _format_response_text(response)
    output_items = [
        _helper.create_text_output_item(
            text=text,
            id=f"msg_{uuid.uuid4().hex[:8]}",
        )
    ]

    custom_outputs = {
        "session_id": response.session_id,
        "trace_id": response.trace_id,
        "cache_status": response.cache_status.value,
        "latency_ms": response.latency_ms,
    }
    if response.sql:
        custom_outputs["sql"] = response.sql
    if response.similarity_score is not None:
        custom_outputs["similarity_score"] = response.similarity_score
    if response.mlflow_trace_url:
        custom_outputs["mlflow_trace_url"] = response.mlflow_trace_url

    return ResponsesAgentResponse(output=output_items, custom_outputs=custom_outputs)


@stream()
async def handle_stream(request: ResponsesAgentRequest) -> Generator[ResponsesAgentStreamEvent, None, None]:
    """Streaming invocation: yields delta events as the pipeline progresses."""
    from backend.services.graph import run_pipeline_stream

    question = extract_question(request)
    user_id = extract_user_id(request)
    session_id = extract_session_id(request)

    if not question:
        item_id = f"msg_{uuid.uuid4().hex[:8]}"
        yield ResponsesAgentStreamEvent(
            **_helper.create_text_delta(delta="Please provide a question.", item_id=item_id),
        )
        yield ResponsesAgentStreamEvent(
            type="response.output_item.done",
            item=_helper.create_text_output_item(text="Please provide a question.", id=item_id),
        )
        return

    item_id = f"msg_{uuid.uuid4().hex[:8]}"
    full_text_parts: list[str] = []

    async for event_type, event_data in run_pipeline_stream(question, session_id, user_id):
        if event_type == "status":
            chunk = f"[{event_data.get('step', '')}] {event_data.get('message', '')}\n"
            full_text_parts.append(chunk)
            yield ResponsesAgentStreamEvent(
                **_helper.create_text_delta(delta=chunk, item_id=item_id),
            )
        elif event_type == "complete":
            description = event_data.get("description", "")
            sql = event_data.get("sql", "")
            final_text = ""
            if description:
                final_text += f"\n{description}\n"
            if sql:
                final_text += f"\n```sql\n{sql}\n```\n"
            if final_text:
                full_text_parts.append(final_text)
                yield ResponsesAgentStreamEvent(
                    **_helper.create_text_delta(delta=final_text, item_id=item_id),
                )
        elif event_type == "error":
            error_text = f"\nError: {event_data.get('message', 'Unknown error')}\n"
            full_text_parts.append(error_text)
            yield ResponsesAgentStreamEvent(
                **_helper.create_text_delta(delta=error_text, item_id=item_id),
            )

    yield ResponsesAgentStreamEvent(
        type="response.output_item.done",
        item=_helper.create_text_output_item(
            text="".join(full_text_parts),
            id=item_id,
        ),
    )


def _format_response_text(response) -> str:
    """Format an AskResponse into a readable text string."""
    parts = []
    if response.description:
        parts.append(response.description)
    if response.sql:
        parts.append(f"\n```sql\n{response.sql}\n```")
    if response.data and response.columns:
        parts.append(f"\n{len(response.data)} rows returned.")
    if response.follow_up_questions:
        parts.append("\nFollow-up questions:")
        for q in response.follow_up_questions:
            parts.append(f"  - {q}")
    return "\n".join(parts) if parts else "No results."
