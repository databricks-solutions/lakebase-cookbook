"""End-to-end checks that the gated endpoints actually reject bad callers.

test_authz.py covers the authz helpers in isolation. These tests drive the real
FastAPI routers through TestClient, so a route that forgets to call
require_self / require_admin fails here even if the helpers are correct.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services import authz
from backend.services.auth_context import USER_TOKEN_HEADER

ALICE = {"x-forwarded-email": "alice@example.com", USER_TOKEN_HEADER: "alice-token"}
BOB = {"x-forwarded-email": "bob@example.com", USER_TOKEN_HEADER: "bob-token"}


@pytest.fixture
def client(monkeypatch):
    """App with the memory/cache/pipeline routers mounted, as if deployed."""
    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "test-sp")
    authz._admin_cache.clear()
    # Nobody is an admin unless a test says otherwise.
    monkeypatch.setattr(authz, "_lookup_admin", lambda auth: False)

    from backend.routers import cache, memory, pipelines

    app = FastAPI()
    app.include_router(memory.router)
    app.include_router(cache.router)
    app.include_router(pipelines.router)
    return TestClient(app)


# ── Cross-user access on memory/session endpoints ──


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/memory/sessions/alice@example.com"),
        ("GET", "/api/memory/sessions/alice@example.com/sess-1"),
        ("DELETE", "/api/memory/sessions/alice@example.com"),
        ("DELETE", "/api/memory/sessions/alice@example.com/sess-1"),
        ("GET", "/api/memory/entries/alice@example.com"),
        ("DELETE", "/api/memory/entries/alice@example.com"),
        ("DELETE", "/api/memory/entries/alice@example.com/entry-1"),
        ("POST", "/api/memory/entries/alice@example.com/entry-1/restore"),
        ("POST", "/api/pipelines/memory/alice@example.com"),
    ],
)
def test_bob_cannot_touch_alices_data(client, method, path):
    """Bob authenticates as himself but targets Alice in the URL."""
    response = client.request(method, path, headers=BOB)
    assert response.status_code == 403, (
        f"{method} {path} allowed a cross-user request: {response.status_code}"
    )


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/memory/sessions/alice@example.com"),
        ("GET", "/api/memory/entries/alice@example.com"),
        ("DELETE", "/api/memory/entries/alice@example.com"),
    ],
)
def test_anonymous_is_rejected_when_deployed(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 403


# ── Admin-only operations ──


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("DELETE", "/api/cache/entries/entry-1", None),
        ("DELETE", "/api/cache/entries", None),
        ("PUT", "/api/cache/threshold", {"threshold": 0.9}),
        ("PUT", "/api/cache/entries/entry-1/pin", {"pinned": True}),
        ("POST", "/api/cache/evict", None),
        ("POST", "/api/pipelines/cache", None),
        ("POST", "/api/pipelines/eviction", None),
        (
            "POST",
            "/api/cache/faq",
            {"question": "q", "sql": "SELECT 1", "genie_space_id": "space-1"},
        ),
    ],
)
def test_non_admin_cannot_run_global_operations(client, method, path, body):
    response = client.request(method, path, headers=ALICE, json=body)
    assert response.status_code == 403, (
        f"{method} {path} allowed a non-admin: {response.status_code}"
    )


# ── Threshold validation ──


@pytest.mark.parametrize("bad", [0, -0.5, 1.5, 0.1])
def test_threshold_rejects_unsafe_values(client, monkeypatch, bad):
    """A threshold at or near 0 would make every query a cache 'hit'."""
    monkeypatch.setattr(authz, "_lookup_admin", lambda auth: True)
    authz._admin_cache.clear()

    response = client.put("/api/cache/threshold", headers=ALICE, json={"threshold": bad})
    assert response.status_code == 422


def test_evict_rejects_zero_max_age(client, monkeypatch):
    """max_age_days=0 would delete the whole cache."""
    monkeypatch.setattr(authz, "_lookup_admin", lambda auth: True)
    authz._admin_cache.clear()

    response = client.post("/api/cache/evict?max_age_days=0", headers=ALICE)
    assert response.status_code == 422


# ── Feedback must belong to the caller ──


@pytest.fixture
def feedback_client(monkeypatch):
    """App with only the feedback router mounted, as if deployed."""
    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "test-sp")
    authz._admin_cache.clear()
    monkeypatch.setattr(authz, "_lookup_admin", lambda auth: False)

    from backend.routers import feedback

    app = FastAPI()
    app.include_router(feedback.router)
    return TestClient(app)


def _mock_trace_owner(monkeypatch, owner):
    from unittest.mock import AsyncMock

    from backend.routers import feedback

    monkeypatch.setattr(
        feedback.trace_store, "get_owner", AsyncMock(return_value=owner)
    )
    # Don't let the background MLflow write run during the test.
    monkeypatch.setattr(feedback, "spawn_background", lambda coro, name: coro.close())


def test_owner_can_rate_their_own_trace(feedback_client, monkeypatch):
    _mock_trace_owner(monkeypatch, "alice@example.com")

    response = feedback_client.post(
        "/api/feedback", headers=ALICE, json={"trace_id": "tr-1", "rating": 1}
    )

    assert response.status_code == 200


def test_bob_cannot_rate_alices_trace(feedback_client, monkeypatch):
    """A thumbs-up promotes a question into the SHARED cache.

    Without this check, any caller holding a trace_id could seed cache entries on
    another user's behalf, or suppress one with a thumbs-down.
    """
    _mock_trace_owner(monkeypatch, "alice@example.com")

    response = feedback_client.post(
        "/api/feedback", headers=BOB, json={"trace_id": "tr-1", "rating": 1}
    )

    assert response.status_code == 403


def test_admin_can_rate_another_users_trace(feedback_client, monkeypatch):
    _mock_trace_owner(monkeypatch, "alice@example.com")
    monkeypatch.setattr(authz, "_lookup_admin", lambda auth: True)
    authz._admin_cache.clear()

    response = feedback_client.post(
        "/api/feedback", headers=BOB, json={"trace_id": "tr-1", "rating": 1}
    )

    assert response.status_code == 200


def test_anonymous_cannot_submit_feedback_when_deployed(feedback_client, monkeypatch):
    _mock_trace_owner(monkeypatch, "alice@example.com")

    response = feedback_client.post("/api/feedback", json={"trace_id": "tr-1", "rating": 1})

    assert response.status_code == 403


def test_unresolvable_trace_is_accepted_because_upload_is_async(
    feedback_client, monkeypatch
):
    """A not-yet-uploaded trace must not 404 the user's thumbs-up.

    MLflow uploads traces asynchronously, 30-120s after the query completes, which
    is why the background tag write retries. A user clicking thumbs-up promptly --
    the normal case -- arrives before the trace is readable. Rejecting that broke
    the primary user action, observed live as an immediate 404 that became a 200
    twenty seconds later.

    Accepting is safe: the background write only succeeds if the trace really
    appears, so an unresolvable trace_id records no rating either way.
    """
    _mock_trace_owner(monkeypatch, None)

    response = feedback_client.post(
        "/api/feedback", headers=ALICE, json={"trace_id": "tr-not-yet-uploaded", "rating": 1}
    )

    assert response.status_code == 200


def test_cross_user_rating_is_still_rejected_once_the_trace_is_readable(
    feedback_client, monkeypatch
):
    """The relaxation above must not weaken the check it exists alongside."""
    _mock_trace_owner(monkeypatch, "alice@example.com")

    response = feedback_client.post(
        "/api/feedback", headers=BOB, json={"trace_id": "tr-1", "rating": -1}
    )

    assert response.status_code == 403
