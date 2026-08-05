"""Build Databricks workspace deep-links that work on every cloud.

Azure workspace hostnames embed the workspace (org) ID -- ``adb-<org_id>.<n>.azuredatabricks.net``
-- and Azure UI links need it as an ``?o=<org_id>`` query param to disambiguate
workspaces sharing an account. AWS (``dbc-*.cloud.databricks.com``,
``*.cloud.databricks.com``) and GCP hostnames do not carry the ID, and their UI
links do not need it.

Centralising that here keeps the ``adb-`` regex in one place instead of two
independent copies, and guarantees we never emit a dangling ``?`` or an empty
``?o=`` on non-Azure workspaces.
"""

import re

# Azure Databricks workspace hostnames embed the numeric workspace/org ID.
_AZURE_ORG_ID = re.compile(r"adb-(\d+)")


def extract_org_id(host: str) -> str:
    """Return the numeric workspace (org) ID, or "" when the host doesn't carry one.

    Only Azure hostnames encode it. An empty result is normal on AWS and GCP and
    is not an error.
    """
    if not host:
        return ""
    match = _AZURE_ORG_ID.search(host)
    return match.group(1) if match else ""


def org_query_param(host: str) -> str:
    """Return ``"?o=<org_id>"`` on Azure, or ``""`` elsewhere.

    Safe to append directly to a workspace URL that has no other query string.
    """
    org_id = extract_org_id(host)
    return f"?o={org_id}" if org_id else ""


def workspace_url(host: str, path: str) -> str:
    """Join a workspace host and UI path, adding ``?o=`` only when meaningful."""
    if not host:
        return ""
    return f"{host.rstrip('/')}/{path.lstrip('/')}{org_query_param(host)}"


def trace_deep_link(host: str, experiment_id: str, trace_id: str) -> str | None:
    """Deep-link to a single MLflow trace inside an experiment.

    Handles the query-string join so callers don't have to care whether ``?o=``
    was present -- the previous code appended a bare ``?`` on non-Azure hosts so
    that a later ``&selectedEvaluationId=`` would still parse.
    """
    if not (host and experiment_id and trace_id):
        return None
    base = workspace_url(host, f"ml/experiments/{experiment_id}/traces")
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}selectedEvaluationId={trace_id}"
