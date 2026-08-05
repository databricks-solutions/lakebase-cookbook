"""Conditional-edge functions for the LangGraph pipeline.

These are pure state -> next-node-name mappings with no I/O, which makes them
the cheapest part of the pipeline to test directly. Extracted from graph.py so
the routing rules can be read as one small unit rather than hunted for among
the node implementations.

Re-exported from backend.services.graph for backwards compatibility.
"""

from langgraph.graph import END

from backend.models import CacheStatus
from backend.services.pipeline.state import PipelineState


def route_supervisor(state: PipelineState) -> str:
    """Route based on supervisor loop state.

    The supervisor only receives confirmed data queries. Routes to:
    - cache_search: next sub-question to process
    - summarizer: all sub-questions done (multi-space)
    - END: all sub-questions done (single-space)
    """
    plan = state.get("supervisor_plan") or []
    step = state.get("current_step", -1)

    if not plan or step >= len(plan):
        if len(plan) > 1:
            return "summarizer"
        return END

    return "cache_search"


def route_after_memory(state: PipelineState) -> str:
    """Route after memory retrieval: greetings/assistant go to assistant, data queries go to rewrite."""
    fp = state.get("fast_path_result", "data_query")
    if fp in ("greeting", "assistant"):
        return "assistant"
    return "rewrite"


def route_cache(state: PipelineState) -> str:
    """Route based on cache search result tier.

    Tier 1 (>=0.90): Direct hit — populate params, validate SQL, execute.
    Tier 2 (0.75-0.90, has parameterized SQL): substitute new parameter values.
    Tier 3 (<0.75): Cache miss — go to Genie.
    """
    if state.get("cache_hit"):
        return "populate_params"
    if state.get("answer_morph"):
        return "answer_morph"
    return "genie_dispatch"


def route_answer_morph(state: PipelineState) -> str:
    """After answer_morph (SQL adaptation): success -> supervisor, failure -> genie_dispatch."""
    if state.get("cache_status") == CacheStatus.HIT.value:
        return "supervisor"
    return "genie_dispatch"


def route_cache_fallback(state: PipelineState) -> str:
    """After execute_cached: success → supervisor (loop back), failure → genie_dispatch."""
    if state.get("cache_status") == CacheStatus.HIT.value:
        return "supervisor"
    return "genie_dispatch"
