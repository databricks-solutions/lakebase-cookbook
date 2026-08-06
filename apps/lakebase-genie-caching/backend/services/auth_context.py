"""Caller identity and per-request Databricks clients (on-behalf-of).

Why this exists
---------------
A Databricks App runs as its own service principal (SP). If every query executes
as that SP, then *every* user of the app sees whatever the SP can see -- Unity
Catalog grants on the underlying tables stop being enforced per user.

For a semantic cache that matters more than for a plain query app. A cache hit
replays SQL that some *earlier, possibly better-privileged* user's question
produced. Executed as the app SP, user B would receive the results of user A's
cached query over a table B has no SELECT on.

The cache itself is deliberately **shared** across users: a question one person
asks should speed up the same question for everyone, and the cached SQL text is
not the sensitive asset. The boundary is on the **data**: anything that returns
rows to a caller executes as the **caller**, so Unity Catalog decides what they
see. Only genuinely shared background work (batch promotion, MLflow writes,
permission bootstrap) runs as the SP.

How OBO works
-------------
When user authorization is enabled on the app, the Databricks proxy forwards the
end user's OAuth token in the ``x-forwarded-access-token`` header, alongside
identity headers (``x-forwarded-email`` and friends). We read it per request and
build a short-lived ``WorkspaceClient`` from it.

This requires the app to declare the ``sql`` and ``dashboards.genie`` OAuth
scopes and have user authorization enabled (see README). If the header is absent,
``AuthContext.can_query_as_user`` is False and callers must refuse the
cache/Genie path rather than silently falling back to SP identity -- a silent
fallback is exactly the permission bypass this module exists to prevent.

Security note: the token is a bearer credential. It is never logged, never put in
an MLflow tag or span attribute, never written to Postgres, and never included in
an SSE event. ``AuthContext.__repr__`` is overridden so it cannot leak via an
exception traceback or a debug log line.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

# Header the Databricks Apps proxy uses to forward the end user's OAuth token.
USER_TOKEN_HEADER = "x-forwarded-access-token"

# Identity headers, in preference order.
EMAIL_HEADERS = ("x-forwarded-email",)
USERNAME_HEADERS = ("x-forwarded-preferred-username", "x-forwarded-user")


@dataclass
class AuthContext:
    """Who is asking, and the credential to act on their behalf.

    Construct via :func:`from_headers` (deployed) or :func:`service_principal`
    (background jobs and local development).
    """

    user_id: str = "unknown"
    email: Optional[str] = None
    display_name: Optional[str] = None
    # Bearer token. Excluded from repr; see __repr__ below.
    user_token: Optional[str] = field(default=None, repr=False)
    # True when this context intentionally represents the app SP rather than a
    # human -- batch jobs, startup bootstrap. Distinct from "user token missing".
    is_service_principal: bool = False

    @property
    def can_query_as_user(self) -> bool:
        """True when we hold a caller token and can honour their UC grants."""
        return bool(self.user_token)

    def workspace_client(self) -> Any:
        """A WorkspaceClient acting as this identity.

        Returns a caller-scoped client when a user token is present, otherwise
        the app SP's default client. Callers that return data to a user MUST
        check :attr:`can_query_as_user` first instead of relying on this
        fallback.
        """
        import os

        from databricks.sdk import WorkspaceClient

        if not self.user_token:
            return WorkspaceClient()

        # Pin auth to the caller's PAT explicitly. Inside a Databricks App the
        # runtime injects DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET for the
        # service principal; supplying a token as well makes the SDK see two
        # credentials and fail with "more than one authorization method
        # configured: oauth and pat". Setting auth_type="pat" and blanking the
        # OAuth pair for this client only resolves the ambiguity in favour of the
        # user, which is the whole point of on-behalf-of.
        host = os.environ.get("DATABRICKS_HOST") or ""
        if not host:
            from databricks.sdk.core import Config

            host = Config().host

        return WorkspaceClient(
            host=host,
            token=self.user_token,
            auth_type="pat",
            client_id=None,
            client_secret=None,
        )

    def __repr__(self) -> str:  # pragma: no cover - defensive, not logic
        """Never render the token, even in a traceback or debug log."""
        return (
            f"AuthContext(user_id={self.user_id!r}, "
            f"has_user_token={bool(self.user_token)}, "
            f"is_service_principal={self.is_service_principal})"
        )

    __str__ = __repr__


# ── Ambient per-request context ──
#
# The token deliberately travels in a contextvar rather than inside the
# LangGraph PipelineState. Two things serialise that state:
#   1. the Lakebase checkpointer, which writes it to Postgres, and
#   2. @mlflow.trace, which records function inputs as trace attributes.
# Either would persist a live bearer credential. A contextvar is visible to the
# whole async call tree (including asyncio.to_thread via copy_context) but is
# never part of any serialised payload.
_CURRENT: ContextVar[Optional[AuthContext]] = ContextVar("genie_cache_auth", default=None)


@contextmanager
def use(auth: Optional[AuthContext]) -> Iterator[Optional[AuthContext]]:
    """Bind ``auth`` as the current caller for the duration of the block."""
    token = _CURRENT.set(auth)
    try:
        yield auth
    finally:
        _CURRENT.reset(token)


def current() -> AuthContext:
    """Return the current caller, or an unauthenticated context.

    The fallback has no user token, so ``can_query_as_user`` is False and any
    data-returning path refuses rather than silently using SP privileges.
    """
    return _CURRENT.get() or AuthContext()


def from_headers(headers: Any, fallback_user_id: str = "unknown") -> AuthContext:
    """Build an :class:`AuthContext` from request headers.

    ``headers`` is anything with a case-insensitive ``.get()`` -- Starlette's
    ``request.headers`` qualifies.

    ``fallback_user_id`` covers local development, where the proxy headers are
    absent. It is only used for identity, never to grant query access: without
    the token, ``can_query_as_user`` stays False.
    """
    get = getattr(headers, "get", None)
    if get is None:
        return AuthContext(user_id=fallback_user_id)

    token = _first(get, (USER_TOKEN_HEADER,))
    email = _first(get, EMAIL_HEADERS)
    username = _first(get, USERNAME_HEADERS)

    return AuthContext(
        user_id=email or username or fallback_user_id,
        email=email,
        display_name=username or email,
        user_token=token,
    )


def service_principal(user_id: str = "system") -> AuthContext:
    """Context for shared background work that legitimately runs as the app SP.

    Use for batch promotion, eviction, MLflow writes, and startup bootstrap --
    never for answering a user's question.
    """
    return AuthContext(user_id=user_id, is_service_principal=True)


def _first(get, names: tuple[str, ...]) -> Optional[str]:
    for name in names:
        value = get(name)
        if value:
            return value.strip()
    return None
