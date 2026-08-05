"""Database connection management for Lakebase with OAuth token refresh.

Uses psycopg3 with a connection pool for fast query execution.
Each execute_raw call borrows a connection from the pool instead of
opening a new TCP+SSL connection (~500-800ms savings per query).
"""

import asyncio
import logging
import os
import re
import threading
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from databricks.sdk import WorkspaceClient

from backend.config import config

logger = logging.getLogger(__name__)

_current_token: str | None = None
_username: str | None = None
_token_lock = threading.Lock()
_token_refresh_task: asyncio.Task | None = None
_pool: ConnectionPool | None = None
_initialized = False

TOKEN_REFRESH_INTERVAL = 50 * 60  # 50 minutes (before 1-hour expiry)


def _generate_token() -> str:
    """Generate a fresh OAuth token for Lakebase.

    Lakebase Autoscaling uses the Postgres API and requires credentials scoped
    to an endpoint resource path. Lakebase Provisioned uses the legacy database
    API and instance name.
    """
    w = WorkspaceClient()
    if config.lakebase.is_autoscaling:
        cred = w.postgres.generate_database_credential(
            endpoint=config.lakebase.resolved_endpoint_name,
        )
    else:
        cred = w.database.generate_database_credential(
            request_id=str(uuid.uuid4()),
            instance_names=[config.lakebase.instance_name],
        )
    return cred.token


def _get_username() -> str:
    """Get current Databricks username for Lakebase authentication."""
    if os.environ.get("PGUSER"):
        return os.environ["PGUSER"]
    if os.environ.get("DATABRICKS_CLIENT_ID"):
        return os.environ["DATABRICKS_CLIENT_ID"]
    w = WorkspaceClient()
    return w.current_user.me().user_name


def _make_conninfo() -> str:
    """Build a libpq connection string from config (which reads PG* env vars)."""
    lb = config.lakebase
    with _token_lock:
        token = _current_token
    return psycopg.conninfo.make_conninfo(
        host=lb.dns,
        port=lb.port,
        dbname=lb.database_name,
        user=os.environ.get("PGUSER", _username),
        password=token,
        sslmode=lb.sslmode,
        connect_timeout=60,
    )


def _get_connection() -> psycopg.Connection:
    """Create a new psycopg connection (used during init / fallback only)."""
    lb = config.lakebase
    with _token_lock:
        token = _current_token
    return psycopg.connect(
        host=lb.dns,
        port=lb.port,
        dbname=lb.database_name,
        user=os.environ.get("PGUSER", _username),
        password=token,
        sslmode=lb.sslmode,
        row_factory=dict_row, autocommit=True,
        connect_timeout=60,
    )


async def _refresh_lakebase_token_and_pools() -> None:
    """Refresh Lakebase OAuth token and recreate the app-owned DB pool."""
    global _current_token, _pool
    new_token = await asyncio.to_thread(_generate_token)
    with _token_lock:
        _current_token = new_token
    if _pool:
        old_pool = _pool
        _pool = _create_pool()
        try:
            old_pool.close(timeout=5)
        except Exception:
            pass
    logger.info("Lakebase OAuth token refreshed + pool recreated")


async def _token_refresh_loop():
    """Background task to refresh OAuth token and update pool credentials."""
    while True:
        await asyncio.sleep(TOKEN_REFRESH_INTERVAL)
        try:
            await _refresh_lakebase_token_and_pools()
        except Exception as e:
            logger.error(f"Failed to refresh Lakebase token: {e}")


def _check_connection(conn: psycopg.Connection) -> None:
    """Verify a pooled connection is healthy before reuse."""
    try:
        conn.execute("SELECT 1")
    except psycopg.OperationalError:
        raise
    except Exception:
        try:
            conn.cancel()
            conn.reset()
        except Exception:
            raise psycopg.OperationalError("connection unrecoverable")


def _create_pool() -> ConnectionPool:
    """Create a connection pool with current credentials."""
    conninfo = _make_conninfo()
    pool = ConnectionPool(
        conninfo=conninfo,
        min_size=1,
        max_size=10,
        timeout=60,
        kwargs={"row_factory": dict_row, "autocommit": True},
        check=_check_connection,
        open=True,
    )
    return pool


def db_available() -> bool:
    """Return True if the database pool is initialized and usable."""
    return _initialized and _pool is not None


def _resolve_autoscaling_host() -> str:
    """Resolve the endpoint host from the Lakebase Autoscaling API."""
    w = WorkspaceClient()
    endpoint = w.postgres.get_endpoint(name=config.lakebase.resolved_endpoint_name)
    return endpoint.status.hosts.host


def _ensure_lakebase_host_configured(host: str, autoscaling: bool, endpoint: str) -> None:
    """Fail before libpq falls back to a local socket when Lakebase host is missing."""
    if host:
        return

    detail = (
        f"autoscaling={autoscaling}, endpoint={endpoint or '<unset>'}. "
        "Set LAKEBASE_PROJECT or ENDPOINT_NAME for Lakebase Autoscaling, "
        "or set PGHOST/DATABRICKS_LAKEBASE_INSTANCE for provisioned Lakebase."
    )
    raise RuntimeError(f"Lakebase host is not configured ({detail})")


def is_schema_ownership_error(exc: Exception) -> bool:
    """Return True for Postgres DDL errors caused by non-owner migrations."""
    message = str(exc).lower()
    return (
        "must be owner" in message
        or "insufficientprivilege" in message
        or "permission denied" in message and ("table" in message or "index" in message)
    )


async def init_db():
    """Initialize database credentials, connection pool, and start token refresh."""
    global _current_token, _username, _token_refresh_task, _pool, _initialized

    _username = await asyncio.to_thread(_get_username)
    logger.info(f"Lakebase username resolved: {_username}")

    if config.lakebase.is_autoscaling and not config.lakebase.dns:
        host = await asyncio.to_thread(_resolve_autoscaling_host)
        config.lakebase.dns = host
        logger.info(f"Lakebase Autoscaling endpoint resolved: {host}")
    elif not config.lakebase.dns:
        logger.info(
            "Using Databricks App PG* env vars: "
            f"host={os.environ.get('PGHOST', '')}, user={os.environ.get('PGUSER', '')}"
        )

    _ensure_lakebase_host_configured(
        config.lakebase.dns,
        config.lakebase.is_autoscaling,
        config.lakebase.resolved_endpoint_name,
    )

    logger.info(
        f"Lakebase connection: host={config.lakebase.dns}, "
        f"db={config.lakebase.database_name}, autoscaling={config.lakebase.is_autoscaling}"
    )

    _current_token = await asyncio.to_thread(_generate_token)
    logger.info("Lakebase OAuth token generated")

    pool = await asyncio.to_thread(_create_pool)

    def _test():
        with pool.connection() as conn:
            cur = conn.execute("SELECT 1 AS ok")
            return cur.fetchone()

    try:
        result = await asyncio.to_thread(_test)
        logger.info(f"Database connection verified: {result}")
    except Exception:
        try:
            pool.close(timeout=2)
        except Exception:
            pass
        raise

    _pool = pool
    _token_refresh_task = asyncio.create_task(_token_refresh_loop())
    _initialized = True
    logger.info(f"Database initialized with pool: {config.lakebase.dns}/{config.lakebase.database_name}")


def get_credentials() -> tuple[str, str]:
    """Return (username, current_token) for other modules that need DB access."""
    return _username, _current_token


async def close_db():
    """Shutdown token refresh task and close pool."""
    global _token_refresh_task, _pool
    if _token_refresh_task:
        _token_refresh_task.cancel()
    if _pool:
        try:
            _pool.close(timeout=5)
        except Exception as e:
            # Worth logging: a pool that fails to close leaves connections open
            # on the Lakebase side, and on a restart loop those accumulate
            # against the connection limit. Silently passing hid that.
            logger.warning("Database pool did not close cleanly: %s", e, exc_info=True)
        else:
            logger.info("Database pool closed")
    else:
        logger.info("No database pool to close")


def _convert_params(sql: str, params: dict | None) -> tuple[str, dict | None]:
    """Convert :name style params to %(name)s style for psycopg3."""
    if not params:
        return sql, params
    converted = re.sub(r'(?<!:):([a-zA-Z_]\w*)', r'%(\1)s', sql)
    return converted, params


async def execute_raw(sql: str, params: dict | None = None) -> list[dict]:
    """Execute raw SQL and return results as list of dicts.

    Accepts :name style params (auto-converted to psycopg3 %(name)s style).
    Borrows a connection from the pool (fast) instead of creating a new one.
    """
    converted_sql, converted_params = _convert_params(sql, params)

    def _exec():
        if _pool:
            with _pool.connection() as conn:
                cur = conn.execute(converted_sql, converted_params or {})
                if cur.description:
                    return list(cur.fetchall())
                return []
        else:
            conn = _get_connection()
            try:
                cur = conn.execute(converted_sql, converted_params or {})
                if cur.description:
                    return list(cur.fetchall())
                return []
            finally:
                conn.close()

    return await asyncio.to_thread(_exec)
