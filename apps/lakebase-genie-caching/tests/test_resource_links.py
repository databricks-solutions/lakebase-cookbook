"""Regression checks for resource link safety."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_config_does_not_emit_empty_job_urls():
    start_server = (ROOT / "agent_server" / "start_server.py").read_text()

    assert "def _job_link" in start_server
    assert '"type") == "trace-archive"' in start_server
    assert 'f"{host}/jobs/{job_id}{o_param}" if job_id else None' in start_server
    assert 'f"{host}/jobs/{trace_archive_job_id}{o_param}"' not in start_server
    assert 'f"{host}/jobs/{batch_job_id}{o_param}"' not in start_server


def test_frontend_resource_links_allow_null_values():
    api = (ROOT / "frontend" / "src" / "api.ts").read_text()
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text()

    assert "trace_archive_job: string | null" in api
    assert "batch_pipelines_job: string | null" in api
    assert "if (!href) return null" in app
