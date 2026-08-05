"""Tests for setup workspace configuration discovery."""

from scripts.setup_workspace import _resolve_lakebase_target


def test_resolve_lakebase_target_prefers_autoscaling_project():
    app_data = {
        "resources": [
            {"database": {"instance_name": "legacy-provisioned"}},
        ]
    }
    variables = {
        "lakebase_project": "lakebase-genie-caching",
        "lakebase_instance": "legacy-provisioned",
    }

    target = _resolve_lakebase_target(app_data, variables)

    assert target["mode"] == "autoscaling"
    assert target["project"] == "lakebase-genie-caching"
    assert target["endpoint"] == "projects/lakebase-genie-caching/branches/production/endpoints/primary"


def test_resolve_lakebase_target_falls_back_to_provisioned():
    app_data = {
        "resources": [
            {"database": {"instance_name": "legacy-provisioned"}},
        ]
    }

    target = _resolve_lakebase_target(app_data, {})

    assert target["mode"] == "provisioned"
    assert target["instance"] == "legacy-provisioned"
