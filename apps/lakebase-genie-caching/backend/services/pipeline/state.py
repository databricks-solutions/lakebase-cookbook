"""Pipeline state shape and the SSE event helpers that operate on it.

PipelineState is the single dict threaded through every LangGraph node. It is
defined here, apart from the node implementations, because two things serialise
it -- the Lakebase checkpointer and MLflow trace capture -- so what may and may
not live in it is a contract worth reading on its own.

Re-exported from backend.services.graph for backwards compatibility.
"""

import time
from typing import Optional, TypedDict


MAX_CALLS_PER_SPACE = 2


class PipelineState(TypedDict, total=False):
    # Inputs
    question: str
    session_id: Optional[str]
    user_id: str
    start_time: float
    # NOTE: the caller's on-behalf-of token is deliberately NOT in this state.
    # PipelineState is serialised by the Lakebase checkpointer and captured by
    # @mlflow.trace, so a bearer credential here would be persisted. It travels
    # in a contextvar instead -- backend.services.auth_context.current().

    # Session
    resolved_session_id: str
    session_title: Optional[str]
    genie_conversation_ids: dict  # {space_id: conversation_id}

    # Rewrite
    rewritten: str

    # Supervisor decision
    intent: str  # "assistant" | "data_query"
    supervisor_plan: list[dict]  # [{"agent": "assistant"|space_id, "task": str}]

    # Supervisor loop state
    current_step: int              # index into supervisor_plan
    current_space_id: Optional[str]  # space_id for the current sub-question
    current_task: Optional[str]    # the current sub-question text
    completed_results: list[dict]  # accumulated results from completed sub-questions
    space_call_counts: dict        # {space_id: int} — per-space call counter

    # Cache (per-iteration, reset by supervisor between loop iterations)
    cache_result: Optional[dict]
    cache_hit: bool
    answer_morph: bool
    bypass_cache: bool  # A/B comparison: skip cache, always go to Genie

    # Conversation history (fetched once in node_session, reused everywhere)
    conversation_history: Optional[list]

    # Fast-path routing decision (set by node_fast_path)
    fast_path_result: Optional[str]
    echo_match: Optional[dict]  # stored by node_fast_path for node_echo_result

    # Memory (folded into rewrite; kept here for UI display)
    memory_context: Optional[list[str]]

    # Genie (multi-agent routing)
    selected_space_id: Optional[str]
    genie_response: Optional[dict]

    # Execution (cache hit path)
    exec_columns: Optional[list[str]]
    exec_data: Optional[list[list]]
    exec_row_count: Optional[int]

    # Output
    cache_status: str
    similarity_score: Optional[float]
    latency_ms: float
    genie_latency_ms: Optional[float]
    trace_id: str
    sql: Optional[str]
    description: Optional[str]
    genie_steps: Optional[list[dict]]
    follow_up_questions: Optional[list[str]]

    # Multi-space supervisor results
    sub_results: Optional[list[dict]]

    # SSE events log (for streaming)
    events: list[dict]

    # Error
    error: Optional[str]


def _elapsed(state: PipelineState) -> int:
    return round((time.time() - state["start_time"]) * 1000)


def _add_event(state: PipelineState, event: str, data: dict) -> PipelineState:
    """Append an SSE event to the events list."""
    events = list(state.get("events", []))
    events.append({"event": event, "data": {**data, "elapsed_ms": _elapsed(state)}})
    return {**state, "events": events}
