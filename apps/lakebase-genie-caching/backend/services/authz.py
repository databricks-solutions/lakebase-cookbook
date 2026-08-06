"""Authorization dependencies for the API surface.

Several endpoints took a ``user_id`` path parameter and trusted it: any caller
could read or delete another user's sessions and memories by changing the URL.
Others triggered jobs or deleted cache entries with no identity check at all.

Two rules cover the whole surface:

* ``require_self`` -- an endpoint scoped to a ``user_id`` may only be called by
  that user (or a workspace admin).
* ``require_admin`` -- global or destructive operations (trigger a batch job,
  evict the cache, delete another user's entry, reset pipeline state) require a
  workspace admin.

Local development
-----------------
The Databricks Apps proxy always sets ``x-forwarded-email`` for an authenticated
user, so its absence means we are not running behind the proxy. Rather than
trusting a flag someone can forget to unset, deployment is detected from
``DATABRICKS_CLIENT_ID``, which the Apps runtime injects. Deployed means the
checks are enforced; running locally they are relaxed so the app is still
usable with ``scripts/start_app.py``.
"""

from __future__ import annotations

import logging
import os

from fastapi import HTTPException, Request

from backend.services import auth_context
from backend.services.auth_context import AuthContext

logger = logging.getLogger(__name__)

# Workspace group whose members are workspace admins.
ADMIN_GROUP = "admins"


def is_deployed() -> bool:
    """True when running as a Databricks App (credentials are auto-injected)."""
    return bool(os.environ.get("DATABRICKS_CLIENT_ID"))


def caller(request: Request) -> AuthContext:
    """FastAPI dependency returning the authenticated caller."""
    return auth_context.from_headers(request.headers)


def _identity_missing(auth: AuthContext) -> bool:
    """True when no proxy identity was forwarded for this request."""
    return not (auth.email or (auth.user_id and auth.user_id != "unknown"))


def _same_identity(auth: AuthContext, user_id: str) -> bool:
    """Compare a path user_id against the caller, tolerating email/username forms."""
    candidates = {
        value.strip().lower()
        for value in (auth.email, auth.user_id, auth.display_name)
        if value
    }
    return user_id.strip().lower() in candidates


def _lookup_admin(auth: AuthContext) -> bool:
    """Ask the workspace whether ``auth`` is an admin.

    Must run as the *caller*: ``current_user.me()`` on a service-principal client
    returns the SP's own groups, which would make every caller look like an admin
    (or none), depending on how the SP is configured.
    """
    if not auth.can_query_as_user:
        # Without a caller token we cannot establish group membership, and
        # assuming admin would be an escalation. Deny.
        return False
    try:
        me = auth.workspace_client().current_user.me()
        groups = {(g.display or "").lower() for g in (me.groups or [])}
        return ADMIN_GROUP in groups
    except Exception as e:
        logger.warning(
            "Admin check failed for %s (treating as non-admin): %s", auth.user_id, e
        )
        return False


# Memoised per (identity, token fingerprint). Admin membership rarely changes
# within a session and each check costs a SCIM round-trip. The raw token is never
# stored as a key -- only a short hash of it, so a re-issued token re-validates.
_admin_cache: dict[tuple[str, str], bool] = {}
_ADMIN_CACHE_MAX = 256


def is_admin(auth: AuthContext) -> bool:
    """Whether the caller is a workspace admin."""
    if not auth.email:
        return False

    import hashlib

    fingerprint = (
        hashlib.sha256(auth.user_token.encode()).hexdigest()[:16]
        if auth.user_token
        else "no-token"
    )
    key = (auth.email.lower(), fingerprint)

    if key not in _admin_cache:
        if len(_admin_cache) >= _ADMIN_CACHE_MAX:
            _admin_cache.clear()
        _admin_cache[key] = _lookup_admin(auth)
    return _admin_cache[key]


def require_self(request: Request, user_id: str) -> AuthContext:
    """Assert the caller owns ``user_id``. Admins may act on any user.

    Raises:
        HTTPException: 403 when the caller is someone else.
    """
    auth = caller(request)

    if _identity_missing(auth):
        if is_deployed():
            raise HTTPException(
                status_code=403,
                detail="No forwarded caller identity; cannot authorize this request.",
            )
        logger.warning(
            "Local development: skipping ownership check for user_id=%s. "
            "This check is enforced when deployed as a Databricks App.",
            user_id,
        )
        return auth

    if _same_identity(auth, user_id):
        return auth

    if is_admin(auth):
        logger.info("Admin %s acting on behalf of %s", auth.user_id, user_id)
        return auth

    raise HTTPException(
        status_code=403,
        detail="You may only access your own sessions and memories.",
    )


def require_admin(request: Request) -> AuthContext:
    """Assert the caller is a workspace admin.

    Used for global and destructive operations: triggering batch jobs, evicting
    the cache, deleting cache entries, and resetting pipeline state.

    Raises:
        HTTPException: 403 when the caller is not an admin.
    """
    auth = caller(request)

    if _identity_missing(auth):
        if is_deployed():
            raise HTTPException(
                status_code=403,
                detail="No forwarded caller identity; cannot authorize this request.",
            )
        logger.warning(
            "Local development: skipping admin check. Enforced when deployed."
        )
        return auth

    if is_admin(auth):
        return auth

    raise HTTPException(
        status_code=403,
        detail="This operation requires a Databricks workspace admin.",
    )
