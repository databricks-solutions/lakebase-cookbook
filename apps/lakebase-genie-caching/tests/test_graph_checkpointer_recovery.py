"""Tests for request-scoped graph checkpointer behavior."""

import pytest

import backend.services.graph as graph


@pytest.mark.asyncio
async def test_request_pipeline_context_uses_fresh_checkpointer(monkeypatch):
    class FakeContext:
        async def __aenter__(self):
            return "fresh-checkpointer"

        async def __aexit__(self, exc_type, exc, tb):
            return None

    built = []
    monkeypatch.setattr(
        "backend.services.checkpointer.lakebase_checkpointer_context",
        lambda: FakeContext(),
    )
    monkeypatch.setattr(graph, "build_pipeline_graph", lambda checkpointer=None: built.append(checkpointer) or "graph")

    async with graph._request_pipeline_context() as compiled_graph:
        assert compiled_graph == "graph"

    assert built == ["fresh-checkpointer"]


@pytest.mark.asyncio
async def test_request_pipeline_context_falls_back_without_checkpointer(monkeypatch):
    class FailingContext:
        async def __aenter__(self):
            raise RuntimeError("Lakebase unavailable")

        async def __aexit__(self, exc_type, exc, tb):
            return None

    built = []
    monkeypatch.setattr(
        "backend.services.checkpointer.lakebase_checkpointer_context",
        lambda: FailingContext(),
    )
    monkeypatch.setattr(graph, "build_pipeline_graph", lambda checkpointer=None: built.append(checkpointer) or "graph")

    async with graph._request_pipeline_context() as compiled_graph:
        assert compiled_graph == "graph"

    assert built == [None]
