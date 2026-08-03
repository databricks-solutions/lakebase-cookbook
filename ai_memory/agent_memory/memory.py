"""Three-layer agent memory on Lakebase Postgres.

* **Short-term** — ``add_turn`` / ``recent_turns``: raw conversation history for a
  (user, session), the working context window.
* **Long-term facts** — ``remember`` / ``list_memories``: durable facts about a
  user ("prefers metric units", "team = finance"), persisted across sessions.
* **Semantic recall** — ``recall``: pgvector cosine-similarity lookup that
  returns the memories most relevant to the current query, to inject into the
  prompt.

All three share one governed Postgres store. Embeddings come from a Databricks
Foundation Model endpoint (see ``embeddings.py``).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, text

from .embeddings import Embedder


@dataclass
class Memory:
    id: int
    content: str
    score: float | None = None


class MemoryStore:
    def __init__(self, engine: Engine, embedder: Embedder, schema: str = "public"):
        self._engine = engine
        self._embedder = embedder
        self._schema = schema

    # --- short-term: conversation history -----------------------------------

    def add_turn(self, user_id: str, session_id: str, role: str, content: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    f'INSERT INTO "{self._schema}".conversations '
                    "(user_id, session_id, role, content) "
                    "VALUES (:u, :s, :r, :c)"
                ),
                {"u": user_id, "s": session_id, "r": role, "c": content},
            )

    def recent_turns(self, user_id: str, session_id: str, limit: int = 10) -> list[Memory]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"SELECT id, role || ': ' || content AS content "
                    f'FROM "{self._schema}".conversations '
                    "WHERE user_id = :u AND session_id = :s "
                    "ORDER BY created_at DESC LIMIT :n"
                ),
                {"u": user_id, "s": session_id, "n": limit},
            ).fetchall()
        # Return in chronological order.
        return [Memory(id=r.id, content=r.content) for r in reversed(rows)]

    # --- long-term: durable facts --------------------------------------------

    def remember(self, user_id: str, content: str) -> int:
        """Persist a long-term fact with its embedding; returns the new row id."""
        embedding = self._embedder.embed(content)
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    f'INSERT INTO "{self._schema}".memories (user_id, content, embedding) '
                    "VALUES (:u, :c, :e) RETURNING id"
                ),
                {"u": user_id, "c": content, "e": _to_pgvector(embedding)},
            ).one()
        return int(row.id)

    def list_memories(self, user_id: str, limit: int = 50) -> list[Memory]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    f'SELECT id, content FROM "{self._schema}".memories '
                    "WHERE user_id = :u ORDER BY created_at DESC LIMIT :n"
                ),
                {"u": user_id, "n": limit},
            ).fetchall()
        return [Memory(id=r.id, content=r.content) for r in rows]

    # --- semantic recall: pgvector cosine similarity -------------------------

    def recall(self, user_id: str, query: str, top_k: int = 5) -> list[Memory]:
        """Return the user's memories most semantically similar to ``query``."""
        q_emb = self._embedder.embed(query)
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"SELECT id, content, 1 - (embedding <=> :q) AS score "
                    f'FROM "{self._schema}".memories '
                    "WHERE user_id = :u "
                    "ORDER BY embedding <=> :q LIMIT :k"
                ),
                {"u": user_id, "q": _to_pgvector(q_emb), "k": top_k},
            ).fetchall()
        return [Memory(id=r.id, content=r.content, score=float(r.score)) for r in rows]


def _to_pgvector(vec: list[float]) -> str:
    """Render a Python list as a pgvector literal, e.g. ``[0.1,0.2,0.3]``."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"
