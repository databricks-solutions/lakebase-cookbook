"""Guard against workspace-specific identifiers re-entering the repo.

This is a public, field-consumable asset: nothing in it may point at a
particular Databricks workspace. Defaults that look plausible are worse than
missing ones, because a copy-paste deploy silently targets someone else's
warehouse, Genie space, or Unity Catalog schema.

Every workspace-specific value belongs in a bundle variable or an environment
variable. If this test fails, replace the literal with one -- do not add it to
the allowlist unless it is genuinely a placeholder or documentation example.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Directories with no hand-written source worth scanning.
SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "dist",           # frontend/dist is a build artefact of frontend/src
    ".idea",
    ".vscode",
    ".databricks",
}

SKIP_FILES = {
    "uv.lock",
    "package-lock.json",
    "tsconfig.tsbuildinfo",
    # This file necessarily contains the patterns it forbids.
    "test_no_hardcoded_identifiers.py",
}

SCAN_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".yml", ".yaml",
    ".json", ".md", ".toml", ".ini", ".cfg", ".sh", ".example", ".css", ".html",
}

# Each pattern pairs a regex with the parameter a developer should use instead.
FORBIDDEN = [
    (
        re.compile(r"\badb-\d{10,}\b"),
        "Azure workspace ID -- use the target's `workspace.host` or a CLI profile",
    ),
    (
        re.compile(r"\b01f[0-9a-f]{29}\b"),
        "Genie space ID -- use the `genie_space_ids` bundle variable / GENIE_SPACE_IDS",
    ),
    (
        re.compile(r"sean[._-]zhang", re.IGNORECASE),
        "personal identifier -- use a neutral placeholder or a bundle variable",
    ),
    (
        re.compile(r"\bdbc-[0-9a-f]{8}-[0-9a-f]{4}\b"),
        "AWS workspace hostname -- use the target's `workspace.host`",
    ),
    (
        # A real app hostname is <app-name>-<workspace-id>.<region>.databricksapps.com.
        # Placeholder forms such as <app>.<region>.databricksapps.com or
        # my-app.aws.databricksapps.com are fine in docs, so only flag hostnames
        # carrying a long numeric workspace ID.
        re.compile(r"[\w-]*\d{10,}[\w-]*\.[\w-]+\.databricksapps\.com"),
        "deployed app URL -- read GENIE_CACHE_APP_URL (see tests/env_config.py)",
    ),
]

# A bare 16-hex string is the shape of a warehouse ID. Checked separately so we
# can exclude coincidental matches such as git SHAs and CSS colour hashes.
WAREHOUSE_ID = re.compile(r"(?<![0-9a-zA-Z])[0-9a-f]{16}(?![0-9a-zA-Z])")


def _scannable_files() -> list[Path]:
    files = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in SKIP_FILES:
            continue
        if path.suffix not in SCAN_SUFFIXES:
            continue
        files.append(path)
    return files


def _violations(pattern: re.Pattern, files: list[Path]) -> list[str]:
    hits = []
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(lines, start=1):
            for match in pattern.finditer(line):
                hits.append(
                    f"{path.relative_to(ROOT)}:{lineno}: {match.group(0)}  |  {line.strip()[:100]}"
                )
    return hits


@pytest.mark.parametrize(
    "pattern,guidance",
    FORBIDDEN,
    ids=[
        "azure-workspace-id",
        "genie-space-id",
        "personal-identifier",
        "aws-workspace-host",
        "deployed-app-url",
    ],
)
def test_no_workspace_identifiers(pattern: re.Pattern, guidance: str):
    hits = _violations(pattern, _scannable_files())
    assert not hits, (
        f"Found {len(hits)} hardcoded workspace identifier(s).\n"
        f"Replace with: {guidance}\n\n" + "\n".join(hits)
    )


def test_no_hardcoded_warehouse_ids():
    """A 16-hex literal in config or source is almost always a warehouse ID."""
    files = [
        path
        for path in _scannable_files()
        # Lockfiles, docs and build metadata legitimately contain hashes.
        if path.suffix in {".py", ".yml", ".yaml", ".ts", ".tsx", ".example"}
    ]
    hits = _violations(WAREHOUSE_ID, files)
    assert not hits, (
        f"Found {len(hits)} possible hardcoded warehouse ID(s).\n"
        "Use the `warehouse_id` bundle variable / SQL_WAREHOUSE_ID env var.\n\n"
        + "\n".join(hits)
    )
