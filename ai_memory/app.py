"""Chainlit chat app demonstrating durable agent memory on Lakebase.

On startup it ensures the memory schema exists (owned by the app service
principal). For each user message it:

1. recalls semantically-relevant long-term memories (pgvector),
2. loads recent conversation history (short-term),
3. answers with a Databricks Foundation Model, using both as context,
4. persists the new turn, and stores a durable fact when the user says
   "remember: <fact>".

This is a minimal reference — the reusable pieces are in ``src/ai_memory/``.
"""

from __future__ import annotations

import chainlit as cl
from databricks.sdk import WorkspaceClient

from agent_memory import (
    Embedder,
    LakebaseCredentialProvider,
    MemoryStore,
    ensure_schema,
    load_settings,
    make_engine,
)

settings = load_settings()
_creds = LakebaseCredentialProvider(settings.lakebase_instance)
_engine = make_engine(settings, _creds)
_schema = settings.pg_schema
_store = MemoryStore(_engine, Embedder(settings.embedding_endpoint), schema=_schema)
_w = WorkspaceClient()

# Create/own the memory schema at startup (idempotent).
ensure_schema(_engine, _schema, settings.embedding_dim)

CHAT_MODEL = "databricks-claude-sonnet-4-5"


@cl.on_chat_start
async def on_chat_start():
    cl.user_session.set("session_id", cl.context.session.id)


@cl.on_message
async def on_message(message: cl.Message):
    user_id = _user_id()
    session_id = cl.user_session.get("session_id")
    text = message.content.strip()

    # Explicit long-term memory: "remember: I prefer metric units"
    if text.lower().startswith("remember:"):
        fact = text.split(":", 1)[1].strip()
        _store.remember(user_id, fact)
        await cl.Message(content=f"Got it — I'll remember that: *{fact}*").send()
        _store.add_turn(user_id, session_id, "user", text)
        return

    # Recall relevant long-term memories + recent history for context.
    recalled = _store.recall(user_id, text, top_k=5)
    recent = _store.recent_turns(user_id, session_id, limit=10)

    system = _build_system_prompt(recalled)
    messages = [{"role": "system", "content": system}]
    messages += [{"role": _role(m), "content": _strip_role(m.content)} for m in recent]
    messages.append({"role": "user", "content": text})

    resp = _w.serving_endpoints.query(name=CHAT_MODEL, messages=messages)
    answer = resp.choices[0].message.content

    await cl.Message(content=answer).send()

    _store.add_turn(user_id, session_id, "user", text)
    _store.add_turn(user_id, session_id, "assistant", answer)


def _build_system_prompt(recalled) -> str:
    base = "You are a helpful assistant with persistent memory of the user."
    if not recalled:
        return base
    facts = "\n".join(f"- {m.content}" for m in recalled)
    return f"{base}\n\nRelevant things you remember about this user:\n{facts}"


def _user_id() -> str:
    user = cl.context.session.user
    return getattr(user, "identifier", None) or "anonymous"


def _role(m) -> str:
    return "assistant" if m.content.startswith("assistant:") else "user"


def _strip_role(content: str) -> str:
    return content.split(":", 1)[1].strip() if ":" in content else content
