"""Query rewriter: transforms multi-turn conversation into standalone question."""

import asyncio
import logging

import mlflow
from mlflow.entities import SpanType

from backend.config import config
from backend.models import Message

logger = logging.getLogger(__name__)

REWRITE_PROMPT = """You are a query rewriter for a data analytics system. Given a conversation history, the user's long-term memory/preferences, and the latest user message, rewrite the latest message into a self-contained standalone question that captures the full intent.

Rules:
- The rewritten question must be understandable without any conversation context
- Preserve specific entities, dates, numbers, and filters mentioned in the conversation
- If the user's current message CONTRADICTS a memory/preference, the current message ALWAYS wins
- Memories that ADD useful context without conflicting may be incorporated (e.g., preferred terminology, domain focus)
- If the latest message is already self-contained and memories are irrelevant or contradictory, return it as-is
- Return ONLY the rewritten question, nothing else

Conversation history:
{history}
{memory_section}
Latest user message: {question}

Rewritten standalone question:"""


@mlflow.trace(name="rewrite_query", span_type=SpanType.CHAIN)
async def rewrite_query(
    question: str,
    history: list[Message],
    memory_context: list[str] | None = None,
) -> str:
    """Rewrite a query using conversation history and user memory.

    Memory preferences are folded into the rewrite so the LLM can resolve
    conflicts (explicit user intent always overrides stored preferences).
    If history has <=1 messages and no memory, returns the question as-is.
    """
    has_history = len(history) > 1
    has_memory = bool(memory_context)
    if not has_history and not has_memory:
        return question

    history_text = "(No prior messages)" if not has_history else "\n".join(
        f"{msg.role.value}: {msg.content}" for msg in history[-10:]
    )

    memory_section = ""
    if has_memory:
        entries = "\n".join(f"- {m}" for m in memory_context)
        memory_section = f"\nUser's long-term memory/preferences:\n{entries}\n"

    prompt = REWRITE_PROMPT.format(
        history=history_text, question=question, memory_section=memory_section
    )

    def _call_llm():
        """Use raw HTTP with the fast model for low-latency rewriting."""
        import json
        import urllib.request

        from backend.services.graph import _get_ws
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
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()

    try:
        rewritten = await asyncio.to_thread(_call_llm)
        if rewritten and len(rewritten) > 5:
            logger.info(f"Query rewritten: '{question}' -> '{rewritten}'")
            return rewritten
    except Exception as e:
        logger.warning(f"Query rewrite failed, using original: {e}")

    return question
