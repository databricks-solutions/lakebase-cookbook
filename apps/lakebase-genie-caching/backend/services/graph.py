"""LangGraph pipeline with fast-path routing and a Supervisor-Loop architecture.

Architecture:
  session (fetch history + refresh space metas) → [fast-path routing]
    greeting:         memory → assistant → END
    assistant:        memory → assistant → END
    already_answered: echo_result → END  (zero LLM calls)
    data_query:       memory → rewrite → supervisor → [data loop]

  All paths except echo_result flow through memory so that user context
  (name, preferences, prior topics) is available for personalization.

  data loop (supervisor routes one sub-question at a time):
    supervisor → cache_search → [three-tier cache routing]
      Tier 1 (>=0.90):  populate_params → execute_cached → supervisor
      Tier 2 (0.75-0.90, has parameterized SQL):
          answer_morph (Tier 2: parameter substitution into cached SQL)
          → supervisor | genie
      Tier 3 (<0.75):   genie → supervisor

    When all sub-questions are complete:
      single-space: supervisor copies result → END
      multi-space:  supervisor → summarizer → END

  Genie spaces are configured at deploy time and resolved from the Genie API
  at startup. A single generic node_genie reads current_space_id from state.

  Safety limit: each Genie space can be called at most MAX_CALLS_PER_SPACE (2) times.

MLflow GenAI Tracing captures each pipeline invocation as a trace with
per-node spans visible in the Databricks Traces UI.
"""

import asyncio
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional, TypedDict

import mlflow
from mlflow.entities import SpanType
from langgraph.graph import END, StateGraph
from databricks.sdk import WorkspaceClient

from backend.config import config
from backend.models import AskResponse, CacheStatus, MessageRole
from backend.services.cache_store import cache_store
from backend.services.genie_client import ask_genie, execute_cached_sql
from backend.services.memory_store import memory_store
from backend.services.preprocessor import normalize_query
from backend.services.query_rewriter import rewrite_query
from backend.services import auth_context
from backend.services.background import spawn as spawn_background
from backend.services.session_store import session_store
from backend.services.workspace_links import workspace_url

logger = logging.getLogger(__name__)

# Shared WorkspaceClient — instantiated once, reused across all LLM calls.
# authenticate() is still called per-request for fresh token headers.
_ws: WorkspaceClient | None = None
_ws_host: str | None = None


def _get_ws() -> tuple[WorkspaceClient, str]:
    """Return the shared (WorkspaceClient, host) singleton."""
    global _ws, _ws_host
    if _ws is None:
        _ws = WorkspaceClient()
        _ws_host = _ws.config.host.rstrip("/")
    return _ws, _ws_host


def _fix_inline_bullets(text: str) -> str:
    """Convert inline Unicode bullets (• item1 • item2) to markdown list format."""
    if "•" not in text:
        return text
    lines = text.split("\n")
    fixed = []
    for line in lines:
        if line.count("•") >= 2:
            parts = [p.strip() for p in line.split("•") if p.strip()]
            fixed.extend(f"- {p}" for p in parts)
        else:
            fixed.append(line.replace("• ", "- "))
    return "\n".join(fixed)


# ---------------------------------------------------------------------------
# Genie Space metadata (implementations in pipeline/spaces.py)
# ---------------------------------------------------------------------------

from backend.services.pipeline.spaces import (  # noqa: E402
    _get_all_active_space_metas,
    _get_space_meta,
    update_space_metas,
)

# ---------------------------------------------------------------------------
# Pipeline State (defined in pipeline/state.py)
# ---------------------------------------------------------------------------

from backend.services.pipeline.state import (  # noqa: E402
    MAX_CALLS_PER_SPACE,
    PipelineState,
    _add_event,
    _elapsed,
)

# ---------------------------------------------------------------------------
# Node: Session (resolve or create session — no intent classification)
# ---------------------------------------------------------------------------

@mlflow.trace(name="node_session", span_type=SpanType.TOOL)
async def node_session(state: PipelineState) -> PipelineState:
    """Resolve or create session. Runs before the supervisor.

    Falls back to an ephemeral in-memory session if DB is unavailable
    (e.g. Model Serving without Lakebase access).
    """
    from backend.services.db import db_available

    session = None
    if db_available():
        try:
            if state.get("session_id"):
                session = await session_store.get_session(state["session_id"])
            if not session:
                session = await session_store.create_session(state["user_id"])
            spawn_background(
                session_store.add_message(session.session_id, MessageRole.USER, state["question"]),
                name="session.add_message(user)",
            )
        except Exception as e:
            logger.warning(f"Session store unavailable, using ephemeral session: {e}")
            session = None

    if not session:
        from backend.models import Session
        import uuid as _uuid
        now = datetime.now(timezone.utc)
        session = Session(
            session_id=state.get("session_id") or str(_uuid.uuid4()),
            user_id=state["user_id"],
            created_at=now,
            updated_at=now,
        )
        logger.info("Using ephemeral in-memory session (DB unavailable)")

    # Fetch conversation history ONCE — all downstream nodes reuse this
    history = []
    if db_available() and session:
        try:
            history = await session_store.get_history(session.session_id, limit=20)
        except Exception as e:
            logger.warning(f"History fetch in session failed: {e}")

    state = _add_event(state, "session", {"session_id": session.session_id, "title": session.title})
    return {**state,
            "resolved_session_id": session.session_id,
            "session_title": session.title,
            "genie_conversation_ids": session.genie_conversation_ids or {},
            "conversation_history": history,
            "rewritten": state["question"]}


# ---------------------------------------------------------------------------
# Fast-path: greeting detection + already-answered short-circuit
# ---------------------------------------------------------------------------

_GREETING_PATTERNS = re.compile(
    r"^(h(i|ello|ey|owdy|ola)|yo|sup|thanks?|thank\s*you|thx|great|cool|ok(ay)?|"
    r"good\s*(morning|afternoon|evening|day|job|bye)|bye|goodbye|see\s*ya|"
    r"who\s*are\s*you|help(\s*me)?|"
    r"how\s*are\s*you|nice|awesome|got\s*it|sure|yes|no|nope|yep|yup)[\s!?.]*$",
    re.IGNORECASE,
)


# Prompt templates live in pipeline/prompts.py; imported here so existing
# references (and test patches against this module) keep working.
from backend.services.pipeline.prompts import (  # noqa: E402
    ASSISTANT_PROMPT,
    EMPTY_RESULTS_PROMPT,
    POPULATE_PARAMS_PROMPT,
    SUMMARIZE_PROMPT,
    SUPERVISOR_PROMPT,
    SYNTHESIS_PROMPT,
    _ALREADY_ANSWERED_PROMPT,
    _INTENT_PROMPT,
    _TITLE_PROMPT,
    _VALIDATE_SQL_PROMPT,
)


def _collect_answered_candidates(question: str, history: list) -> list[dict]:
    """Extract prior data-answered Q&A pairs from conversation history (max 5).

    Only includes answers that contain actual data/SQL results, not
    assistant-style text responses that merely describe available data.
    """
    if not history or len(history) < 2:
        return []
    if len(question.strip().split()) < 3:
        return []

    _DATA_PREFIXES = ("[Cache HIT]", "[Genie]")
    _ASSISTANT_SIGNALS = (
        "The available", "I can help", "Let me know", "available data",
        "data includes", "you can ask", "want to see",
    )

    candidates = []
    for i in range(len(history) - 1):
        msg = history[i]
        next_msg = history[i + 1] if i + 1 < len(history) else None
        if not next_msg:
            continue
        if msg.role.value != "user" or next_msg.role.value != "assistant":
            continue
        content = next_msg.content or ""
        if not any(content.startswith(p) for p in _DATA_PREFIXES):
            continue
        body = content.split("] ", 1)[-1] if "] " in content else content
        if any(sig.lower() in body[:200].lower() for sig in _ASSISTANT_SIGNALS):
            continue
        candidates.append({"prior_question": msg.content, "prior_answer": content})

    return candidates[-5:]


async def _find_already_answered(question: str, history: list) -> dict | None:
    """LLM-based check: has this question already been answered in the conversation?

    Uses a quick Haiku call to determine semantic equivalence, avoiding
    false matches from naive word overlap (e.g. "most common" vs "least common").
    """
    candidates = _collect_answered_candidates(question, history)
    if not candidates:
        return None

    numbered = "\n".join(
        f"{i+1}. {c['prior_question']}" for i, c in enumerate(candidates)
    )
    prompt = _ALREADY_ANSWERED_PROMPT.format(question=question, candidates=numbered)

    def _call():
        import urllib.request
        w, host = _get_ws()
        headers = w.config.authenticate()
        url = f"{host}/serving-endpoints/{config.llm.classifier_endpoint}/invocations"
        payload = json.dumps({
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4,
            "temperature": 0.0,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={
            **headers, "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=config.timeouts.classifier_llm) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip().lower()

    try:
        answer = await asyncio.to_thread(_call)
        if answer == "none" or not answer.isdigit():
            return None
        idx = int(answer) - 1
        if 0 <= idx < len(candidates):
            match = candidates[idx]
            logger.info(
                f"Already-answered (LLM match #{idx+1}): "
                f"'{question}' ≈ '{match['prior_question'][:60]}'"
            )
            return match
        return None
    except Exception as e:
        logger.warning(f"Already-answered LLM check failed, skipping: {e}")
        return None




async def _classify_intent(question: str) -> str:
    """Quick Haiku call to classify intent. Returns 'data' or 'assistant'."""
    prompt = _INTENT_PROMPT.format(question=question)

    def _call():
        import urllib.request
        w, host = _get_ws()
        headers = w.config.authenticate()
        url = f"{host}/serving-endpoints/{config.llm.classifier_endpoint}/invocations"
        payload = json.dumps({
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4,
            "temperature": 0.0,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={
            **headers, "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=config.timeouts.classifier_llm) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip().lower()

    try:
        answer = await asyncio.to_thread(_call)
        if answer.startswith("assistant"):
            return "assistant"
        return "data"
    except Exception as e:
        logger.warning(f"Intent classification failed, defaulting to data: {e}")
        return "data"


@mlflow.trace(name="node_fast_path", span_type=SpanType.CHAIN)
async def node_fast_path(state: PipelineState) -> PipelineState:
    """Fast-path node: greeting regex, already-answered check, Haiku intent classifier.

    Stores the routing decision in state['fast_path_result'] for the
    sync routing function to read.
    """
    question = state["question"].strip()

    # 1. Greeting regex — instant, no LLM
    if _GREETING_PATTERNS.match(question):
        logger.info(f"Fast-path: greeting detected ('{question}')")
        state = _add_event(state, "thinking", {
            "node": "fast_path", "label": "Greeting detected",
            "detail": f"Regex matched \"{question}\" — routing to memory → assistant (no LLM needed)",
        })
        return {**state, "fast_path_result": "greeting"}

    # 2. Already-answered — Haiku LLM check against conversation history
    history = state.get("conversation_history") or []
    candidates = _collect_answered_candidates(question, history)
    if candidates:
        state = _add_event(state, "thinking", {
            "node": "fast_path", "label": "Checking conversation history",
            "detail": f"Found {len(candidates)} prior data answer(s) — asking Haiku if any match semantically",
        })
    match = await _find_already_answered(question, history)
    if match:
        state = _add_event(state, "thinking", {
            "node": "fast_path", "label": "Already answered",
            "detail": f"Haiku confirmed match: \"{match['prior_question'][:80]}\" — returning prior answer",
        })
        return {**state, "fast_path_result": "echo_result", "echo_match": match}

    # 3. Haiku intent classifier — cheap/fast LLM call
    state = _add_event(state, "thinking", {
        "node": "fast_path", "label": "Classifying intent (Haiku)",
        "detail": f"Asking Haiku: is \"{question}\" a data query or general question?",
    })
    intent = await _classify_intent(question)
    logger.info(f"Fast-path: Haiku intent={intent} for '{question[:60]}'")

    if intent == "assistant":
        state = _add_event(state, "thinking", {
            "node": "fast_path", "label": f"Intent: assistant",
            "detail": "Haiku classified as general/meta question — routing to memory → assistant",
        })
        return {**state, "fast_path_result": "assistant"}

    state = _add_event(state, "thinking", {
        "node": "fast_path", "label": "Intent: data query",
        "detail": "Haiku classified as data question — proceeding to memory → rewrite → supervisor → cache/Genie",
    })
    return {**state, "fast_path_result": "data_query"}


def route_fast_path(state: PipelineState) -> str:
    """Sync routing function that reads the fast-path decision from state."""
    return state.get("fast_path_result", "data_query")


@mlflow.trace(name="node_echo_result", span_type=SpanType.CHAIN)
async def node_echo_result(state: PipelineState) -> PipelineState:
    """Return a prior answer from conversation history — zero LLM calls."""
    match = state.get("echo_match")

    if match:
        prior_answer = match["prior_answer"]
        # Strip the [Cache HIT] or [Genie] tag prefix
        for tag in ("[Cache HIT] ", "[Genie] "):
            if prior_answer.startswith(tag):
                prior_answer = prior_answer[len(tag):]
                break

        description = (
            f"I answered a similar question earlier in this conversation:\n\n"
            f"{prior_answer}"
        )
    else:
        description = "I couldn't find the prior answer. Please try asking again."

    latency = (time.time() - state["start_time"]) * 1000
    state = _add_event(state, "status", {"step": "echo", "message": "Returning previous answer..."})
    state = _add_event(state, "status", {"step": "response", "message": "Response ready"})

    from backend.services.db import db_available
    if db_available():
        try:
            await session_store.add_message(
                state["resolved_session_id"], MessageRole.ASSISTANT,
                f"[Echo] {description}"
            )
        except Exception:
            pass

    return {**state,
            "intent": "echo",
            "sql": None,
            "description": description,
            "exec_columns": None,
            "exec_data": None,
            "exec_row_count": None,
            "cache_status": CacheStatus.MISS.value,
            "similarity_score": None,
            "latency_ms": latency,
            "genie_latency_ms": None,
            "genie_steps": None,
            "follow_up_questions": None}


# ---------------------------------------------------------------------------
# Node: Supervisor (unified intent + routing in a single LLM call)
# ---------------------------------------------------------------------------



@mlflow.trace(name="node_supervisor", span_type=SpanType.CHAIN)
async def node_supervisor(state: PipelineState) -> PipelineState:
    """Stateful supervisor: decomposes confirmed data queries into sub-tasks.

    Only receives data queries (intent classification handled by fast-path).

    First call:
      - Runs LLM to decompose question into space-routed sub-tasks
      - Sets supervisor_plan, intent='data_query', current_step=0
    Loop-back calls (current_step already set):
      - Resets per-iteration cache state
      - Advances current_step and sets current_space_id / current_task
      - If all steps complete: routes to summarizer (multi) or END (single)
    """
    plan = state.get("supervisor_plan") or []
    completed = list(state.get("completed_results") or [])
    step = state.get("current_step", -1)

    # ── Loop-back: plan already exists, advance to next step ──
    if plan and step >= 0:
        return await _supervisor_advance(state)

    # ── First call: create the plan ──
    state = _add_event(state, "status", {"step": "supervisor", "message": "Supervisor analyzing query..."})
    raw_question = state["question"]
    question = state.get("rewritten", raw_question)
    active_metas = _get_all_active_space_metas()

    # ── Use pre-fetched conversation history from node_session ──
    history = state.get("conversation_history") or []

    # ── Build history section for the supervisor prompt ──
    history_section = ""
    if history and len(history) > 1:
        history_lines = []
        for msg in history:
            role_label = "User" if msg.role.value == "user" else "Assistant"
            content = msg.content
            if len(content) > 300:
                content = content[:300] + "..."
            history_lines.append(f"  {role_label}: {content}")
        history_section = (
            "Conversation history (use this to resolve follow-up references):\n"
            + "\n".join(history_lines)
            + "\n\n"
        )

    # ── LLM-based supervisor decision (works with 1 or N spaces) ──
    spaces_list = "\n".join(
        f'- "{s["space_id"]}": {s["title"]} — {s.get("description", "(no description)")}'
        for s in active_metas
    )
    prompt = SUPERVISOR_PROMPT.format(
        spaces_list=spaces_list, question=question, history_section=history_section
    )

    def _call():
        import urllib.request as urllib_request
        w, host = _get_ws()
        headers = w.config.authenticate()
        body = json.dumps({
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2048,
            "temperature": 0.0,
        }).encode()
        endpoint = f"{host}/serving-endpoints/{config.llm.assistant_endpoint}/invocations"
        req = urllib_request.Request(endpoint, data=body, headers={**headers, "Content-Type": "application/json"})
        resp = json.loads(urllib_request.urlopen(req, timeout=config.timeouts.supervisor_llm).read())
        return resp["choices"][0]["message"]["content"].strip()

    try:
        raw = await asyncio.to_thread(_call)
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            raw = raw.rsplit("```", 1)[0]
        plan = json.loads(raw.strip())

        if not isinstance(plan, list) or not plan:
            raise ValueError(f"Expected non-empty list, got: {type(plan)}")

        valid_ids = {s["space_id"] for s in active_metas}
        validated = []
        for task in plan:
            agent = task.get("agent", "")
            if agent in valid_ids:
                validated.append(task)
            elif agent == "assistant":
                # Supervisor should not route to assistant — fast-path handles that.
                # Re-route to first available space as a fallback.
                validated.append({**task, "agent": active_metas[0]["space_id"]})
            else:
                for vid in valid_ids:
                    if vid in agent or agent in vid:
                        validated.append({**task, "agent": vid})
                        break
        plan = validated if validated else [{"agent": active_metas[0]["space_id"], "task": question}]

    except Exception as e:
        logger.warning(f"Supervisor LLM failed: {e}, falling back to first space")
        plan = [{"agent": active_metas[0]["space_id"], "task": question}]

    intent = "data_query"

    title_lookup = {m["space_id"]: m["title"] for m in active_metas}
    title_lookup["assistant"] = "Assistant"
    plan_desc = ", ".join(title_lookup.get(t["agent"], t["agent"]) for t in plan)

    plan_details = []
    for t in plan:
        plan_details.append({
            "agent": title_lookup.get(t["agent"], t["agent"]),
            "agent_id": t["agent"],
            "task": t["task"],
            "step": t.get("step", 1),
        })

    state = _add_event(state, "intent", {
        "intent": intent,
        "message": f"Supervisor → {len(plan)} task(s): {plan_desc}",
        "plan": plan_details,
    })

    # Thinking: show the decomposition
    task_lines = "; ".join(f"{title_lookup.get(t['agent'], t['agent'])}: {t['task']}" for t in plan)
    state = _add_event(state, "thinking", {
        "node": "supervisor", "label": f"Decomposed into {len(plan)} sub-task(s) (Sonnet)",
        "detail": task_lines,
    })

    logger.info(f"Supervisor ({config.llm.assistant_endpoint}): {len(plan)} task(s), intent={intent}")

    # Set up the first iteration of the data query loop
    first_task = plan[0]
    space_id = first_task["agent"]
    counts = {space_id: 1}
    state = _add_event(state, "status", {
        "step": "dispatch",
        "message": f"Processing: {title_lookup.get(space_id, space_id)} — {first_task['task'][:150]}",
    })
    return {**state, "supervisor_plan": plan, "intent": intent,
            "current_step": 0, "current_space_id": space_id,
            "current_task": first_task["task"],
            "current_task_raw": first_task["task"],
            "completed_results": [], "space_call_counts": counts,
            "cache_result": None, "cache_hit": False,
            "answer_morph": False, "similarity_score": None}


async def _supervisor_advance(state: PipelineState) -> PipelineState:
    """Advance the supervisor loop to the next sub-question, or finalize."""
    plan = state["supervisor_plan"]
    step = state["current_step"]
    completed = list(state.get("completed_results") or [])
    counts = dict(state.get("space_call_counts") or {})
    active_metas = _get_all_active_space_metas()
    title_lookup = {m["space_id"]: m["title"] for m in active_metas}

    next_step = step + 1

    # Check if we're done
    if next_step >= len(plan):
        logger.info(f"Supervisor loop complete: {len(completed)} result(s)")
        if len(plan) == 1:
            # Single-space: copy the result into main state fields and route to END
            r = completed[0] if completed else {}
            latency = (time.time() - state["start_time"]) * 1000
            cache_hit = r.get("cache_hit", False)
            cache_status = CacheStatus.HIT.value if cache_hit else CacheStatus.MISS.value

            # Persist to session
            from backend.services.db import db_available
            if db_available():
                tag = "Cache HIT" if cache_hit else "Genie"
                try:
                    spawn_background(
                        session_store.add_message(
                            state["resolved_session_id"], MessageRole.ASSISTANT,
                            f"[{tag}] {r.get('description', '')}"
                        ),
                        name="session.add_message(assistant)",
                    )
                except Exception as e:
                    logger.warning("Could not record assistant message: %s", e)

            state = _add_event(state, "status", {"step": "response", "message": "Response ready"})
            return {**state,
                    "current_step": next_step,
                    "sql": r.get("sql"),
                    "description": r.get("description"),
                    "exec_columns": r.get("columns"),
                    "exec_data": r.get("data"),
                    "exec_row_count": r.get("row_count"),
                    "cache_status": cache_status,
                    "latency_ms": latency,
                    "genie_latency_ms": r.get("genie_latency_ms"),
                    "selected_space_id": r.get("space_id"),
                    "genie_steps": r.get("execution_steps"),
                    "follow_up_questions": r.get("follow_up_questions"),
                    "sub_results": None}
        else:
            # Multi-space: route to summarizer
            state = _add_event(state, "status", {"step": "summarize", "message": "Combining results..."})
            return {**state, "current_step": next_step}

    # More steps remain — dispatch next sub-question
    next_task = plan[next_step]
    space_id = next_task["agent"]

    # Safety limit: max calls per space
    space_count = counts.get(space_id, 0) + 1
    if space_count > MAX_CALLS_PER_SPACE:
        logger.warning(f"Space {space_id} hit call limit ({MAX_CALLS_PER_SPACE}), skipping")
        completed.append({
            "space_id": space_id,
            "space_title": title_lookup.get(space_id, "Unknown"),
            "sub_question": next_task["task"],
            "description": f"Skipped: reached the {MAX_CALLS_PER_SPACE}-call limit for this space.",
            "sql": None, "columns": None, "data": None, "row_count": 0,
        })
        state = {**state, "completed_results": completed, "current_step": next_step}
        return await _supervisor_advance(state)

    counts[space_id] = space_count

    # ── Enrich dependent sub-tasks with prior results ──
    raw_task_text = next_task["task"]
    task_text = raw_task_text
    current_plan_step = next_task.get("step", 1)
    prev_plan_step = plan[step].get("step", 1) if step < len(plan) else 0
    if completed and current_plan_step > prev_plan_step:
        task_text = await _enrich_dependent_task(task_text, completed, state)

    state = _add_event(state, "status", {
        "step": "dispatch",
        "message": f"Processing ({next_step + 1}/{len(plan)}): "
                   f"{title_lookup.get(space_id, space_id)} — {task_text[:120]}",
    })

    logger.info(f"Supervisor dispatching step {next_step}: space={space_id}, task={task_text[:120]}")
    return {**state,
            "current_step": next_step,
            "current_space_id": space_id,
            "current_task": task_text,
            "current_task_raw": raw_task_text,
            "space_call_counts": counts,
            # Reset per-iteration cache state
            "cache_result": None, "cache_hit": False,
            "answer_morph": False, "similarity_score": None}


async def _enrich_dependent_task(task_text: str, completed: list[dict],
                                  state: PipelineState) -> str:
    """Rewrite a dependent sub-task by substituting concrete values from prior results."""
    context_parts = []
    for r in completed:
        desc = r.get("description", "")
        data = r.get("data")
        cols = r.get("columns")
        if data and cols:
            sample_rows = data[:10]
            rows_str = "; ".join(
                ", ".join(f"{cols[ci]}={cell}" for ci, cell in enumerate(row))
                for row in sample_rows
            )
            context_parts.append(f"[{r.get('space_title', '')}] {rows_str}")
        elif desc:
            context_parts.append(f"[{r.get('space_title', '')}] {desc[:300]}")

    if not context_parts:
        return task_text

    context_block = "\n".join(context_parts)
    prompt = (
        "Rewrite the following data question by substituting vague references "
        "(like 'top 5 products', 'those items', 'the results above') with the "
        "actual concrete values from the context below.\n\n"
        f"Original question: {task_text}\n\n"
        f"Context from prior query results:\n{context_block}\n\n"
        "Return ONLY the rewritten question. Keep it concise and natural. "
        "Do NOT add explanation or preamble."
    )

    try:
        def _call():
            import urllib.request as urllib_request
            w, host = _get_ws()
            headers = w.config.authenticate()
            body = json.dumps({
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 512,
                "temperature": 0.0,
            }).encode()
            endpoint = f"{host}/serving-endpoints/{config.llm.classifier_endpoint}/invocations"
            req = urllib_request.Request(endpoint, data=body,
                                        headers={**headers, "Content-Type": "application/json"})
            resp = json.loads(urllib_request.urlopen(req, timeout=config.timeouts.classifier_llm).read())
            return resp["choices"][0]["message"]["content"].strip()

        enriched = await asyncio.to_thread(_call)
        if enriched and len(enriched) > 10:
            logger.info(f"Enriched dependent task: '{task_text[:60]}' → '{enriched[:60]}'")
            state = _add_event(state, "thinking", {
                "node": "supervisor",
                "label": "Enriched with prior results (Haiku)",
                "detail": enriched[:150],
            })
            return enriched
    except Exception as e:
        logger.warning(f"Dependent task enrichment failed: {e}")

    return task_text


# ---------------------------------------------------------------------------
# Node: Rewrite (only called for data queries with multi-turn history)
# ---------------------------------------------------------------------------

@mlflow.trace(name="node_rewrite", span_type=SpanType.CHAIN)
async def node_rewrite(state: PipelineState) -> PipelineState:
    """Rewrite query using conversation history and user memory.

    Memory context (fetched upstream by node_memory) is folded into the
    rewrite prompt so the LLM can resolve conflicts between explicit user
    intent and stored preferences.
    """
    memory_context = state.get("memory_context")
    history = state.get("conversation_history") or []

    has_history = len(history) > 1
    has_memory = bool(memory_context)
    if not has_history and not has_memory:
        state = _add_event(state, "thinking", {
            "node": "rewrite", "label": "No rewrite needed",
            "detail": "First question in conversation, no history or memory to integrate",
        })
        return state

    try:
        state = _add_event(state, "status", {"step": "rewrite", "message": "Analyzing query..."})
        state = _add_event(state, "thinking", {
            "node": "rewrite", "label": "Rewriting query (Sonnet)",
            "detail": f"Integrating {'conversation history' if has_history else ''}{' + ' if has_history and has_memory else ''}{'user memory' if has_memory else ''} into standalone question",
        })
        rewritten = await rewrite_query(state["question"], history, memory_context)
        if rewritten != state["question"]:
            state = _add_event(state, "rewrite", {"original": state["question"], "rewritten": rewritten})
            state = _add_event(state, "thinking", {
                "node": "rewrite", "label": "Query rewritten",
                "detail": f"\"{state['question'][:50]}\" → \"{rewritten[:80]}\"",
            })
            return {**state, "rewritten": rewritten}
        else:
            state = _add_event(state, "thinking", {
                "node": "rewrite", "label": "Query unchanged",
                "detail": "LLM determined the question is already standalone",
            })
    except Exception as e:
        logger.warning(f"Rewrite failed: {e}")

    return state


# ---------------------------------------------------------------------------
# Node: Cache Search
# ---------------------------------------------------------------------------

async def _dual_cache_search(
    search_query: str,
    original_query: str,
    space_id: str | None,
    raw_query: str | None = None,
) -> "CacheSearchResult | None":
    """Search cache with multiple query variants, return the best match.

    Searches with up to three variants in parallel:
    - search_query: the (potentially enriched) current task
    - original_query: the top-level user question
    - raw_query: the un-enriched sub-task from the supervisor plan

    For multi-step dependent tasks, the enrichment step substitutes concrete
    values (e.g. "Prostate, Breast") into the sub-question, which changes
    semantics enough to miss cached entries that use generic phrasing
    (e.g. "the top 3 products by revenue").  Searching the raw un-enriched
    task catches these matches.
    """
    from backend.services.embedding import get_embedding
    from backend.models import CacheSearchResult

    unique_queries = list(dict.fromkeys(
        q for q in [search_query, raw_query, original_query] if q
    ))

    if len(unique_queries) == 1:
        return await cache_store.search(unique_queries[0], space_id=space_id)

    embeddings = await asyncio.gather(*(get_embedding(q) for q in unique_queries))
    results = await asyncio.gather(*(
        cache_store.search(q, space_id=space_id, embedding=emb)
        for q, emb in zip(unique_queries, embeddings)
    ))

    candidates = [r for r in results if r is not None]
    if not candidates:
        return None
    best = max(candidates, key=lambda r: r.similarity_score)

    best_idx = results.index(best)
    if best_idx > 0:
        primary_sim = results[0].similarity_score if results[0] else 0.0
        logger.info(
            f"Multi-query cache: variant '{unique_queries[best_idx][:60]}' "
            f"matched better ({best.similarity_score:.3f} vs primary {primary_sim:.3f})"
        )
    return best


@mlflow.trace(name="node_cache_search", span_type=SpanType.RETRIEVER)
async def node_cache_search(state: PipelineState) -> PipelineState:
    state = _add_event(state, "status", {"step": "cache_search", "message": "Searching semantic cache..."})

    if state.get("bypass_cache"):
        logger.info("Cache search skipped (A/B bypass)")
        state = _add_event(state, "cache_miss", {"message": "Cache bypassed (A/B comparison) — going straight to Genie"})
        return {**state, "cache_result": None, "cache_hit": False, "answer_morph": False, "similarity_score": None}

    from backend.services.db import db_available
    if not db_available():
        # Same distinction as the exception path below: the cache is down, which
        # is not the same as this question not being cached.
        logger.warning("Cache search skipped: Lakebase unavailable, answering via Genie")
        state = _add_event(state, "cache_unavailable", {
            "message": "Cache is unavailable, answering with Genie directly.",
            "error_type": "DatabaseUnavailable",
            "detail": "Lakebase connection is not established.",
        })
        return {
            **state,
            "cache_result": None,
            "cache_hit": False,
            "answer_morph": False,
            "similarity_score": None,
            "cache_status": CacheStatus.UNAVAILABLE.value,
        }

    target_space_id = state.get("current_space_id")
    search_query = state.get("current_task") or state["rewritten"]
    original_query = state["question"]
    raw_query = state.get("current_task_raw")

    try:
        result = await _dual_cache_search(search_query, original_query, target_space_id, raw_query=raw_query)
    except Exception as e:
        # A cache *outage* is not a cache *miss*. Both fall through to Genie so
        # the user still gets an answer, but they are reported as distinct events:
        # emitting "cache_miss" here made a Lakebase failure look like normal
        # behaviour, hiding the outage from anyone watching the UI or metrics.
        logger.error(f"Cache search failed, falling back to Genie: {e}", exc_info=True)
        state = _add_event(state, "cache_unavailable", {
            "message": "Cache is unavailable, answering with Genie directly.",
            "error_type": type(e).__name__,
            "detail": str(e)[:200],
        })
        return {
            **state,
            "cache_result": None,
            "cache_hit": False,
            "answer_morph": False,
            "similarity_score": None,
            "cache_status": CacheStatus.UNAVAILABLE.value,
        }

    cache_hit = False
    answer_morph = False
    cache_dict = None

    def _make_cache_dict(entry, similarity):
        return {
            "entry_id": entry.id,
            "cached_sql": entry.cached_sql,
            "cached_question": entry.query_text,
            "similarity": similarity,
            "record_type": entry.record_type,
            "parameterized_sql": entry.parameterized_sql,
            "parameters": entry.parameters,
        }

    if result and result.similarity_score >= config.cache.similarity_threshold:
        cache_hit = True
        cache_dict = _make_cache_dict(result.entry, result.similarity_score)
        record_label = "FAQ" if result.entry.record_type == "faq" else "Cache"
        state = _add_event(state, "cache_hit", {
            "similarity": round(result.similarity_score, 4),
            "cached_sql": result.entry.cached_sql,
            "record_type": result.entry.record_type,
            "message": f"{record_label} hit! {result.similarity_score * 100:.1f}% match",
        })
        state = _add_event(state, "thinking", {
            "node": "cache", "label": f"Cache HIT ({result.similarity_score*100:.0f}%)",
            "detail": f"Matched: \"{result.entry.query_text}\" — will re-execute SQL for fresh data",
        })
    elif (
        result
        and result.similarity_score >= config.cache.answer_morph_threshold
        and result.entry.parameterized_sql
    ):
        answer_morph = True
        cache_dict = _make_cache_dict(result.entry, result.similarity_score)
        strategy = "SQL adaptation"
        state = _add_event(state, "answer_morph_candidate", {
            "similarity": round(result.similarity_score, 4),
            "cached_question": result.entry.query_text,
            "message": (
                f"Tier 2 candidate ({result.similarity_score * 100:.1f}%), "
                f"strategy: {strategy}"
            ),
        })
        state = _add_event(state, "thinking", {
            "node": "cache", "label": f"Tier 2: {strategy} ({result.similarity_score*100:.0f}%)",
            "detail": f"Similar to: \"{result.entry.query_text}\" — will try {strategy}",
        })
    elif result:
        cache_dict = _make_cache_dict(result.entry, result.similarity_score)
        score_pct = result.similarity_score * 100
        morph_pct = config.cache.answer_morph_threshold * 100
        hit_pct = config.cache.similarity_threshold * 100
        if result.similarity_score >= config.cache.answer_morph_threshold:
            reason = f"Match at {score_pct:.0f}% (below {hit_pct:.0f}% hit threshold) but no SQL or cached answer to adapt — calling Genie"
        else:
            reason = f"Best match at {score_pct:.0f}% — below {morph_pct:.0f}% morph threshold, calling Genie"
        state = _add_event(state, "cache_miss", {
            "similarity": round(result.similarity_score, 4),
            "message": reason,
        })
        state = _add_event(state, "thinking", {
            "node": "cache", "label": f"Cache miss ({score_pct:.0f}%)",
            "detail": reason,
        })
    else:
        state = _add_event(state, "cache_miss", {"message": "No cache match found, calling Genie..."})
        state = _add_event(state, "thinking", {
            "node": "cache", "label": "Cache miss (no match)",
            "detail": "No similar queries found in semantic cache — calling Genie for fresh SQL",
        })

    return {**state, "cache_result": cache_dict, "cache_hit": cache_hit,
            "answer_morph": answer_morph,
            "similarity_score": result.similarity_score if result else None}


# ---------------------------------------------------------------------------
# Node: Memory (unified user memory)
# ---------------------------------------------------------------------------

@mlflow.trace(name="node_memory", span_type=SpanType.RETRIEVER)
async def node_memory(state: PipelineState) -> PipelineState:
    state = _add_event(state, "status", {"step": "memory", "message": "Retrieving memory context..."})

    from backend.services.db import db_available
    if not db_available():
        logger.info("Memory search skipped (DB unavailable)")
        return {**state, "memory_context": None}

    try:
        entries = await memory_store.search(state["question"], state["user_id"])
        memory_context = [e.content for e in entries] if entries else None
    except Exception as e:
        logger.warning(f"Memory search failed: {e}")
        memory_context = None

    if memory_context:
        mem_summary = " | ".join(m[:50] for m in memory_context[:3])
        state = _add_event(state, "thinking", {
            "node": "memory", "label": f"Found {len(memory_context)} memories",
            "detail": mem_summary,
        })
    else:
        state = _add_event(state, "thinking", {
            "node": "memory", "label": "No relevant memories found",
            "detail": "Proceeding without user memory context",
        })

    return {**state, "memory_context": memory_context}


# ---------------------------------------------------------------------------
# Node: Populate Parameters (cache hit with parameterized SQL)
# ---------------------------------------------------------------------------



def _substitute_params(sql: str, params: dict) -> str:
    """Substitute :param placeholders in SQL with values from *params*.

    - String values are single-quoted unless the placeholder is already inside
      a quoted string literal (e.g. ``'%:disease%'``).
    - Numeric values are inserted as-is.
    - Keys are processed longest-first to avoid prefix collisions.
    """
    result = sql
    for key in sorted(params.keys(), key=len, reverse=True):
        value = params[key]
        if value is None:
            continue
        pattern = re.compile(rf":{re.escape(key)}\b")
        if isinstance(value, str):
            escaped = value.replace("'", "''")

            def _replace_in_context(m: re.Match, _escaped=escaped, _result=result) -> str:
                prefix = _result[:m.start()]
                in_quotes = prefix.count("'") % 2 == 1
                return _escaped if in_quotes else f"'{_escaped}'"

            result = pattern.sub(_replace_in_context, result)
        else:
            result = pattern.sub(str(value), result)
    return result


@mlflow.trace(name="node_populate_params", span_type=SpanType.LLM)
async def node_populate_params(state: PipelineState) -> PipelineState:
    """Extract entities from the current query and populate the parameterized SQL template.

    For FAQ entries without SQL, this node is a pass-through.
    For entries without parameterized_sql, uses the raw cached_sql.
    """
    cache_dict = state.get("cache_result")
    if not cache_dict:
        return state

    parameterized_sql = cache_dict.get("parameterized_sql")
    cached_params = cache_dict.get("parameters") or {}

    logger.info(
        f"populate_params: parameterized_sql={bool(parameterized_sql)}, "
        f"cached_params={cached_params}, "
        f"populate_enabled={config.cache.populate_params_on_query}, "
        f"answer_morph={state.get('answer_morph')}"
    )

    # No parameterized template or feature disabled -> use raw SQL as-is
    if not parameterized_sql or not cached_params or not config.cache.populate_params_on_query:
        return state

    param_names = ", ".join(cached_params.keys())
    state = _add_event(state, "thinking", {
        "node": "populate_params", "label": f"Populating params: {param_names}",
        "detail": f"Extracting entity values for [{param_names}] from question (Sonnet)",
    })
    state = _add_event(state, "status", {
        "step": "populate_params",
        "message": "Extracting entities for parameterized SQL..."
    })

    try:
        prompt = POPULATE_PARAMS_PROMPT.format(
            param_names=", ".join(cached_params.keys()),
            example_values=json.dumps(cached_params),
            question=state.get("current_task") or state["question"],
        )

        def _call():
            import urllib.request
            w, host = _get_ws()
            headers = w.config.authenticate()

            url = f"{host}/serving-endpoints/{config.llm.assistant_endpoint}/invocations"
            payload = json.dumps({
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 256,
                "temperature": 0.0,
            }).encode("utf-8")

            req = urllib.request.Request(url, data=payload, headers={
                **headers,
                "Content-Type": "application/json",
            })
            with urllib.request.urlopen(req, timeout=config.timeouts.assistant_llm) as resp:
                data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()

        raw = await asyncio.to_thread(_call)

        # Parse the response
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            raw = raw.rsplit("```", 1)[0]

        new_params = json.loads(raw.strip())

        if isinstance(new_params, dict) and new_params:
            # Fall back to original cached values for None/empty extractions
            for key in list(new_params.keys()):
                if new_params[key] is None or new_params[key] == "":
                    if key in cached_params and cached_params[key] is not None:
                        logger.info(
                            f"Param '{key}' not found in question, "
                            f"keeping original: {cached_params[key]}"
                        )
                        new_params[key] = cached_params[key]

            populated_sql = _substitute_params(parameterized_sql, new_params)

            # Validate: if any of the expected :param placeholders remain,
            # substitution is incomplete — fall back to the raw cached SQL
            # instead of sending broken SQL to the warehouse.
            leftover = [
                k for k in cached_params
                if re.search(rf":{re.escape(k)}\b", populated_sql)
            ]
            if leftover:
                logger.warning(
                    f"Parameterized SQL still has unresolved placeholders {leftover}, "
                    "falling back to raw cached SQL"
                )
                state = _add_event(state, "status", {
                    "step": "params_fallback",
                    "message": "Some parameters could not be resolved, using raw cached SQL",
                })
                return state

            cache_dict = {**cache_dict, "cached_sql": populated_sql}
            state = _add_event(state, "status", {
                "step": "params_populated",
                "message": f"Populated {len(new_params)} parameters in SQL template",
            })
            logger.info(f"Populated params: {new_params}")
            return {**state, "cache_result": cache_dict}

    except Exception as e:
        logger.warning(f"Parameter population failed, using raw SQL: {e}")
        state = _add_event(state, "status", {
            "step": "params_fallback",
            "message": "Parameter population failed, using raw cached SQL",
        })

    return state


# ---------------------------------------------------------------------------
# Node: Answer Morph (Tier 2: SQL adaptation → Genie)
# ---------------------------------------------------------------------------



async def _try_sql_adaptation(
    state: PipelineState, cache_dict: dict,
    user_question: str, space_id: str | None, space_title: str,
) -> PipelineState | None:
    """Phase 1: adapt parameterized SQL with new params, execute, summarize.

    Returns updated state on success, None on failure (caller routes to Genie).
    """
    parameterized_sql = cache_dict.get("parameterized_sql")
    cached_params = cache_dict.get("parameters") or {}

    if not parameterized_sql or not cached_params or not config.cache.populate_params_on_query:
        return None

    param_names = ", ".join(cached_params.keys())
    state = _add_event(state, "thinking", {
        "node": "morph", "label": f"SQL adaptation: extracting [{param_names}]",
        "detail": "Extracting new parameter values from question, then re-executing adapted SQL",
    })
    state = _add_event(state, "status", {
        "step": "sql_adaptation",
        "message": "Adapting parameterized SQL to your question...",
    })

    try:
        prompt = POPULATE_PARAMS_PROMPT.format(
            param_names=", ".join(cached_params.keys()),
            example_values=json.dumps(cached_params),
            question=user_question,
        )

        def _call_extract():
            import urllib.request
            w, host = _get_ws()
            headers = w.config.authenticate()
            url = f"{host}/serving-endpoints/{config.llm.assistant_endpoint}/invocations"
            payload = json.dumps({
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 256, "temperature": 0.0,
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={
                **headers, "Content-Type": "application/json",
            })
            with urllib.request.urlopen(req, timeout=config.timeouts.assistant_llm) as resp:
                data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()

        raw = await asyncio.to_thread(_call_extract)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            raw = raw.rsplit("```", 1)[0]

        new_params = json.loads(raw.strip())
        if not isinstance(new_params, dict) or not new_params:
            logger.info("SQL adaptation: LLM returned empty/invalid params")
            return None

        for key in list(new_params.keys()):
            if new_params[key] is None or new_params[key] == "":
                if key in cached_params and cached_params[key] is not None:
                    new_params[key] = cached_params[key]

        populated_sql = _substitute_params(parameterized_sql, new_params)
        leftover = [k for k in cached_params if re.search(rf":{re.escape(k)}\b", populated_sql)]
        if leftover:
            logger.warning(f"SQL adaptation: unresolved placeholders {leftover}")
            return None

        logger.info(f"SQL adaptation: extracted params {new_params}")
        state = _add_event(state, "thinking", {
            "node": "morph", "label": f"Params extracted: {json.dumps(new_params)}",
            "detail": "Executing adapted SQL with new parameters",
        })
        # Validate the adapted SQL before trusting it.
        #
        # Tier 2 originally skipped validation on the theory that "only parameter
        # values change". That is not true: a question can sit in the 0.75-0.90
        # band because its *semantics* differ, not its parameters. "3 rarest
        # cancers" matched a cached "3 most common cancers" template at 0.835,
        # extracted top_count=3, reused the DESC sort, and returned the most
        # common cancers labelled as the rarest -- a confidently wrong answer.
        #
        # Parameter extraction cannot catch that, because sort direction is not a
        # parameter. The same Haiku check Tier 1 already uses does.
        if not await _validate_sql(user_question, populated_sql):
            logger.info(
                "SQL adaptation rejected by validation: adapted SQL does not match "
                "the question's intent (params alone could not reconcile them)"
            )
            state = _add_event(state, "thinking", {
                "node": "morph", "label": "Adapted SQL rejected by validation",
                "detail": "The cached template's logic doesn't match this question "
                          "(e.g. a different sort or filter) — falling back to Genie",
            })
            return None

        state = _add_event(state, "status", {
            "step": "execute_sql", "message": "Executing adapted SQL on warehouse...",
        })

        columns, data, row_count = await execute_cached_sql(populated_sql, auth=auth_context.current())
        await cache_store.increment_hit(cache_dict["entry_id"])

        state = _add_event(state, "thinking", {
            "node": "morph",
            "label": f"SQL adaptation succeeded ({row_count} rows)",
            "detail": f"Parameterized SQL re-executed with adapted params — {row_count} rows",
        })

        if row_count == 0:
            history = state.get("conversation_history") or []
            description = await _summarize_empty_results(
                question=user_question, space_title=space_title,
                sql=populated_sql, history=history,
            )
        else:
            description = await _summarize_results(
                user_question, populated_sql, columns, data, row_count,
            )

        completed = list(state.get("completed_results") or [])
        sub = {
            "space_id": space_id, "space_title": space_title,
            "sub_question": user_question, "sql": populated_sql,
            "description": description, "columns": columns,
            "data": data, "row_count": row_count,
            "cache_hit": True, "similarity": cache_dict.get("similarity"),
            "source": "sql_adaptation",
        }
        completed.append(sub)

        state = _add_event(state, "sub_result", {
            "space_id": space_id, "space_title": space_title,
            "sub_question": user_question, "sql": populated_sql,
            "description": description, "columns": columns,
            "data": data[:50] if data else None, "row_count": row_count,
            "cache_hit": True, "index": len(completed) - 1,
        })

        sim_pct = cache_dict.get("similarity", 0) * 100
        state = _add_event(state, "answer_morph_success", {
            "similarity": round(cache_dict.get("similarity", 0), 4),
            "message": f"SQL adaptation from {sim_pct:.1f}% match — {row_count} rows",
        })
        return {**state, "completed_results": completed, "cache_status": CacheStatus.HIT.value}

    except Exception as e:
        logger.warning(f"SQL adaptation failed: {e}")
        state = _add_event(state, "thinking", {
            "node": "morph", "label": "SQL adaptation failed",
            "detail": f"Error: {str(e)[:120]} — routing to Genie",
        })
        return None


@mlflow.trace(name="node_answer_morph", span_type=SpanType.CHAIN)
async def node_answer_morph(state: PipelineState) -> PipelineState:
    """Tier 2: adapt the cached SQL template, else fall through to Genie.

    Phase 1 (SQL adaptation): If parameterized_sql + parameters exist, extract
    new param values from the user's question, substitute, execute, summarize.
    Returns real tabular data.

    Fails: return miss → routes to Genie.
    """
    cache_dict = state.get("cache_result")
    if not cache_dict:
        return {**state, "cache_hit": False, "answer_morph": False}

    user_question = state.get("current_task") or state["question"]
    space_id = state.get("current_space_id")
    space_title = _get_space_meta(space_id).get("title", "Unknown Space") if space_id else "Unknown Space"

    # Phase 1: SQL adaptation
    result = await _try_sql_adaptation(state, cache_dict, user_question, space_id, space_title)
    if result is not None:
        return result

    # No text-morph fallback exists. The cache stores SQL only, never answers or
    # result sets, so there is nothing to adapt without re-querying -- adaptation
    # either produces executable SQL or the question goes to Genie.
    state = _add_event(state, "cache_miss", {
        "message": "Tier 2 adaptation failed, calling Genie...",
    })
    state = _add_event(state, "thinking", {
        "node": "morph", "label": "Tier 2 failed → Genie",
        "detail": "SQL adaptation failed — routing to Genie for fresh SQL",
    })
    return {**state, "cache_hit": False, "answer_morph": False,
            "cache_status": CacheStatus.MISS.value}


# ---------------------------------------------------------------------------
# Node: Execute Cached SQL (cache hit path)
# ---------------------------------------------------------------------------



@mlflow.trace(name="summarize_results", span_type=SpanType.LLM)
async def _summarize_results(
    question: str,
    sql: str,
    columns: list[str],
    data: list[list],
    row_count: int,
) -> str:
    """Use the fast LLM to generate a natural language summary of SQL results."""
    preview_rows = data[:20]
    data_preview = "\n".join(
        ", ".join(f"{col}={val}" for col, val in zip(columns, row))
        for row in preview_rows
    )
    if row_count > 20:
        data_preview += f"\n... and {row_count - 20} more rows"

    prompt = SUMMARIZE_PROMPT.format(
        question=question,
        sql=sql,
        columns=", ".join(columns),
        row_count=row_count,
        data_preview=data_preview,
    )

    def _call():
        import json
        import urllib.request
        w, host = _get_ws()
        headers = w.config.authenticate()

        url = f"{host}/serving-endpoints/{config.llm.assistant_endpoint}/invocations"
        payload = json.dumps({
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2048,
            "temperature": 0.0,
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers={
            **headers,
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=config.timeouts.assistant_llm) as resp:
            result = json.loads(resp.read())
        return result["choices"][0]["message"]["content"].strip()

    try:
        return _fix_inline_bullets(await asyncio.to_thread(_call))
    except Exception as e:
        logger.warning(f"Result summarization failed: {e}")
        return f"Found {row_count} result{'s' if row_count != 1 else ''}."




@mlflow.trace(name="summarize_empty_results", span_type=SpanType.LLM)
async def _summarize_empty_results(
    question: str,
    space_title: str,
    sql: str | None = None,
    genie_description: str | None = None,
    history: list | None = None,
) -> str:
    """Use the LLM to generate a context-aware response for 0-row Genie results."""
    history_text = "(No previous messages)"
    if history and len(history) > 0:
        history_text = "\n".join(
            f"  {msg.role.value}: {msg.content[:300]}{'...' if len(msg.content) > 300 else ''}"
            for msg in history
        )

    sql_section = f"SQL that was attempted: {sql}\n" if sql else ""
    genie_text_section = (
        f"Genie's response: {genie_description}\n" if genie_description else ""
    )

    prompt = EMPTY_RESULTS_PROMPT.format(
        question=question,
        space_title=space_title,
        sql_section=sql_section,
        genie_text_section=genie_text_section,
        history=history_text,
    )

    def _call():
        import json
        import urllib.request
        w, host = _get_ws()
        headers = w.config.authenticate()

        url = f"{host}/serving-endpoints/{config.llm.assistant_endpoint}/invocations"
        payload = json.dumps({
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2048,
            "temperature": 0.0,
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers={
            **headers,
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=config.timeouts.assistant_llm) as resp:
            result = json.loads(resp.read())
        return result["choices"][0]["message"]["content"].strip()

    try:
        return _fix_inline_bullets(await asyncio.to_thread(_call))
    except Exception as e:
        logger.warning(f"Empty-results summarization failed: {e}")
        return (
            genie_description
            or "The query returned no results. There are no matching records for your question."
        )




@mlflow.trace(name="validate_sql", span_type=SpanType.LLM)
async def _validate_sql(question: str, sql: str) -> bool:
    """Quick LLM check that the cached SQL aligns with the user question.

    Uses the quick model (Haiku) for minimal latency.
    Defaults to True on failure (fail-open).
    """
    prompt = _VALIDATE_SQL_PROMPT.format(question=question, sql=sql)

    try:
        def _call():
            import urllib.request
            w, host = _get_ws()
            headers = w.config.authenticate()
            url = f"{host}/serving-endpoints/{config.llm.classifier_endpoint}/invocations"
            payload = json.dumps({
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 8,
                "temperature": 0.0,
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={
                **headers, "Content-Type": "application/json",
            })
            with urllib.request.urlopen(req, timeout=config.timeouts.classifier_llm) as resp:
                data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip().lower()

        answer = await asyncio.to_thread(_call)
        is_valid = answer.startswith("yes")
        logger.info(f"SQL validation: {'valid' if is_valid else 'invalid'} (answer={answer})")
        return is_valid
    except Exception as e:
        logger.warning(f"SQL validation failed, defaulting to pass: {e}")
        return True


@mlflow.trace(name="node_execute_cached", span_type=SpanType.CHAIN)
async def node_execute_cached(state: PipelineState) -> PipelineState:
    """Validate and execute cached SQL.

    First runs a quick LLM check to confirm the SQL makes sense for the
    question. On success, appends to completed_results and routes back to
    supervisor.  On failure, routes to genie_dispatch for a fresh Genie call.
    """
    cache_dict = state["cache_result"]
    record_type = cache_dict.get("record_type", "trace")
    space_id = state.get("current_space_id")
    space_title = _get_space_meta(space_id).get("title", "Unknown Space")
    sub_question = state.get("current_task") or state["question"]

    sql_to_execute = cache_dict["cached_sql"]

    # Validate against the current sub-question so multi-step queries catch
    # mismatches (e.g., cached "EMEA revenue" SQL vs "APAC revenue" question).
    validation_question = sub_question
    state = _add_event(state, "thinking", {
        "node": "execute_cached", "label": "Validating SQL (Haiku)",
        "detail": f"Checking if cached SQL matches \"{validation_question[:100]}\"",
    })
    sql_valid = await _validate_sql(validation_question, sql_to_execute)
    if not sql_valid:
        logger.info(f"SQL validation rejected cached SQL for question: {sub_question}")
        state = _add_event(state, "thinking", {
            "node": "execute_cached", "label": "SQL validation failed",
            "detail": "Haiku rejected the cached SQL as not matching the question — falling back to Genie",
        })
        state = _add_event(state, "cache_miss", {
            "message": "SQL validation rejected cached query, calling Genie...",
        })
        return {**state, "cache_hit": False, "answer_morph": False,
                "cache_status": CacheStatus.MISS.value}

    state = _add_event(state, "thinking", {
        "node": "execute_cached", "label": "SQL validated, executing",
        "detail": "Haiku confirmed SQL is valid — executing on warehouse",
    })
    state = _add_event(state, "status", {"step": "execute_sql", "message": "Executing cached SQL on warehouse..."})

    try:
        columns, data, row_count = await execute_cached_sql(sql_to_execute, auth=auth_context.current())
        await cache_store.increment_hit(cache_dict["entry_id"])

        state = _add_event(state, "thinking", {
            "node": "execute_cached",
            "label": f"SQL returned {row_count} row(s)",
            "detail": f"Executed cached SQL successfully — {row_count} rows, summarizing with Sonnet",
        })

        if row_count == 0:
            state = _add_event(state, "status", {"step": "summarize", "message": "Summarizing empty results..."})
            history = state.get("conversation_history") or []

            description = await _summarize_empty_results(
                question=sub_question,
                space_title=space_title,
                sql=sql_to_execute,
                history=history,
            )
        else:
            state = _add_event(state, "status", {"step": "summarize", "message": "Summarizing results..."})
            description = await _summarize_results(
                sub_question, sql_to_execute, columns, data, row_count,
            )

        completed = list(state.get("completed_results") or [])
        sub = {
            "space_id": space_id,
            "space_title": space_title,
            "sub_question": sub_question,
            "sql": sql_to_execute,
            "description": description,
            "columns": columns,
            "data": data,
            "row_count": row_count,
            "cache_hit": True,
        }
        completed.append(sub)

        state = _add_event(state, "sub_result", {
            "space_id": space_id,
            "space_title": space_title,
            "sub_question": sub_question,
            "sql": sql_to_execute,
            "description": description,
            "columns": columns,
            "data": data[:50] if data else None,
            "row_count": row_count,
            "cache_hit": True,
            "index": len(completed) - 1,
        })
        state = _add_event(state, "status", {
            "step": "cache_hit_done",
            "message": f"Cache hit executed: {row_count} row(s)",
        })
        return {**state, "completed_results": completed,
                "cache_status": CacheStatus.HIT.value}

    except Exception as e:
        logger.warning(f"Cached SQL execution failed, falling through to Genie: {e}")
        state = _add_event(state, "thinking", {
            "node": "execute_cached", "label": "SQL execution failed",
            "detail": f"Cached SQL threw an error — falling back to Genie: {str(e)[:120]}",
        })
        state = _add_event(state, "status", {"step": "cache_fallback", "message": "Cached SQL failed, falling back to Genie..."})
        return {**state, "cache_hit": False,
                "cache_status": CacheStatus.MISS.value}


# ---------------------------------------------------------------------------
# Genie Execution Helpers
# ---------------------------------------------------------------------------



@mlflow.trace(name="execute_space_query", span_type=SpanType.TOOL)
async def _execute_space_query(
    sub_question: str,
    space_id: str,
    space_title: str,
    conv_ids: dict,
    session_id: str,
) -> dict:
    """Execute a single sub-question against a specific Genie space.

    The caller's identity comes from the ambient auth context, not a parameter:
    this function is @mlflow.trace-decorated, and trace capture records
    arguments -- a bearer token passed here would be written to the trace.
    Genie therefore runs on-behalf-of the caller so Unity Catalog grants apply.
    """
    existing_conv_id = conv_ids.get(space_id)

    genie_response = await ask_genie(
        sub_question,
        space_id=space_id,
        conversation_id=existing_conv_id,
        auth=auth_context.current(),
    )

    if genie_response.status == "FAILED":
        logger.error(
            f"Genie call failed for space {space_id} ({space_title}): "
            f"{genie_response.error}"
        )

    if genie_response.conversation_id and genie_response.conversation_id != existing_conv_id:
        spawn_background(
            session_store.set_genie_conversation_id(
                session_id, space_id, genie_response.conversation_id
            ),
            name="session.set_genie_conversation_id",
        )

    return {
        "space_id": space_id,
        "space_title": space_title,
        "sub_question": sub_question,
        "sql": genie_response.sql,
        "description": genie_response.description,
        "columns": genie_response.columns,
        "data": genie_response.data,
        "row_count": genie_response.row_count,
        "latency_ms": genie_response.latency_ms,
        "execution_steps": genie_response.execution_steps,
        "follow_up_questions": genie_response.follow_up_questions or [],
        "conversation_id": genie_response.conversation_id,
        "message_id": genie_response.message_id,
        "status": genie_response.status,
        "error": genie_response.error,
    }


@mlflow.trace(name="synthesize_results", span_type=SpanType.LLM)
async def _synthesize_multi_results(
    question: str,
    sub_results: list[dict],
) -> str:
    """Synthesize results from multiple Genie spaces into a unified answer."""
    results_text_parts = []
    for i, r in enumerate(sub_results, 1):
        part = f"--- Source {i}: {r['space_title']} ---\n"
        part += f"Sub-question: {r.get('sub_question', 'N/A')}\n"
        if r.get("sql"):
            part += f"SQL: {r['sql']}\n"
        if r.get("columns") and r.get("data"):
            preview_rows = r["data"][:15]
            part += f"Results ({r.get('row_count', len(r['data']))} rows):\n"
            part += "\n".join(
                ", ".join(f"{col}={val}" for col, val in zip(r["columns"], row))
                for row in preview_rows
            )
            if r.get("row_count", 0) > 15:
                part += f"\n... and {r['row_count'] - 15} more rows"
        elif r.get("description"):
            part += f"Response: {r['description']}\n"
        else:
            part += "No results returned.\n"
        results_text_parts.append(part)

    results_text = "\n\n".join(results_text_parts)

    prompt = SYNTHESIS_PROMPT.format(question=question, results_text=results_text)

    def _call():
        import urllib.request
        w, host = _get_ws()
        headers = w.config.authenticate()

        url = f"{host}/serving-endpoints/{config.llm.assistant_endpoint}/invocations"
        payload = json.dumps({
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2048,
            "temperature": 0.0,
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers={
            **headers,
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=config.timeouts.assistant_llm) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()

    try:
        return _fix_inline_bullets(await asyncio.to_thread(_call))
    except Exception as e:
        logger.warning(f"Synthesis LLM failed: {e}")
        parts = []
        for r in sub_results:
            desc = r.get("description") or "(no result)"
            parts.append(f"**{r['space_title']}**: {desc}")
        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Node: Genie Dispatch (thin routing node — reads current_space_id)
# ---------------------------------------------------------------------------

@mlflow.trace(name="node_genie", span_type=SpanType.TOOL)
async def node_genie(state: PipelineState) -> PipelineState:
    """Generic Genie node: calls the space identified by current_space_id.

    Replaces per-space static nodes with a single dynamic node that reads
    the target space from state. Works with any space_id, including ones
    added at runtime.
    """
    space_id = state.get("current_space_id")
    space_meta = _get_space_meta(space_id)
    space_title = space_meta.get("title", "Unknown Space")
    sub_question = state.get("current_task") or state["question"]
    conv_ids = dict(state.get("genie_conversation_ids") or {})

    state = _add_event(state, "thinking", {
        "node": "genie", "label": f"Calling Genie: {space_title}",
        "detail": f"Sending \"{sub_question}\" to Genie Space \"{space_title}\"",
    })
    state = _add_event(state, "status", {
        "step": "genie", "message": f"Calling Genie: {space_title}...",
    })

    r = await _execute_space_query(
        sub_question=sub_question,
        space_id=space_id,
        space_title=space_title,
        conv_ids=conv_ids,
        session_id=state["resolved_session_id"],
    )

    if r.get("conversation_id"):
        conv_ids[space_id] = r["conversation_id"]

    if r.get("status") == "FAILED":
        error_msg = r.get("error") or "Unknown Genie error"
        logger.error(f"Genie query failed for {space_title}: {error_msg}")
        state = _add_event(state, "thinking", {
            "node": "genie", "label": f"Genie error: {space_title}",
            "detail": f"Genie query failed: {error_msg[:120]}",
        })
        description = (
            f"Sorry, the Genie query failed: {error_msg}\n\n"
            "This may be a temporary issue. Please try again."
        )
        state = _add_event(state, "status", {
            "step": "error",
            "message": f"Genie error ({space_title}): {error_msg[:200]}",
        })
    elif r.get("sql"):
        row_count = r.get("row_count") or 0
        state = _add_event(state, "thinking", {
            "node": "genie",
            "label": f"Genie returned {row_count} row(s)",
            "detail": f"[{space_title}] generated SQL with {row_count} rows — summarizing with Sonnet",
        })
        state = _add_event(state, "sql", {"sql": r["sql"], "space_title": space_title})
        state = _add_event(state, "status", {
            "step": "results", "message": f"[{space_title}] Got {row_count} rows",
        })

        if row_count == 0:
            state = _add_event(state, "status", {"step": "summarize", "message": "Summarizing results..."})
            history = state.get("conversation_history") or []
            description = await _summarize_empty_results(
                question=sub_question, space_title=space_title,
                sql=r.get("sql"), genie_description=r.get("description"),
                history=history,
            )
        elif r.get("columns") and r.get("data"):
            state = _add_event(state, "status", {"step": "summarize", "message": "Summarizing results..."})
            description = await _summarize_results(
                sub_question, r["sql"], r["columns"], r["data"], row_count,
            )
        else:
            description = r.get("description")
    else:
        description = r.get("description")

    for step in r.get("execution_steps", []):
        state = _add_event(state, "genie_step", {
            "space_title": space_title, "status": step["status"],
            "label": f"[{space_title}] {step['label']}",
            "genie_elapsed_s": step["elapsed_s"],
            "duration_ms": step.get("duration_ms", 0),
        })

    completed = list(state.get("completed_results") or [])
    sub = {
        "space_id": space_id, "space_title": space_title,
        "sub_question": sub_question, "sql": r.get("sql"),
        "description": description, "columns": r.get("columns"),
        "data": r.get("data"), "row_count": r.get("row_count"),
        "genie_latency_ms": r.get("latency_ms"),
        "execution_steps": r.get("execution_steps", []),
        "follow_up_questions": r.get("follow_up_questions", []),
        "conversation_id": r.get("conversation_id"),
        "message_id": r.get("message_id"),
        "cache_hit": False, "status": r.get("status"),
        "error": r.get("error"),
    }
    completed.append(sub)

    genie_data = r.get("data")
    state = _add_event(state, "sub_result", {
        "space_id": space_id, "space_title": space_title,
        "sub_question": sub_question, "sql": r.get("sql"),
        "description": description, "columns": r.get("columns"),
        "data": genie_data[:50] if genie_data else None,
        "row_count": r.get("row_count"),
        "cache_hit": False, "index": len(completed) - 1,
    })

    return {**state, "completed_results": completed,
            "genie_conversation_ids": conv_ids}


# ---------------------------------------------------------------------------
# Node: Summarizer (multi-space synthesis)
# ---------------------------------------------------------------------------

@mlflow.trace(name="node_summarizer", span_type=SpanType.CHAIN)
async def node_summarizer(state: PipelineState) -> PipelineState:
    """Synthesize completed_results from multiple spaces into a unified answer."""
    completed = state.get("completed_results") or []

    state = _add_event(state, "status", {
        "step": "synthesize",
        "message": f"Combining results from {len(completed)} space(s)...",
    })

    description = await _synthesize_multi_results(state["question"], completed)

    combined_sqls = []
    total_rows = 0
    total_genie_ms = 0
    all_follow_ups = []

    for r in completed:
        if r.get("sql"):
            combined_sqls.append(f"-- [{r['space_title']}]\n{r['sql']}")
            state = _add_event(state, "sql", {"sql": r["sql"], "space_title": r["space_title"]})
        total_rows += r.get("row_count") or 0
        total_genie_ms += r.get("genie_latency_ms") or 0
        all_follow_ups.extend(r.get("follow_up_questions", []))

    combined_sql = "\n\n".join(combined_sqls) if combined_sqls else None
    selected_sid = ", ".join(r["space_id"] for r in completed)

    latency = (time.time() - state["start_time"]) * 1000

    from backend.services.db import db_available
    if db_available():
        try:
            await session_store.add_message(
                state["resolved_session_id"], MessageRole.ASSISTANT,
                f"[Genie] {description}"
            )
        except Exception:
            pass

    display_sub_results = [{
        "space_id": r["space_id"],
        "space_title": r["space_title"],
        "sub_question": r.get("sub_question", ""),
        "sql": r.get("sql"),
        "columns": r.get("columns"),
        "data": r.get("data"),
        "row_count": r.get("row_count"),
        "description": r.get("description"),
        "conversation_id": r.get("conversation_id"),
        "message_id": r.get("message_id"),
        "cache_hit": r.get("cache_hit", False),
    } for r in completed]

    state = _add_event(state, "status", {"step": "response", "message": "Response ready"})

    return {**state,
            "sql": combined_sql,
            "description": description,
            "exec_columns": None,
            "exec_data": None,
            "exec_row_count": total_rows,
            "cache_status": CacheStatus.MISS.value,
            "selected_space_id": selected_sid,
            "latency_ms": latency,
            "genie_latency_ms": total_genie_ms,
            "genie_steps": [step for r in completed for step in r.get("execution_steps", [])],
            "follow_up_questions": all_follow_ups,
            "sub_results": display_sub_results}


# ---------------------------------------------------------------------------
# Node: Assistant sub-agent (conversation + meta, unified)
# ---------------------------------------------------------------------------



@mlflow.trace(name="assistant_llm", span_type=SpanType.LLM)
async def _assistant_llm(question: str, history_text: str, memory_context: list[str] | None = None) -> str:
    """Generate assistant response using the fast LLM with full context."""
    metas = _get_all_active_space_metas()
    spaces_detail = "\n".join(
        f'{i+1}. **{m["title"]}**: {m.get("description") or "(no description)"}'
        for i, m in enumerate(metas)
    )
    if memory_context:
        memory_section = "\nUser memory (long-term context about this user):\n" + "\n".join(
            f"- {m}" for m in memory_context
        ) + "\n"
    else:
        memory_section = ""
    prompt = ASSISTANT_PROMPT.format(
        spaces_detail=spaces_detail,
        memory_section=memory_section,
        history=history_text,
        question=question,
    )

    def _call():
        import urllib.request
        w, host = _get_ws()
        headers = w.config.authenticate()

        url = f"{host}/serving-endpoints/{config.llm.assistant_endpoint}/invocations"
        payload = json.dumps({
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2048,
            "temperature": 0.0,
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers={
            **headers,
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=config.timeouts.assistant_llm) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()

    try:
        return _fix_inline_bullets(await asyncio.to_thread(_call))
    except Exception as e:
        logger.warning(f"Assistant LLM failed: {e}")
        metas = _get_all_active_space_metas()
        lines = ["I'm having trouble generating a response, but here's what I can tell you:\n"]
        lines.append(f"You have access to {len(metas)} Genie Space(s):")
        for m in metas:
            lines.append(f"- **{m['title']}**: {m.get('description') or '(no description)'}")
        lines.append("\nTry asking a data question about any of these domains!")
        return "\n".join(lines)


@mlflow.trace(name="node_assistant", span_type=SpanType.CHAIN)
async def node_assistant(state: PipelineState) -> PipelineState:
    """Unified assistant sub-agent: handles conversation + meta questions."""
    state = _add_event(state, "status", {"step": "assistant", "message": "Assistant responding..."})

    # Use pre-fetched conversation history from node_session
    history = state.get("conversation_history") or []
    history_text = "(No previous messages in this session)"
    if history:
        history_text = "\n".join(
            f"{msg.role.value}: {msg.content}" for msg in history
        )

    description = await _assistant_llm(state["question"], history_text, state.get("memory_context"))

    latency = (time.time() - state["start_time"]) * 1000
    state = _add_event(state, "status", {"step": "response", "message": "Response ready"})

    from backend.services.db import db_available
    if db_available():
        try:
            await session_store.add_message(
                state["resolved_session_id"], MessageRole.ASSISTANT,
                f"[Assistant] {description}"
            )
        except Exception:
            pass

    # Derive intent: greeting if fast-path said so, otherwise assistant
    fp = state.get("fast_path_result")
    intent = "greeting" if fp == "greeting" else "assistant"

    return {**state,
            "intent": intent,
            "sql": None,
            "description": description,
            "exec_columns": None,
            "exec_data": None,
            "exec_row_count": None,
            "cache_status": CacheStatus.MISS.value,
            "similarity_score": None,
            "latency_ms": latency,
            "genie_latency_ms": None,
            "genie_steps": None,
            "follow_up_questions": None}


# ---------------------------------------------------------------------------
# Routing functions (implementations in pipeline/routing.py)
# ---------------------------------------------------------------------------

from backend.services.pipeline.routing import (  # noqa: E402
    route_after_memory,
    route_answer_morph,
    route_cache,
    route_cache_fallback,
    route_supervisor,
)


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------

def build_pipeline_graph(checkpointer=None) -> StateGraph:
    """Build and compile the LangGraph pipeline.

    Architecture: fast-path routing + supervisor-loop with single generic
    Genie node. History is fetched ONCE in node_session and reused.

    Flow: session → [fast-path routing]:
      greeting:         memory → assistant → END
      assistant:        memory → assistant → END
      already_answered: echo_result → END (zero LLM calls)
      data_query:       memory → rewrite → supervisor → [data loop]
        supervisor dispatches one sub-question at a time:
          cache_search → [three-tier routing]:
            Tier 1 (>=0.90) → populate_params → execute_cached → supervisor
            Tier 2 (0.75-0.90) → answer_morph (SQL adapt) → supervisor | genie
            Tier 3 (<0.75) → genie → supervisor
          When all sub-questions done:
            single-space → END (supervisor copies result)
            multi-space  → summarizer → END

    All paths except echo_result go through memory for user context.
    Genie spaces are static (configured at deploy time via GENIE_SPACE_IDS).
    """
    graph = StateGraph(PipelineState)

    # Core nodes
    graph.add_node("session", node_session)
    graph.add_node("fast_path", node_fast_path)
    graph.add_node("echo_result", node_echo_result)
    graph.add_node("rewrite", node_rewrite)
    graph.add_node("supervisor", node_supervisor)
    graph.add_node("assistant", node_assistant)
    graph.add_node("cache_search", node_cache_search)
    graph.add_node("memory", node_memory)
    graph.add_node("populate_params", node_populate_params)
    graph.add_node("answer_morph", node_answer_morph)
    graph.add_node("execute_cached", node_execute_cached)
    graph.add_node("genie_dispatch", node_genie)
    graph.add_node("summarizer", node_summarizer)

    # Entry: session → fast_path node → conditional routing
    graph.set_entry_point("session")
    graph.add_edge("session", "fast_path")
    graph.add_conditional_edges("fast_path", route_fast_path, {
        "greeting": "memory",
        "echo_result": "echo_result",
        "assistant": "memory",
        "data_query": "memory",
    })
    graph.add_edge("echo_result", END)
    graph.add_conditional_edges("memory", route_after_memory, {
        "assistant": "assistant",
        "rewrite": "rewrite",
    })
    graph.add_edge("rewrite", "supervisor")

    # Supervisor routes: cache_search | summarizer | END
    # (assistant intent is handled by fast_path, supervisor only sees data queries)
    graph.add_conditional_edges("supervisor", route_supervisor, {
        "cache_search": "cache_search",
        "summarizer": "summarizer",
        END: END,
    })

    # Cache pipeline: cache_search → [three-way routing]
    graph.add_conditional_edges("cache_search", route_cache, {
        "populate_params": "populate_params",
        "answer_morph": "answer_morph",
        "genie_dispatch": "genie_dispatch",
    })

    graph.add_edge("populate_params", "execute_cached")

    # answer_morph: success → supervisor, failure → genie_dispatch
    graph.add_conditional_edges("answer_morph", route_answer_morph, {
        "supervisor": "supervisor",
        "genie_dispatch": "genie_dispatch",
    })

    # execute_cached: success → supervisor, failure → genie_dispatch
    graph.add_conditional_edges("execute_cached", route_cache_fallback, {
        "supervisor": "supervisor",
        "genie_dispatch": "genie_dispatch",
    })

    # Genie node routes back to supervisor
    graph.add_edge("genie_dispatch", "supervisor")

    # Terminal nodes
    graph.add_edge("summarizer", END)
    graph.add_edge("assistant", END)

    return graph.compile(checkpointer=checkpointer)


# Singleton compiled graph
_compiled_graph = None


def init_pipeline(checkpointer=None):
    """Initialize the compiled pipeline graph (call once at startup)."""
    global _compiled_graph
    _compiled_graph = build_pipeline_graph(checkpointer=checkpointer)
    if checkpointer:
        logger.info("LangGraph pipeline initialized with PostgresSaver checkpointer (Lakebase)")
    else:
        logger.info("LangGraph pipeline initialized without checkpointer")
    return _compiled_graph


def get_pipeline():
    """Get or create the compiled pipeline graph."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_pipeline_graph()
    return _compiled_graph


@asynccontextmanager
async def _request_pipeline_context():
    """Yield a graph compiled with a fresh request-scoped checkpointer."""
    from backend.services.checkpointer import lakebase_checkpointer_context

    context = lakebase_checkpointer_context()
    try:
        checkpointer = await context.__aenter__()
    except Exception as e:
        logger.warning(
            "Lakebase checkpointer unavailable; running request without checkpointing: %s",
            e,
        )
        yield get_pipeline()
        return

    try:
        yield build_pipeline_graph(checkpointer=checkpointer)
    except Exception as e:
        await context.__aexit__(type(e), e, e.__traceback__)
        raise
    else:
        await context.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# Helper: Run pipeline and build AskResponse
# ---------------------------------------------------------------------------

def _build_response(question: str, final_state: dict) -> AskResponse:
    """Build an AskResponse from the final pipeline state."""
    selected_sid = final_state.get("selected_space_id")
    selected_title = None
    sub_results = final_state.get("sub_results")

    if selected_sid:
        # Multi-space: selected_sid may be comma-separated
        if "," in (selected_sid or ""):
            selected_title = " + ".join(
                _get_space_meta(sid.strip()).get("title", sid.strip())
                for sid in selected_sid.split(",")
            )
        else:
            try:
                meta = _get_space_meta(selected_sid)
                selected_title = meta.get("title")
            except Exception:
                pass

    # Build a human-readable plan for the frontend
    raw_plan = final_state.get("supervisor_plan") or []
    title_lookup_local = {}
    for m in _get_all_active_space_metas():
        title_lookup_local[m["space_id"]] = m["title"]
    title_lookup_local["assistant"] = "Assistant"
    supervisor_plan_display = [
        {"agent": title_lookup_local.get(t.get("agent", ""), t.get("agent", "")), "task": t.get("task", "")}
        for t in raw_plan
    ] if raw_plan else None

    # Include session title if already set (will be None for the first query
    # since title generation is async, but present for subsequent queries)
    session_title = final_state.get("session_title")

    return AskResponse(
        question=question,
        rewritten_question=final_state.get("rewritten") if final_state.get("rewritten") != question else None,
        intent=final_state.get("intent"),
        sql=final_state.get("sql"),
        description=final_state.get("description"),
        columns=final_state.get("exec_columns"),
        data=final_state.get("exec_data"),
        row_count=final_state.get("exec_row_count"),
        cache_status=CacheStatus(final_state.get("cache_status", "miss")),
        similarity_score=final_state.get("similarity_score"),
        latency_ms=final_state.get("latency_ms", 0),
        genie_latency_ms=final_state.get("genie_latency_ms"),
        trace_id=final_state.get("trace_id", ""),
        session_id=final_state.get("resolved_session_id", ""),
        session_title=session_title,
        memory_context=final_state.get("memory_context"),
        genie_steps=final_state.get("genie_steps"),
        follow_up_questions=final_state.get("follow_up_questions"),
        selected_space_id=selected_sid,
        selected_space_title=selected_title,
        sub_results=sub_results,
        supervisor_plan=supervisor_plan_display,
    )


# ---------------------------------------------------------------------------
# Session title generation (async, fire-and-forget)
# ---------------------------------------------------------------------------



async def _generate_session_title(session_id: str, question: str, description: str | None = None) -> None:
    """Generate a session title using the fast LLM and persist it.

    Called as a fire-and-forget task so it never blocks the response.
    Only sets the title if the session doesn't have one yet (first query).
    """
    try:
        session = await session_store.get_session(session_id)
        if session and session.title:
            return  # already titled

        hint = f"Response summary: {description[:200]}" if description else ""
        prompt = _TITLE_PROMPT.format(question=question, response_hint=hint)

        def _call_llm():
            import urllib.request
            w, host = _get_ws()
            headers = w.config.authenticate()
            url = f"{host}/serving-endpoints/{config.llm.assistant_endpoint}/invocations"
            payload = json.dumps({
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 30,
                "temperature": 0.0,
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={
                **headers, "Content-Type": "application/json",
            })
            with urllib.request.urlopen(req, timeout=config.timeouts.assistant_llm) as resp:
                data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip().strip('"').strip("'")

        title = await asyncio.to_thread(_call_llm)
        if title and len(title) > 1:
            await session_store.set_title(session_id, title)
            logger.info(f"Session {session_id[:8]} titled: {title}")
    except Exception as e:
        logger.warning(f"Session title generation failed: {e}")


_mlflow_trace_base: str | None = None


def get_mlflow_trace_base_url() -> str | None:
    """Return the MLflow trace base URL (without a specific trace ID).

    Includes ``?o=<workspace_id>`` on Azure only; see
    :mod:`backend.services.workspace_links`.
    """
    global _mlflow_trace_base
    try:
        if _mlflow_trace_base is None:
            # Prefer the configured ID. Resolving by name returns None whenever the
            # bundle prefixed the experiment name (development mode), which
            # silently dropped the trace deep-link from every response.
            experiment_id = config.mlflow_experiment_id
            if not experiment_id:
                experiment = mlflow.get_experiment_by_name(config.mlflow_experiment_name)
                if not experiment:
                    return None
                experiment_id = experiment.experiment_id
            _w, host = _get_ws()
            _mlflow_trace_base = workspace_url(
                host, f"ml/experiments/{experiment_id}/traces"
            )
        return _mlflow_trace_base
    except Exception:
        logger.warning("Could not build MLflow trace base URL", exc_info=True)
        return None


def _get_mlflow_trace_url() -> str | None:
    """Build a Databricks MLflow trace deep-link from the active trace."""
    try:
        trace_id = mlflow.get_active_trace_id()
        if not trace_id:
            return None
        base = get_mlflow_trace_base_url()
        if not base:
            return None
        separator = "&" if "?" in base else "?"
        return f"{base}{separator}selectedEvaluationId={trace_id}"
    except Exception:
        return None


def _tag(val: str, max_len: int = 250) -> str:
    """Truncate a tag value to fit the 255-byte MLflow limit."""
    return val[:max_len] if val else ""


def _set_trace_metadata(response: AskResponse, user_id: str, final_state: dict):
    """Attach rich metadata tags to the current MLflow trace.

    Tags have a 255-byte limit — longer values like SQL or sub_results are
    stored as span attributes instead (no size limit).

    ``user_id`` must be the caller's identity, not the LangGraph thread_id. The
    two entry points used to disagree: the batch path passed thread_id
    (``session_id or user_id``), so the user_id tag held a session UUID for any
    session-based query. That made the tag unusable for attributing a trace to a
    person -- which feedback authorization depends on.
    """
    try:
        genie_conversation_id = ""
        genie_message_id = ""
        sub_results_json = ""
        sub_results = final_state.get("sub_results")
        if sub_results and len(sub_results) >= 1:
            sub_results_json = json.dumps(sub_results, default=str)
            first = sub_results[0] if isinstance(sub_results, list) else None
            if first:
                genie_conversation_id = first.get("conversation_id") or ""
                genie_message_id = first.get("message_id") or ""

        # Build a lightweight version of sub_results for span storage.
        # The full version (with data/columns) can be 10-50KB+ which causes
        # silent retrieval failures. The cache pipeline only needs the fields
        # below for promotion.
        sub_results_lean = ""
        if sub_results and isinstance(sub_results, list):
            lean = [{
                "space_id": r.get("space_id"),
                "space_title": r.get("space_title"),
                "sub_question": r.get("sub_question"),
                "sql": r.get("sql"),
                "description": r.get("description"),
                "conversation_id": r.get("conversation_id"),
                "message_id": r.get("message_id"),
                "cache_hit": r.get("cache_hit", False),
                "row_count": r.get("row_count"),
            } for r in sub_results]
            sub_results_lean = json.dumps(lean, default=str)

        mlflow.update_current_trace(
            tags={
                "intent": response.intent or "unknown",
                "cache_status": response.cache_status.value,
                "pipeline": "langgraph",
                "user_id": _tag(user_id),
                "session_id": _tag(response.session_id or ""),
                "question": _tag(response.question or ""),
                "rewritten_question": _tag(response.rewritten_question or ""),
                "sql": _tag(response.sql or ""),
                "similarity_score": str(response.similarity_score or ""),
                "genie_latency_ms": str(response.genie_latency_ms or ""),
                "genie_space_id": response.selected_space_id or "",
                "genie_conversation_id": genie_conversation_id,
                "genie_message_id": genie_message_id,
                "sub_results": _tag(sub_results_lean or sub_results_json),
            },
        )
        span = mlflow.get_current_active_span()
        if span:
            span.set_attributes({
                "latency_ms": response.latency_ms,
                "cache_hit": response.cache_status == CacheStatus.HIT,
                "genie_latency_ms": response.genie_latency_ms or 0,
                "similarity_score": response.similarity_score or 0,
                "sql_full": response.sql or "",
                "question_full": response.question or "",
                "sub_results_full": sub_results_lean or sub_results_json,
            })
    except Exception:
        pass


@mlflow.trace(name="genie_pipeline", span_type=SpanType.CHAIN)
async def run_pipeline(question: str, session_id: Optional[str], user_id: str) -> tuple[AskResponse, list[dict]]:
    """Run the LangGraph pipeline (batch mode) and return (AskResponse, sse_events).

    Uses ainvoke -- all events are collected in state and returned at the end.
    For real-time streaming, use run_pipeline_stream() instead.
    Decorated with @mlflow.trace so the full invocation appears in the Traces UI.

    The caller's identity is read from the ambient auth context (bound by the
    router via auth_context.use), so Genie and cached-SQL execution run as that
    user and Unity Catalog grants apply per user. It is not a parameter because
    @mlflow.trace records arguments.
    """
    thread_id = session_id or user_id
    invoke_config = {"configurable": {"thread_id": thread_id}}

    initial_state: PipelineState = {
        "question": question,
        "session_id": session_id,
        "user_id": user_id,
        "start_time": time.time(),
        "events": [],
        # Reset all output fields so stale checkpointed values never bleed through
        # bypass_cache MUST be reset here. The checkpointer persists state per
        # thread, so an A/B comparison (which sets it True) would otherwise leave
        # the cache permanently bypassed for that user's thread.
        "bypass_cache": False,
        "sql": None,
        "description": None,
        "exec_columns": None,
        "exec_data": None,
        "exec_row_count": None,
        "cache_status": CacheStatus.MISS.value,
        "cache_hit": False,
        "answer_morph": False,
        "cache_result": None,
        "similarity_score": None,
        "latency_ms": 0,
        "genie_latency_ms": None,
        "genie_steps": None,
        "follow_up_questions": None,
        "conversation_history": None,
        "fast_path_result": None,
        "echo_match": None,
        "memory_context": None,
        "selected_space_id": None,
        "sub_results": None,
        "supervisor_plan": [],
        "trace_id": "",
        "error": None,
        # Supervisor loop state
        "current_step": -1,
        "current_space_id": None,
        "current_task": None,
        "completed_results": [],
        "space_call_counts": {},
    }

    async with _request_pipeline_context() as graph:
        final_state = await graph.ainvoke(initial_state, config=invoke_config)

    # Use the MLflow trace ID as the app-level trace ID
    mlflow_trace_id = mlflow.get_active_trace_id()
    if mlflow_trace_id:
        final_state["trace_id"] = mlflow_trace_id

    response = _build_response(question, final_state)
    response.mlflow_trace_url = _get_mlflow_trace_url()
    _set_trace_metadata(response, user_id, final_state)

    # Fire-and-forget: generate session title if not yet set
    resolved_sid = final_state.get("resolved_session_id", "")
    if resolved_sid:
        spawn_background(
            _generate_session_title(resolved_sid, question, response.description),
            name="generate_session_title",
        )

    return response, final_state.get("events", [])


def _stream_output_reducer(chunks: list) -> dict:
    """Reduce streamed (event_type, event_data) tuples to just the final response."""
    for event_type, event_data in reversed(chunks):
        if event_type == "complete":
            return event_data
    return {"events": len(chunks)}


@mlflow.trace(name="genie_pipeline_stream", span_type=SpanType.CHAIN, output_reducer=_stream_output_reducer)
async def run_pipeline_stream(question: str, session_id: Optional[str], user_id: str,
                              bypass_cache: bool = False):
    """Run the LangGraph pipeline with true streaming via astream.

    Yields (event_type, event_data) tuples in real time as each node
    completes, rather than batching all events to the end.
    The final yield is ("complete", AskResponse.model_dump()).

    Decorated with @mlflow.trace (async generator support >= 2.20.2).
    The output_reducer captures only the final response for the trace output.
    """
    thread_id = session_id or user_id
    invoke_config = {"configurable": {"thread_id": thread_id}}

    initial_state: PipelineState = {
        "question": question,
        "session_id": session_id,
        "user_id": user_id,
        "start_time": time.time(),
        "events": [],
        "bypass_cache": bypass_cache,
        # Reset all output fields so stale checkpointed values never bleed through
        "sql": None,
        "description": None,
        "exec_columns": None,
        "exec_data": None,
        "exec_row_count": None,
        "cache_status": CacheStatus.MISS.value,
        "cache_hit": False,
        "answer_morph": False,
        "cache_result": None,
        "similarity_score": None,
        "latency_ms": 0,
        "genie_latency_ms": None,
        "genie_steps": None,
        "follow_up_questions": None,
        "conversation_history": None,
        "fast_path_result": None,
        "echo_match": None,
        "memory_context": None,
        "selected_space_id": None,
        "sub_results": None,
        "supervisor_plan": [],
        "trace_id": "",
        "error": None,
        # Supervisor loop state
        "current_step": -1,
        "current_space_id": None,
        "current_task": None,
        "completed_results": [],
        "space_call_counts": {},
    }

    emitted_count = 0
    final_state = initial_state

    try:
        async with _request_pipeline_context() as graph:
            async for chunk in graph.astream(initial_state, config=invoke_config):
                for node_name, state_update in chunk.items():
                    if isinstance(state_update, dict):
                        final_state = {**final_state, **state_update}

                        events = final_state.get("events", [])
                        while emitted_count < len(events):
                            evt = events[emitted_count]
                            yield evt["event"], evt["data"]
                            emitted_count += 1

        # Use the MLflow trace ID as the app-level trace ID
        mlflow_trace_id = mlflow.get_active_trace_id()
        if mlflow_trace_id:
            final_state["trace_id"] = mlflow_trace_id

        response = _build_response(question, final_state)
        response.mlflow_trace_url = _get_mlflow_trace_url()

        # Set enriched trace metadata before yielding final event
        _set_trace_metadata(response, user_id, final_state)

        # Fire-and-forget: generate session title if not yet set
        resolved_sid = final_state.get("resolved_session_id", "")
        if resolved_sid:
            spawn_background(
                _generate_session_title(resolved_sid, question, response.description),
                name="generate_session_title",
            )

        yield "complete", response.model_dump()

    except Exception as e:
        logger.error(f"Pipeline stream error: {e}", exc_info=True)
        yield "error", {"message": str(e)}
