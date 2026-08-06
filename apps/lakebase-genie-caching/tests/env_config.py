"""Workspace configuration for the integration / benchmark scripts.

The scripts under ``tests/`` that talk to a live deployment (``e2e_*.py``,
``benchmark.py``, ``test_parameterized.py``) used to hardcode one workspace's
app URL, CLI profile, and Genie space IDs. That made them unrunnable for anyone
else and leaked workspace identifiers into a public repo.

They now read the environment instead. Set these before running:

    export GENIE_CACHE_APP_URL="https://<app>.<region>.databricksapps.com"
    export DATABRICKS_CONFIG_PROFILE="<your-cli-profile>"
    export GENIE_SPACE_IDS="<space-id-1>,<space-id-2>"

The unit-test suite (``pytest tests/``) does not need any of these -- it is
fully mocked. Helpers here return ``None``/``[]`` when unset so callers can skip
cleanly rather than fail with a confusing connection error.
"""

import os


def app_url() -> str | None:
    """Base URL of the deployed app, e.g. https://my-app.aws.databricksapps.com."""
    url = os.environ.get("GENIE_CACHE_APP_URL", "").strip().rstrip("/")
    return url or None


def cli_profile() -> str | None:
    """Databricks CLI profile used to mint a bearer token for the app."""
    profile = (
        os.environ.get("GENIE_CACHE_PROFILE")
        or os.environ.get("DATABRICKS_CONFIG_PROFILE")
        or ""
    ).strip()
    return profile or None


def genie_space_ids() -> list[str]:
    """Genie space IDs to exercise, in configuration order."""
    raw = os.environ.get("GENIE_SPACE_IDS", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


def require_app_url() -> str:
    """Return the app URL or raise with the variable to set."""
    url = app_url()
    if not url:
        raise SystemExit(
            "GENIE_CACHE_APP_URL is not set.\n"
            "  export GENIE_CACHE_APP_URL='https://<app>.<region>.databricksapps.com'"
        )
    return url


def require_profile() -> str:
    """Return the CLI profile or raise with the variable to set."""
    profile = cli_profile()
    if not profile:
        raise SystemExit(
            "No Databricks CLI profile configured.\n"
            "  export DATABRICKS_CONFIG_PROFILE='<your-cli-profile>'"
        )
    return profile


def require_genie_space_ids(minimum: int = 1) -> list[str]:
    """Return at least ``minimum`` configured space IDs, or raise."""
    ids = genie_space_ids()
    if len(ids) < minimum:
        raise SystemExit(
            f"GENIE_SPACE_IDS must list at least {minimum} space ID(s); got {len(ids)}.\n"
            "  export GENIE_SPACE_IDS='<space-id-1>,<space-id-2>'"
        )
    return ids
