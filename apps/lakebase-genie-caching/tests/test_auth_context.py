"""Tests for caller identity and on-behalf-of execution.

These cover the permission boundary. The cache itself is shared across users on
purpose -- a question one person asks should speed up the same question for
everyone -- so access control lives at execution time: cached SQL runs as the
caller, and Unity Catalog decides who can see the data.
"""

import pytest

from backend.services import auth_context
from backend.services.auth_context import AuthContext, USER_TOKEN_HEADER


class _Headers:
    """Minimal case-insensitive stand-in for Starlette's request.headers."""

    def __init__(self, mapping: dict):
        self._data = {k.lower(): v for k, v in mapping.items()}

    def get(self, key, default=None):
        return self._data.get(key.lower(), default)


# ── Identity extraction ──


def test_from_headers_reads_forwarded_identity_and_token():
    auth = auth_context.from_headers(
        _Headers({
            USER_TOKEN_HEADER: "token-abc",
            "x-forwarded-email": "alice@example.com",
            "x-forwarded-preferred-username": "alice",
        })
    )

    assert auth.user_id == "alice@example.com"
    assert auth.email == "alice@example.com"
    assert auth.user_token == "token-abc"
    assert auth.can_query_as_user


def test_from_headers_without_token_cannot_query_as_user():
    """Local dev / user-auth-disabled: identity known, but no OBO credential."""
    auth = auth_context.from_headers(_Headers({"x-forwarded-email": "bob@example.com"}))

    assert auth.user_id == "bob@example.com"
    assert auth.user_token is None
    assert not auth.can_query_as_user


def test_from_headers_falls_back_to_supplied_user_id():
    auth = auth_context.from_headers(_Headers({}), fallback_user_id="body-supplied")

    assert auth.user_id == "body-supplied"
    # A body-supplied ID never grants query rights.
    assert not auth.can_query_as_user


# ── Token must not leak ──


def test_repr_never_contains_the_token():
    """A traceback or debug log must not expose the bearer credential."""
    auth = AuthContext(user_id="alice@example.com", user_token="super-secret-token")

    assert "super-secret-token" not in repr(auth)
    assert "super-secret-token" not in str(auth)
    assert "has_user_token=True" in repr(auth)


def test_dataclass_fields_exclude_token_from_repr():
    auth = AuthContext(user_id="a", user_token="t")
    assert AuthContext.__dataclass_fields__["user_token"].repr is False
    assert "t'" not in repr(auth)


# ── Ambient context ──


def test_current_defaults_to_unprivileged_context():
    auth = auth_context.current()
    assert not auth.can_query_as_user


def test_use_binds_and_restores_the_caller():
    alice = AuthContext(user_id="alice@example.com", user_token="tok")

    with auth_context.use(alice):
        assert auth_context.current() is alice

    assert not auth_context.current().can_query_as_user


def test_use_restores_on_exception():
    alice = AuthContext(user_id="alice@example.com", user_token="tok")

    with pytest.raises(RuntimeError):
        with auth_context.use(alice):
            raise RuntimeError("boom")

    assert not auth_context.current().can_query_as_user


def test_nested_use_isolates_identities():
    alice = AuthContext(user_id="alice@example.com", user_token="a")
    bob = AuthContext(user_id="bob@example.com", user_token="b")

    with auth_context.use(alice):
        with auth_context.use(bob):
            assert auth_context.current().user_id == "bob@example.com"
        assert auth_context.current().user_id == "alice@example.com"


@pytest.mark.asyncio
async def test_context_visible_inside_asyncio_to_thread():
    """Pipeline nodes offload blocking SDK calls; the caller must survive that."""
    import asyncio

    alice = AuthContext(user_id="alice@example.com", user_token="tok")

    with auth_context.use(alice):
        seen = await asyncio.to_thread(lambda: auth_context.current().user_id)

    assert seen == "alice@example.com"


# ── Cached SQL identity ──


@pytest.mark.asyncio
async def test_cached_sql_falls_back_to_service_principal_by_default():
    """Without a caller token, cached SQL runs as the app service principal.

    This keeps the cache working when user authorization is not enabled -- it is an
    admin-gated Public Preview, and a cache that silently never serves looks like a
    broken feature rather than a missing setting. The cache stores SQL only and
    re-executes on every hit, so results are still produced by the warehouse rather
    than replayed from storage.

    Set REQUIRE_USER_AUTH=true to refuse this fallback; see the test below.
    """
    from unittest.mock import MagicMock, patch

    from backend.config import config
    from backend.services.genie_client import execute_cached_sql

    assert config.require_user_auth is False, "must default to permissive"

    from databricks.sdk.service.sql import StatementState

    fake = MagicMock()
    response = MagicMock()
    response.status.state = StatementState.SUCCEEDED
    response.manifest = None
    response.result = None
    fake.statement_execution.execute_statement.return_value = response

    with patch("backend.services.genie_client.WorkspaceClient", return_value=fake):
        columns, data, row_count = await execute_cached_sql("SELECT 1", auth=None)

    assert row_count == 0
    # The service principal client was used, and the SQL was executed rather than
    # results being replayed from storage.
    fake.statement_execution.execute_statement.assert_called_once()


@pytest.mark.asyncio
async def test_cached_sql_refuses_sp_fallback_when_user_auth_required(monkeypatch):
    """REQUIRE_USER_AUTH=true is the setting for data with per-user access."""
    from backend.config import config
    from backend.services.genie_client import execute_cached_sql

    monkeypatch.setattr(config, "require_user_auth", True)

    with pytest.raises(PermissionError, match="REQUIRE_USER_AUTH"):
        await execute_cached_sql("SELECT 1", auth=None)

    with pytest.raises(PermissionError):
        await execute_cached_sql("SELECT 1", auth=AuthContext(user_id="alice@example.com"))


# ── The cache stores SQL only ──


@pytest.mark.asyncio
async def test_tier2_without_a_template_falls_through_to_genie():
    """There is no path that returns an answer without re-executing SQL.

    Tier 2 text morph used to replay a stored natural-language answer, which meant
    Unity Catalog never adjudicated the underlying data. That feature and its
    storage are removed: the cache holds SQL only, so a Tier 2 candidate with no
    parameterized template has nothing to adapt and goes to Genie.
    """
    from unittest.mock import AsyncMock, patch

    from backend.services.graph import node_answer_morph

    state = {
        "question": "What is revenue by region?",
        "current_task": "What is revenue by region?",
        "current_space_id": "space-1",
        "start_time": 0.0,
        "events": [],
        "cache_result": {
            "entry_id": "e-1",
            "cached_question": "Which region had the most revenue?",
            "cached_sql": "SELECT region, SUM(amount) FROM sales GROUP BY region",
            "parameterized_sql": None,
            "parameters": None,
            "similarity": 0.82,
        },
    }

    with patch(
        "backend.services.graph._try_sql_adaptation",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await node_answer_morph(state)

    assert result["cache_hit"] is False
    assert result["cache_status"] == "miss"


def test_cache_entry_has_no_answer_or_result_field():
    """The model must not carry fields for storing answers."""
    from backend.models import CacheEntry

    fields = set(CacheEntry.model_fields)
    assert "cached_answer" not in fields
    assert "result" not in fields
