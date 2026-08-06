"""Tests for the SPA fallback routing from agent_server/start_server.py.

Creates a temporary frontend directory with index.html and assets/ to verify
that the catch-all route serves index.html for SPA routes while still serving
static files directly.
"""

import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.testclient import TestClient


def _make_spa_app(frontend_dir: str) -> FastAPI:
    """Build a minimal FastAPI app with the same SPA fallback logic as start_server.py."""
    app = FastAPI()

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    assets_dir = os.path.join(frontend_dir, "assets")
    app.mount("/assets", StaticFiles(directory=assets_dir), name="static-assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        file_path = os.path.join(frontend_dir, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        index = os.path.join(frontend_dir, "index.html")
        return FileResponse(index)

    return app


@pytest.fixture
def spa_client(tmp_path):
    """Create a temp frontend dir and return a TestClient."""
    index_html = tmp_path / "index.html"
    index_html.write_text("<!DOCTYPE html><html><body>SPA</body></html>")

    assets = tmp_path / "assets"
    assets.mkdir()
    js_file = assets / "main.js"
    js_file.write_text("console.log('app');")

    favicon = tmp_path / "favicon.ico"
    favicon.write_bytes(b"\x00\x00")

    app = _make_spa_app(str(tmp_path))
    return TestClient(app)


class TestSPAFallback:
    def test_root_returns_index_html(self, spa_client):
        resp = spa_client.get("/")
        assert resp.status_code == 200
        assert "SPA" in resp.text

    def test_cache_route_returns_index_html(self, spa_client):
        resp = spa_client.get("/cache")
        assert resp.status_code == 200
        assert "SPA" in resp.text

    def test_memory_route_returns_index_html(self, spa_client):
        resp = spa_client.get("/memory")
        assert resp.status_code == 200
        assert "SPA" in resp.text

    def test_nested_route_returns_index_html(self, spa_client):
        resp = spa_client.get("/some/deep/route")
        assert resp.status_code == 200
        assert "SPA" in resp.text

    def test_static_file_served_directly(self, spa_client):
        resp = spa_client.get("/favicon.ico")
        assert resp.status_code == 200
        assert resp.content == b"\x00\x00"

    def test_assets_js_served(self, spa_client):
        resp = spa_client.get("/assets/main.js")
        assert resp.status_code == 200
        assert "console.log" in resp.text

    def test_api_routes_not_intercepted(self, spa_client):
        resp = spa_client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
