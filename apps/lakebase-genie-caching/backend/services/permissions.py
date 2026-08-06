"""Ensure the app's service principal has required permissions on startup.

The Databricks Apps resource framework handles sql_warehouse, database,
serving_endpoint, experiment, job, and genie_space resources.

This module grants permissions for any remaining resources that the
framework cannot manage directly.

Job run permissions are granted out-of-band by the deployer/admin. The app
service principal can run jobs with CAN_MANAGE_RUN, but it cannot reliably
inspect or self-grant job ACLs at startup.
"""

import logging
import os

logger = logging.getLogger(__name__)

REQUIRED_PERMISSIONS: dict = {}


def _get_sp_name() -> str | None:
    """Get the current service principal's client ID (used as SP name in ACLs).

    In a Databricks App, the SP authenticates via OAuth with DATABRICKS_CLIENT_ID.
    For local dev (human user), returns None to skip permission checks.
    """
    sp_client_id = os.environ.get("DATABRICKS_CLIENT_ID")
    if sp_client_id:
        return sp_client_id

    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        me = w.current_user.me()
        app_id = getattr(me, "application_id", None)
        if app_id:
            return str(app_id)
        if me.user_name and "@" not in me.user_name:
            return me.user_name
    except Exception:
        pass
    return None


def ensure_permissions() -> dict:
    """Check and fix permissions for resources not managed by the Apps framework.

    Returns a summary dict of results per resource type.
    """
    if not REQUIRED_PERMISSIONS:
        return {"status": "skipped", "reason": "no non-framework resources to manage"}

    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()

    sp_name = _get_sp_name()
    if not sp_name:
        logger.info("Not running as a service principal — skipping permission checks")
        return {"status": "skipped", "reason": "not a service principal"}

    logger.info(f"Checking permissions for service principal: {sp_name}")
    results = {}

    for resource_type, spec in REQUIRED_PERMISSIONS.items():
        resource_results = []
        for resource_id in spec["resource_ids"]:
            api_path = spec["api_path_template"].format(resource_id=resource_id)
            try:
                resp = w.api_client.do("GET", api_path)
                acl_list = resp.get("access_control_list", [])

                has_permission = False
                for acl in acl_list:
                    acl_sp = acl.get("service_principal_name", "")
                    if acl_sp == sp_name:
                        for perm in acl.get("all_permissions", []):
                            if perm.get("permission_level") in (
                                spec["required_level"],
                                "CAN_MANAGE",
                                "IS_OWNER",
                            ):
                                has_permission = True
                                break
                    if has_permission:
                        break

                if has_permission:
                    logger.info(f"  {resource_type}/{resource_id}: already has {spec['required_level']}")
                    resource_results.append("ok")
                else:
                    logger.warning(
                        f"  {resource_type}/{resource_id}: MISSING {spec['required_level']} — granting..."
                    )
                    patch_body = {
                        "access_control_list": [
                            {
                                "service_principal_name": sp_name,
                                "permission_level": spec["required_level"],
                            }
                        ]
                    }
                    w.api_client.do("PATCH", api_path, body=patch_body)
                    logger.info(f"  {resource_type}/{resource_id}: granted {spec['required_level']}")
                    resource_results.append("granted")

            except Exception as e:
                logger.error(f"  {resource_type}/{resource_id}: permission check failed: {e}")
                resource_results.append(f"failed: {e}")

        if all(r == "ok" for r in resource_results):
            results[resource_type] = "ok"
        elif any("failed" in r for r in resource_results):
            results[resource_type] = "some_failures"
        else:
            results[resource_type] = "granted"

    return results
