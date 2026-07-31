"""Apply plain-SQL migrations from migrations/ exactly once, in filename order.

Used by .github/scripts/apply_production_migrations.py (the merge-to-main
workflow). It is written as a standalone module so the same exactly-once logic
can also back a `databricks bundle deploy` postdeploy hook if you add one — dev
and CI then behave identically.

Applied files are recorded in schema_migrations with a checksum; a file whose
content changes after being applied is reported as drift (and skipped — add a
new migration instead of editing an old one). Each file runs in its own
transaction, so a failing migration rolls back entirely and stops the run.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import psycopg

MIGRATIONS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_by TEXT NOT NULL DEFAULT current_user
)
"""


@dataclass
class MigrationResult:
    filename: str
    applied: bool
    note: str = ""


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pending_migrations(conn: psycopg.Connection, migrations_dir: Path) -> list[Path]:
    """Migration files not yet recorded in schema_migrations, in apply order."""
    conn.execute(MIGRATIONS_TABLE_DDL)
    applied = {
        row[0] for row in conn.execute("SELECT filename FROM schema_migrations")
    }
    return [
        p
        for p in sorted(migrations_dir.glob("*.sql"))
        if p.name not in applied
    ]


def apply_pending(
    conn: psycopg.Connection, migrations_dir: Path
) -> list[MigrationResult]:
    """Apply every pending migration. Raises on the first failure (after the
    failed file's transaction has rolled back)."""
    conn.execute(MIGRATIONS_TABLE_DDL)
    applied = dict(
        conn.execute("SELECT filename, checksum FROM schema_migrations")
    )

    results: list[MigrationResult] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        sql_text = path.read_text(encoding="utf-8")
        digest = _checksum(sql_text)

        if path.name in applied:
            note = ""
            if applied[path.name] != digest:
                note = (
                    "DRIFT: file content changed after it was applied — "
                    "add a new migration instead of editing this one"
                )
            results.append(MigrationResult(path.name, applied=False, note=note))
            continue

        with conn.transaction():
            conn.execute(sql_text)
            conn.execute(
                "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)",
                (path.name, digest),
            )
        results.append(MigrationResult(path.name, applied=True))

    return results
