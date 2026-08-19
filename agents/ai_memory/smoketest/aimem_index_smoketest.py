"""Offline smoke test for the ai_memory schema/index CONTRACT (no live infra).

WHAT THIS PROVES (offline, no Databricks / no Lakebase / no model endpoint):
  1. The semantic-recall index is HNSW, not IVFFlat. This matters because
     ``memories_ddl`` is executed by ``ensure_schema`` at application startup,
     i.e. against an empty table on a fresh database. IVFFlat derives its lists
     from a k-means training step over the rows present at build time, so
     building it empty yields a poorly-clustered index; HNSW has no training
     step.
  2. The switch actually takes effect on an existing database: the legacy
     IVFFlat index is dropped by name and the HNSW index is created under a
     *new* name. ``CREATE INDEX IF NOT EXISTS`` matches on name only and never
     compares the definition, so reusing the old name would silently leave an
     existing IVFFlat index in place. The drop precedes the create and both are
     in the statement list ``ensure_schema`` runs in one transaction, so a
     failed build rolls the drop back.
  3. The index opclass is ``vector_cosine_ops``, matching the ``<=>`` cosine
     operator that ``memory.py`` actually uses for recall. A mismatched opclass
     silently disables the index for that operator.
  4. The HNSW parameters match the other pgvector examples in this cookbook
     (graphrag), so the repo does not disagree with itself about how to index
     embeddings. This is asserted by parsing graphrag's schema.sql, not by
     restating a constant here.
  5. Every CREATE is idempotent (``IF NOT EXISTS``) and the DROP is
     ``IF EXISTS``, because ``ensure_schema`` runs on every startup.
  6. Statement ordering is valid: the ``vector`` extension precedes the table
     that declares a ``vector`` column, which precedes the indexes on it.
  7. ``embedding_dim`` propagates into the column type, and the schema name is
     quoted so a reserved word or mixed case cannot break the DDL.

WHAT THIS DOES NOT COVER (needs live Lakebase):
  - pgvector's actual index behaviour and recall. The recall numbers motivating
    the HNSW switch were measured on a live Lakebase instance (PG 16.14,
    pgvector 0.8.0, 1024-dim databricks-bge-large-en) and are quoted in the
    pull request, not reproduced here.
  - Whether the planner chooses the index at a given row count. That is
    cost-based and therefore environment-dependent.
  - The cost of the one-time rebuild on an existing populated table. Measured
    separately; see the README.

Run:
    cd agents/ai_memory && uv sync && uv run python smoketest/aimem_index_smoketest.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_memory.db import (  # noqa: E402
    EMBEDDING_INDEX_NAME,
    LEGACY_EMBEDDING_INDEX_NAME,
    memories_ddl,
)

FAILURES: list[str] = []

GRAPHRAG_SCHEMA = Path(__file__).resolve().parents[2] / "graphrag" / "sql" / "schema.sql"

EXPECTED_HNSW_PARAMS = {"m": "16", "ef_construction": "64"}


def check(name: str, got, want) -> None:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got={got!r} want={want!r}")
    if not ok:
        FAILURES.append(name)


def fail(name: str, why: str) -> None:
    """Record a FAILURE for drift that would otherwise raise.

    The harness contract is print-a-FAIL-and-exit-1, so a renamed statement or a
    reworded graphrag schema must surface as a FAIL line, not a traceback.
    """
    print(f"  [FAIL] {name}: {why}")
    FAILURES.append(name)


def find_stmt(ddl: list[str], needle: str, name: str) -> str | None:
    for stmt in ddl:
        if needle in stmt:
            return stmt
    fail(name, f"no statement containing {needle!r}")
    return None


def hnsw_params(sql: str) -> dict[str, str]:
    """Extract the ``m`` / ``ef_construction`` storage parameters from a WITH clause.

    Scoped to the parenthesised WITH clause so an unrelated ``m = <digits>``
    elsewhere in the statement cannot be picked up as an HNSW parameter.
    """
    m = re.search(r"WITH\s*\((?P<params>[^)]*)\)", sql, re.IGNORECASE)
    if not m:
        return {}
    return dict(re.findall(r"(\bm\b|\bef_construction\b)\s*=\s*(\d+)", m.group("params")))


def main() -> int:
    dim = 1024
    schema = "aimem"
    ddl = memories_ddl(schema, dim)
    joined = "\n".join(ddl)
    embedding_idx = find_stmt(ddl, EMBEDDING_INDEX_NAME, "embedding index statement exists")
    drop_legacy = find_stmt(ddl, "DROP INDEX", "legacy-index drop statement exists")
    if embedding_idx is None or drop_legacy is None:
        print(f"\nRESULT: {len(FAILURES)} FAILED -> {FAILURES}")
        return 1

    print("\n--- 1. index type -------------------------------------------------")
    check("embedding index uses HNSW", "USING hnsw" in embedding_idx, True)
    # Scoped to the embedding index statement, so an unrelated comment or a
    # column named "lists" elsewhere in the DDL cannot flip these.
    check("embedding index does not use IVFFlat", "ivfflat" in embedding_idx.lower(), False)
    check("no IVFFlat lists parameter remains", "lists" in embedding_idx.lower(), False)

    print("\n--- 2. the switch takes effect on an existing database -------------")
    # The whole point: IF NOT EXISTS matches on name, so the new index must not
    # reuse the old name, and the old name must be dropped explicitly.
    check(
        "the HNSW index uses a new name",
        EMBEDDING_INDEX_NAME != LEGACY_EMBEDDING_INDEX_NAME,
        True,
    )
    check(
        "the legacy index name is dropped",
        LEGACY_EMBEDDING_INDEX_NAME in drop_legacy,
        True,
    )
    check("the drop is schema-qualified", f'"{schema}".' in drop_legacy, True)
    check("the drop precedes the create", ddl.index(drop_legacy) < ddl.index(embedding_idx), True)
    check(
        "the create does not reference the legacy name",
        LEGACY_EMBEDDING_INDEX_NAME in embedding_idx,
        False,
    )

    print("\n--- 3. opclass matches the recall operator ------------------------")
    check(
        "embedding index opclass is vector_cosine_ops",
        "vector_cosine_ops" in embedding_idx,
        True,
    )
    memory_src = (Path(__file__).resolve().parents[1] / "agent_memory" / "memory.py").read_text(
        encoding="utf-8"
    )
    check("recall uses the cosine operator <=>", "<=>" in memory_src, True)

    print("\n--- 4. consistency with the graphrag example ----------------------")
    check("graphrag schema.sql is present", GRAPHRAG_SCHEMA.exists(), True)
    ours = hnsw_params(embedding_idx)
    # Asserted against the literal expectation as well as against graphrag, so
    # the comparison cannot pass vacuously when both sides parse to {}.
    check("our HNSW parameters parse to the expected values", ours, EXPECTED_HNSW_PARAMS)
    if GRAPHRAG_SCHEMA.exists():
        graphrag_sql = GRAPHRAG_SCHEMA.read_text(encoding="utf-8")
        gr_match = re.search(r"USING\s+hnsw.*?;", graphrag_sql, re.IGNORECASE | re.DOTALL)
        if gr_match is None:
            fail(
                "graphrag declares an HNSW index",
                "no 'USING hnsw ... ;' statement found in graphrag/sql/schema.sql",
            )
        else:
            gr_idx = gr_match.group(0)
            check("HNSW parameters match graphrag", ours, hnsw_params(gr_idx))
            check("opclass matches graphrag", "vector_cosine_ops" in gr_idx, True)

    print("\n--- 5. re-runnable DDL -------------------------------------------")
    creates = [s for s in ddl if s.strip().upper().startswith("CREATE")]
    drops = [s for s in ddl if s.strip().upper().startswith("DROP")]
    check("every statement is a CREATE or a DROP", len(creates) + len(drops), len(ddl))
    check(
        "every CREATE is IF NOT EXISTS",
        all("IF NOT EXISTS" in s for s in creates),
        True,
    )
    check("every DROP is IF EXISTS", all("IF EXISTS" in s for s in drops), True)

    print("\n--- 6. statement ordering ----------------------------------------")
    ext = find_stmt(ddl, "CREATE EXTENSION", "extension statement exists")
    tbl = find_stmt(ddl, "CREATE TABLE", "table statement exists")
    if ext is not None and tbl is not None:
        check("vector extension precedes the table", ddl.index(ext) < ddl.index(tbl), True)
        check("table precedes its indexes", ddl.index(tbl) < ddl.index(embedding_idx), True)

    print("\n--- 7. parameterisation ------------------------------------------")
    check(f"embedding column is vector({dim})", f"vector({dim})" in joined, True)
    check("schema name is quoted", f'"{schema}"' in joined, True)
    # NOTE: this proves only that the arguments reach the generated DDL. It does
    # NOT prove that changing EMBEDDING_DIM migrates an existing database -- the
    # CREATE TABLE is IF NOT EXISTS, so an existing vector(n) column is left as
    # it is. The README documents that limitation.
    other = memories_ddl("Mixed-Case", 768)
    check(
        "a different dim reaches the generated DDL",
        "vector(768)" in "\n".join(other),
        True,
    )
    check(
        "a mixed-case schema stays quoted",
        '"Mixed-Case"' in "\n".join(other),
        True,
    )

    print("\n" + "=" * 66)
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} FAILED -> {FAILURES}")
        return 1
    print("RESULT: ALL PASSED - ai_memory index contract verified offline.")
    print("(Live pgvector recall measured separately; see the pull request.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
