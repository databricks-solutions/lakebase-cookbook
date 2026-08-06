"""One-time workspace setup after first `databricks bundle deploy`.

Runs as the deployer (your credentials) to perform admin-level actions
that the app's service principal cannot do itself:

  1. Register Lakebase database as a Unity Catalog catalog
  2. Grant Lakebase schema CREATE to the app's SP
  3. Grant Genie space CAN_MANAGE to the app's SP
  4. Grant UC table access for Genie space data to the app's SP

Usage:
    python scripts/setup_workspace.py --profile <cli-profile> --app-name <app>

All values are derived from the deployed app and its Genie spaces — nothing
is hardcoded.
"""

import argparse
import json
import logging
import os
import sys
import uuid

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_override_file(target: str | None) -> dict:
    """Read .databricks/bundle/<target>/variable-overrides.json, if present."""
    if not target:
        return {}
    path = os.path.join(
        PROJECT_ROOT, ".databricks", "bundle", target, "variable-overrides.json"
    )
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _read_dab_variable(var_name: str, target: str | None = None) -> str:
    """Resolve a bundle variable the same way the Databricks CLI does.

    Precedence, highest first:
      1. BUNDLE_VAR_<name> environment variable
      2. .databricks/bundle/<target>/variable-overrides.json
      3. the target's `variables:` block in databricks.yml
      4. the variable's `default:` in databricks.yml

    Reading only (4) was wrong once the workspace-specific variables lost their
    defaults: setup then silently resolved genie_space_ids to "" and granted the
    app's service principal permission on zero Genie spaces, leaving a deployment
    that looked configured but could not answer a question.
    """
    env_value = os.environ.get(f"BUNDLE_VAR_{var_name}")
    if env_value:
        return env_value

    overrides = _read_override_file(target)
    if var_name in overrides and overrides[var_name]:
        return str(overrides[var_name])

    try:
        import yaml
        with open(os.path.join(PROJECT_ROOT, "databricks.yml")) as f:
            dab = yaml.safe_load(f)

        if target and target in (dab.get("targets") or {}):
            target_vars = (dab["targets"][target] or {}).get("variables") or {}
            if var_name in target_vars:
                return str(target_vars[var_name])

        return str((dab.get("variables") or {}).get(var_name, {}).get("default", ""))
    except Exception:
        return ""


def _read_dab_variables(target: str | None = None) -> dict[str, str]:
    """Read the bundle variables used by setup."""
    names = (
        "lakebase_project",
        "lakebase_instance",
        "genie_space_ids",
        "trace_archive_catalog",
        "trace_archive_schema",
    )
    return {name: _read_dab_variable(name, target) for name in names}


def _resolve_lakebase_target(app_data: dict, variables: dict[str, str]) -> dict[str, str]:
    """Resolve whether this deployment uses Autoscaling or provisioned Lakebase."""
    provisioned_instance = ""
    for resource in app_data.get("resources", []):
        if resource.get("database"):
            provisioned_instance = resource["database"].get("instance_name", "")
            break

    project = variables.get("lakebase_project", "").strip()
    if project:
        return {
            "mode": "autoscaling",
            "project": project,
            "endpoint": f"projects/{project}/branches/production/endpoints/primary",
        }

    instance = provisioned_instance or variables.get("lakebase_instance", "").strip()
    if instance:
        return {"mode": "provisioned", "instance": instance}

    return {"mode": "unknown"}


def _quote_ident(identifier: str) -> str:
    """Quote a PostgreSQL identifier."""
    return '"' + identifier.replace('"', '""') + '"'


def main():
    parser = argparse.ArgumentParser(description="One-time workspace setup for Lakebase Genie Caching")
    parser.add_argument("--profile", required=True, help="Databricks CLI profile")
    parser.add_argument("--app-name", default="lakebase-genie-caching", help="Databricks App name")
    parser.add_argument("--catalog-name", default="pg_genie_caching", help="UC catalog name for Lakebase")
    parser.add_argument("--target", default=None, help="DAB target (reads target-specific variable overrides)")
    parser.add_argument(
        "--genie-space-ids",
        default=None,
        help="Comma-separated Genie space IDs; overrides the bundle variable",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print actions without executing")
    args = parser.parse_args()

    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient(profile=args.profile)
    host = w.config.host.rstrip("/")
    me = w.current_user.me()
    logger.info(f"Connected to {host} as {me.user_name}")

    # ── Discover app SP and resources ──
    logger.info(f"Looking up app '{args.app_name}'...")
    app_data = w.api_client.do("GET", f"/api/2.0/apps/{args.app_name}")
    sp_client_id = app_data.get("service_principal_client_id", "")
    if not sp_client_id:
        logger.error("App has no service principal. Is it deployed?")
        sys.exit(1)
    logger.info(f"App SP: {sp_client_id}")

    variables = _read_dab_variables(args.target)
    lakebase_target = _resolve_lakebase_target(app_data, variables)

    genie_space_ids_raw = args.genie_space_ids or variables.get("genie_space_ids", "")
    genie_space_ids = [s.strip() for s in genie_space_ids_raw.split(",") if s.strip()]
    if not genie_space_ids:
        logger.warning(
            "No Genie spaces resolved -- steps 3 and 4 will grant nothing, and the app "
            "will not be able to answer questions.\n"
            "  Pass --genie-space-ids <id1,id2>, or set the genie_space_ids bundle "
            "variable for target %r.",
            args.target,
        )

    logger.info(f"Lakebase mode: {lakebase_target['mode']}")
    if lakebase_target["mode"] == "autoscaling":
        logger.info(f"Lakebase project: {lakebase_target['project']}")
        logger.info(f"Lakebase endpoint: {lakebase_target['endpoint']}")
    elif lakebase_target["mode"] == "provisioned":
        logger.info(f"Lakebase instance: {lakebase_target['instance']}")
    logger.info(f"Genie spaces: {genie_space_ids}")
    logger.info(f"Catalog name: {args.catalog_name}")

    if lakebase_target["mode"] == "unknown":
        logger.error("Could not determine Lakebase project or provisioned instance")
        sys.exit(1)

    if args.dry_run:
        logger.info("\n[DRY RUN] Would perform:")
        if lakebase_target["mode"] == "autoscaling":
            logger.info(f"  1. Grant CAN_USE on Lakebase project '{lakebase_target['project']}'")
        else:
            logger.info(f"  1. Create UC catalog '{args.catalog_name}' for '{lakebase_target['instance']}'")
        logger.info(f"  2. Create/grant Lakebase OAuth role for SP {sp_client_id}")
        logger.info(f"  3. Grant CAN_MANAGE on {len(genie_space_ids)} Genie space(s)")
        logger.info(f"  4. Grant UC table access for data referenced by Genie spaces")
        return

    failures: list[str] = []

    if lakebase_target["mode"] == "autoscaling":
        _section("Step 1: Grant Lakebase Autoscaling project permission")
        try:
            w.api_client.do("PATCH", f"/api/2.0/permissions/database-projects/{lakebase_target['project']}", body={
                "access_control_list": [{
                    "service_principal_name": sp_client_id,
                    "permission_level": "CAN_USE",
                }]
            })
            logger.info(f"  Granted CAN_USE on project '{lakebase_target['project']}' to {sp_client_id}")
        except Exception as e:
            logger.error(f"  FAILED: {e}")
            failures.append(f"Step 1 (Lakebase project permission): {e}")
    else:
        # ── Step 1: Register Lakebase as UC catalog ──
        _section("Step 1: Register Lakebase as Unity Catalog catalog")
        try:
            w.api_client.do("POST", "/api/2.0/database/catalogs", body={
                "database_instance_name": lakebase_target["instance"],
                "name": args.catalog_name,
                "database_name": "databricks_postgres",
                "create_database_if_not_exists": True,
            })
            logger.info(f"  Created catalog '{args.catalog_name}'")
        except Exception as e:
            if "already exists" in str(e).lower():
                logger.info(f"  Catalog '{args.catalog_name}' already exists (OK)")
            else:
                logger.warning(f"  Failed: {e}")

    # ── Step 2: Grant Lakebase schema permissions ──
    _section("Step 2: Grant Lakebase schema permissions to SP")
    try:
        import psycopg

        if lakebase_target["mode"] == "autoscaling":
            endpoint = lakebase_target["endpoint"]
            endpoint_info = w.postgres.get_endpoint(name=endpoint)
            db_host = endpoint_info.status.hosts.host
            cred = w.postgres.generate_database_credential(endpoint=endpoint)
        else:
            instance_info = w.api_client.do("GET", f"/api/2.0/database/instances/{lakebase_target['instance']}")
            db_host = instance_info.get("read_write_dns", "")
            cred = w.database.generate_database_credential(
                request_id=str(uuid.uuid4()),
                instance_names=[lakebase_target["instance"]],
            )

        conn = psycopg.connect(
            host=db_host, port=5432, dbname="databricks_postgres",
            user=me.user_name, password=cred.token,
            sslmode="require", autocommit=True,
        )
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("CREATE EXTENSION IF NOT EXISTS databricks_auth")
        try:
            conn.execute("SELECT databricks_create_role(%s, %s)", (sp_client_id, "service_principal"))
            logger.info(f"  Created OAuth role for {sp_client_id}")
        except Exception as e:
            if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                raise
            logger.info(f"  OAuth role for {sp_client_id} already exists")

        quoted_sp = _quote_ident(sp_client_id)
        conn.execute(f"GRANT CONNECT ON DATABASE databricks_postgres TO {quoted_sp}")
        conn.execute(f"GRANT CREATE, USAGE ON SCHEMA public TO {quoted_sp}")
        conn.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {quoted_sp}")
        conn.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {quoted_sp}"
        )
        conn.close()
        logger.info(f"  Granted schema ALL to {sp_client_id}")
    except Exception as e:
        logger.error(f"  FAILED: {e}")
        failures.append(f"Step 2 (Lakebase schema grants): {e}")

    # ── Step 3: Grant Genie space permissions ──
    _section("Step 3: Grant Genie space CAN_MANAGE to SP")
    for space_id in genie_space_ids:
        try:
            w.api_client.do("PATCH", f"/api/2.0/permissions/genie/{space_id}", body={
                "access_control_list": [{
                    "service_principal_name": sp_client_id,
                    "permission_level": "CAN_MANAGE",
                }]
            })
            logger.info(f"  Granted CAN_MANAGE on {space_id}")
        except Exception as e:
            logger.warning(f"  Failed for {space_id}: {e}")

    # ── Step 4: Grant UC table access ──
    _section("Step 4: Grant UC table access for Genie space data")
    headers = w.config.authenticate()
    granted_catalogs: set[str] = set()
    granted_schemas: set[str] = set()

    for space_id in genie_space_ids:
        try:
            import urllib.request
            url = f"{host}/api/2.0/genie/spaces/{space_id}?include_serialized_space=true"
            req = urllib.request.Request(url, headers={**headers, "Content-Type": "application/json"})
            resp_data = json.loads(urllib.request.urlopen(req, timeout=15).read())

            serialized = resp_data.get("serialized_space", "")
            if not serialized:
                logger.info(f"  No serialized config for space {space_id}")
                continue

            space_data = json.loads(serialized) if isinstance(serialized, str) else serialized
            data_sources = space_data.get("data_sources", {})
            if isinstance(data_sources, str):
                data_sources = json.loads(data_sources)

            for table in data_sources.get("tables", []):
                fqn = table.get("identifier", "")
                parts = fqn.split(".")
                if len(parts) < 2:
                    continue

                catalog_name = parts[0]
                schema_name = f"{parts[0]}.{parts[1]}"

                if catalog_name not in granted_catalogs:
                    try:
                        w.api_client.do("PATCH", f"/api/2.1/unity-catalog/permissions/catalog/{catalog_name}", body={
                            "changes": [{"principal": sp_client_id, "add": ["USE_CATALOG"]}]
                        })
                        logger.info(f"  Granted USE_CATALOG on {catalog_name}")
                        granted_catalogs.add(catalog_name)
                    except Exception as e:
                        logger.warning(f"  Failed USE_CATALOG on {catalog_name}: {e}")

                if schema_name not in granted_schemas:
                    try:
                        w.api_client.do("PATCH", f"/api/2.1/unity-catalog/permissions/schema/{schema_name}", body={
                            "changes": [{"principal": sp_client_id, "add": ["USE_SCHEMA", "SELECT"]}]
                        })
                        logger.info(f"  Granted USE_SCHEMA + SELECT on {schema_name}")
                        granted_schemas.add(schema_name)
                    except Exception as e:
                        logger.warning(f"  Failed on {schema_name}: {e}")

        except Exception as e:
            logger.warning(f"  Could not resolve tables for space {space_id}: {e}")

    if failures:
        _section("Setup INCOMPLETE")
        for f in failures:
            logger.error(f"  {f}")
        logger.error(
            "\nThe app's service principal does NOT have the access it needs. The app "
            "will start but run in degraded mode -- no cache, no memory, no sessions.\n"
            "\nIf a Lakebase step failed with 'project not found' shortly after a "
            "`bundle destroy`: Lakebase SOFT-deletes the project and holds its name "
            "for a 7-day retention window, so redeploying inside that window does not "
            "recreate it. Set a new `lakebase_project` value in databricks.yml (or in "
            ".databricks/bundle/<target>/variable-overrides.json), redeploy, and re-run "
            "this script."
        )
        sys.exit(1)

    _section("Setup complete!")


def _section(title: str):
    logger.info(f"\n{'='*60}")
    logger.info(title)
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
