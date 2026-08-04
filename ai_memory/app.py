"""Chainlit chat app demonstrating durable agent memory on Lakebase.

Two kinds of memory, one Lakebase database:

* **Short-term / history** — Chainlit's SQLAlchemy data layer persists every
  thread to Lakebase, giving the resumable-thread sidebar and cross-session
  history for free. The working context window for the LLM comes from
  ``cl.chat_context`` (the current thread's turns).
* **Long-term facts + recall** — a ``memories`` table with a pgvector embedding.
  Say ``remember: <fact>`` to store a durable fact; each turn recalls the most
  semantically-relevant facts and injects them into the system prompt.

The reusable pieces live in ``agent_memory/``.
"""

from __future__ import annotations

import chainlit as cl
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

from agent_memory import (
    Embedder,
    LakebaseCredentialProvider,
    MemoryStore,
    create_chainlit_data_layer,
    ensure_schema,
    load_settings,
    make_engine,
)

settings = load_settings()
_creds = LakebaseCredentialProvider(settings.lakebase_instance)
_engine = make_engine(settings, _creds)
_store = MemoryStore(_engine, Embedder(settings.embedding_endpoint), schema=settings.pg_schema)
_w = WorkspaceClient()

# Create/own the schema at startup (Chainlit data-layer tables + memories).
ensure_schema(_engine, settings.pg_schema, settings.embedding_dim)

CHAT_MODEL = "databricks-claude-sonnet-4-5"


@cl.data_layer
def get_data_layer():
    # Registering a data layer is what enables the thread sidebar + resume.
    return create_chainlit_data_layer(settings, _creds)


@cl.header_auth_callback
def header_auth(headers: dict) -> cl.User | None:
    """Databricks Apps forwards the signed-in user via headers. Chainlit only
    persists threads for an authenticated user, so map that header to a User."""
    email = headers.get("x-forwarded-email") or headers.get("x-forwarded-user")
    identifier = email or "local-dev-user"
    return cl.User(identifier=identifier, metadata={"provider": "databricks"})


@cl.on_message
async def on_message(message: cl.Message):
    user_id = _user_id()
    text = message.content.strip()

    # Explicit long-term memory: "remember: I prefer metric units"
    if text.lower().startswith("remember:"):
        fact = text.split(":", 1)[1].strip()
        _store.remember(user_id, fact)
        await cl.Message(content=f"Got it — I'll remember that: *{fact}*").send()
        return

    # Recall relevant long-term facts + this thread's short-term history.
    recalled = _store.recall(user_id, text, top_k=5)

    messages = [ChatMessage(role=ChatMessageRole.SYSTEM, content=_build_system_prompt(recalled))]
    messages += _history_messages()
    messages.append(ChatMessage(role=ChatMessageRole.USER, content=text))

    resp = _w.serving_endpoints.query(name=CHAT_MODEL, messages=messages)
    answer = resp.choices[0].message.content

    # Chainlit persists this turn to the data layer (thread history) on send.
    await cl.Message(content=answer).send()


def _history_messages() -> list[ChatMessage]:
    """The current thread's prior turns, from Chainlit's managed context."""
    out: list[ChatMessage] = []
    for m in cl.chat_context.to_openai():
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant") and isinstance(content, str):
            out.append(
                ChatMessage(
                    role=ChatMessageRole.ASSISTANT if role == "assistant" else ChatMessageRole.USER,
                    content=content,
                )
            )
    return out


def _build_system_prompt(recalled) -> str:
    base = "You are a helpful assistant with persistent memory of the user."
    if not recalled:
        return base
    facts = "\n".join(f"- {m.content}" for m in recalled)
    return f"{base}\n\nRelevant things you remember about this user:\n{facts}"


def _user_id() -> str:
    user = cl.context.session.user
    return getattr(user, "identifier", None) or "anonymous"
