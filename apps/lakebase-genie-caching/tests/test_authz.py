"""Tests for endpoint authorization.

Covers the two rules in backend/services/authz.py: user-scoped endpoints reject
callers who are not that user, and global/destructive endpoints require a
workspace admin.
"""

import pytest
from fastapi import HTTPException

from backend.services import authz
from backend.services.auth_context import USER_TOKEN_HEADER, AuthContext


class _Request:
    """Minimal stand-in for a Starlette Request carrying proxy headers."""

    def __init__(self, headers: dict | None = None):
        data = {k.lower(): v for k, v in (headers or {}).items()}
        self.headers = _Headers(data)


class _Headers:
    def __init__(self, data: dict):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key.lower(), default)


def _user_request(email: str, token: str = "tok") -> _Request:
    return _Request({"x-forwarded-email": email, USER_TOKEN_HEADER: token})


@pytest.fixture(autouse=True)
def _deployed_and_clean(monkeypatch):
    """Run each test as if deployed, with a clean admin cache.

    Deployment is detected via DATABRICKS_CLIENT_ID; without it the checks
    intentionally relax for local development.
    """
    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "test-sp-client-id")
    authz._admin_cache.clear()
    yield
    authz._admin_cache.clear()


def _no_admins(monkeypatch):
    monkeypatch.setattr(authz, "_lookup_admin", lambda auth: False)


def _all_admins(monkeypatch):
    monkeypatch.setattr(authz, "_lookup_admin", lambda auth: True)


# ── require_self ──


def test_require_self_allows_the_owner(monkeypatch):
    _no_admins(monkeypatch)
    auth = authz.require_self(_user_request("alice@example.com"), "alice@example.com")
    assert auth.email == "alice@example.com"


def test_require_self_is_case_insensitive(monkeypatch):
    _no_admins(monkeypatch)
    authz.require_self(_user_request("Alice@Example.com"), "alice@example.com")


def test_require_self_rejects_a_different_user(monkeypatch):
    """The core fix: changing the URL must not expose another user's data."""
    _no_admins(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        authz.require_self(_user_request("bob@example.com"), "alice@example.com")

    assert exc.value.status_code == 403


def test_require_self_allows_an_admin_acting_for_another_user(monkeypatch):
    _all_admins(monkeypatch)
    authz.require_self(_user_request("admin@example.com"), "alice@example.com")


def test_require_self_rejects_missing_identity_when_deployed(monkeypatch):
    _no_admins(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        authz.require_self(_Request({}), "alice@example.com")

    assert exc.value.status_code == 403


def test_require_self_relaxes_when_not_deployed(monkeypatch):
    """Local dev has no proxy headers; the app must still be usable."""
    monkeypatch.delenv("DATABRICKS_CLIENT_ID", raising=False)
    _no_admins(monkeypatch)

    auth = authz.require_self(_Request({}), "alice@example.com")
    assert auth is not None


# ── require_admin ──


def test_require_admin_allows_an_admin(monkeypatch):
    _all_admins(monkeypatch)
    authz.require_admin(_user_request("admin@example.com"))


def test_require_admin_rejects_a_normal_user(monkeypatch):
    _no_admins(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        authz.require_admin(_user_request("alice@example.com"))

    assert exc.value.status_code == 403


def test_require_admin_rejects_anonymous_when_deployed(monkeypatch):
    _no_admins(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        authz.require_admin(_Request({}))

    assert exc.value.status_code == 403


# ── Admin lookup semantics ──


def test_admin_lookup_denies_without_a_caller_token():
    """Group membership can't be established without OBO, so deny rather than assume."""
    tokenless = AuthContext(user_id="alice@example.com", email="alice@example.com")
    assert authz._lookup_admin(tokenless) is False


def test_admin_lookup_uses_the_caller_not_the_service_principal(monkeypatch):
    """A bare WorkspaceClient() would return the SP's groups, not the caller's."""
    used = {}

    class _Me:
        groups = [type("G", (), {"display": "admins"})()]

    class _Client:
        current_user = type("CU", (), {"me": staticmethod(lambda: _Me())})()

    def _client_for(self):
        used["token"] = self.user_token
        return _Client()

    monkeypatch.setattr(AuthContext, "workspace_client", _client_for)

    auth = AuthContext(
        user_id="admin@example.com", email="admin@example.com", user_token="caller-token"
    )
    assert authz._lookup_admin(auth) is True
    assert used["token"] == "caller-token"


def test_admin_result_is_cached_per_identity(monkeypatch):
    calls = []

    def _counting(auth):
        calls.append(auth.email)
        return False

    monkeypatch.setattr(authz, "_lookup_admin", _counting)

    auth = AuthContext(user_id="a@example.com", email="a@example.com", user_token="t")
    authz.is_admin(auth)
    authz.is_admin(auth)

    assert len(calls) == 1


def test_admin_cache_revalidates_on_new_token(monkeypatch):
    """A re-issued token must not reuse the previous decision blindly."""
    calls = []
    monkeypatch.setattr(authz, "_lookup_admin", lambda auth: calls.append(1) or False)

    authz.is_admin(AuthContext(user_id="a@example.com", email="a@example.com", user_token="t1"))
    authz.is_admin(AuthContext(user_id="a@example.com", email="a@example.com", user_token="t2"))

    assert len(calls) == 2


def test_admin_lookup_failure_denies(monkeypatch):
    """A SCIM error must not fail open into admin access."""

    def _boom(self):
        raise RuntimeError("SCIM unavailable")

    monkeypatch.setattr(AuthContext, "workspace_client", _boom)

    auth = AuthContext(user_id="a@example.com", email="a@example.com", user_token="t")
    assert authz._lookup_admin(auth) is False
