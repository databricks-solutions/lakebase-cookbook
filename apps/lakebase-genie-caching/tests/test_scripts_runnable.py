"""Smoke tests that the helper scripts actually run.

Every script under scripts/ is documented for a field engineer to run by hand,
but none had a test that executed one. Two were broken as a result:

- generate_graph_diagram.py failed with ModuleNotFoundError: No module named
  'backend', because running a file inside scripts/ puts scripts/ on sys.path
  rather than the project root -- so it failed from every working directory.
- select_genie_spaces.py iterated the GenieListSpacesResponse wrapper, raising
  TypeError: 'GenieListSpacesResponse' object is not iterable.

These tests invoke the scripts as subprocesses, the way a reader would, so a
missing sys.path fix or an import error fails the build.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _run(script: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=180,
    )


@pytest.mark.parametrize("script", ["setup_workspace.py", "select_genie_spaces.py"])
def test_script_shows_help_without_a_workspace(script, tmp_path):
    """--help must work with no credentials, from an unrelated directory."""
    result = _run(script, "--help", cwd=tmp_path)

    assert result.returncode == 0, f"{script} --help failed:\n{result.stderr}"
    assert "usage:" in result.stdout.lower()


def test_generate_graph_diagram_runs_from_any_directory(tmp_path):
    """Regression: the script could not import `backend` from any cwd.

    It builds the real LangGraph pipeline, so this also catches an import error
    or a wiring break anywhere in the graph module.
    """
    result = _run("generate_graph_diagram.py", cwd=tmp_path)

    assert result.returncode == 0, (
        f"generate_graph_diagram.py failed:\n{result.stdout}\n{result.stderr}"
    )
    # Mermaid output should name the pipeline's entry nodes.
    assert "graph TD" in result.stdout
    assert "supervisor" in result.stdout
    assert "cache_search" in result.stdout


def test_generate_graph_diagram_writes_a_file(tmp_path):
    out = tmp_path / "pipeline.mmd"
    result = _run("generate_graph_diagram.py", "--output", str(out), cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert out.exists()
    assert "graph TD" in out.read_text()


def test_start_app_is_importable():
    """The local dev launcher is a documented entry point (`start-app`)."""
    from scripts.start_app import main

    assert callable(main)
