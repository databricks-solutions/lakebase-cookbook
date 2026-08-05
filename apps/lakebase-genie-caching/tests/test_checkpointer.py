"""Tests for managed LangGraph checkpointer lifecycle."""

import pytest

from backend.services import checkpointer


class _FakeSaver:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.entered = False
        self.exited = False
        self.setup_called = False
        _FakeSaver.instances.append(self)

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.exited = True
        return None

    async def setup(self):
        self.setup_called = True


@pytest.fixture(autouse=True)
def _reset_fake_saver():
    _FakeSaver.instances.clear()
    yield
    _FakeSaver.instances.clear()


@pytest.mark.asyncio
async def test_lakebase_checkpointer_context_uses_autoscaling_project(monkeypatch):
    monkeypatch.setattr(checkpointer, "AsyncCheckpointSaver", _FakeSaver)
    monkeypatch.setattr(checkpointer.config.lakebase, "instance_name", "")
    monkeypatch.setattr(checkpointer.config.lakebase, "endpoint_name", "")
    monkeypatch.setattr(checkpointer.config.lakebase, "project_name", "lakebase-genie-caching")

    async with checkpointer.lakebase_checkpointer_context() as saver:
        assert saver is _FakeSaver.instances[0]
        assert saver.entered is True

    assert saver.exited is True
    assert saver.kwargs["instance_name"] is None
    assert saver.kwargs["project"] == "lakebase-genie-caching"
    assert saver.kwargs["branch"] == "production"


@pytest.mark.asyncio
async def test_lakebase_checkpointer_context_prefers_endpoint_override(monkeypatch):
    monkeypatch.setattr(checkpointer, "AsyncCheckpointSaver", _FakeSaver)
    monkeypatch.setattr(checkpointer.config.lakebase, "instance_name", "")
    monkeypatch.setattr(
        checkpointer.config.lakebase,
        "endpoint_name",
        "projects/custom/branches/production/endpoints/primary",
    )
    monkeypatch.setattr(checkpointer.config.lakebase, "project_name", "lakebase-genie-caching")

    async with checkpointer.lakebase_checkpointer_context() as saver:
        pass

    assert saver.kwargs["autoscaling_endpoint"] == "projects/custom/branches/production/endpoints/primary"
    assert saver.kwargs["project"] is None
    assert saver.kwargs["branch"] is None


@pytest.mark.asyncio
async def test_setup_checkpointer_runs_managed_setup(monkeypatch):
    monkeypatch.setattr(checkpointer, "AsyncCheckpointSaver", _FakeSaver)
    monkeypatch.setattr(checkpointer.config.lakebase, "instance_name", "legacy-instance")
    monkeypatch.setattr(checkpointer.config.lakebase, "endpoint_name", "")
    monkeypatch.setattr(checkpointer.config.lakebase, "project_name", "")

    await checkpointer.setup_checkpointer()

    assert len(_FakeSaver.instances) == 1
    assert _FakeSaver.instances[0].setup_called is True
    assert _FakeSaver.instances[0].exited is True


@pytest.mark.asyncio
async def test_close_checkpointer_is_compatibility_noop():
    assert await checkpointer.close_checkpointer() is None
