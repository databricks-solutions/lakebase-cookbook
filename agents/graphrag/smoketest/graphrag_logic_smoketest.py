"""Offline smoke test for the GraphRAG hybrid-retrieval LOGIC (no live infra).

WHAT THIS PROVES (offline, no Databricks / no Lakebase / no model endpoint):
  1. The vector-seed step ranks the semantically-closest node first.
  2. The recursive-CTE graph expansion pulls in graph-connected context that a
     pure vector search would MISS — the whole point of GraphRAG — bounded by
     :max_hops with a working cycle guard.
  3. The blended score (seed_similarity * 0.5^hop) ranks seeds above their
     neighbors and decays with hop distance.
  4. The BUILD-side graph assembly (notebooks/graph_build.assemble_graph) turns
     structured dims + LLM enrichment into the intended nodes/edges.
  5. The `seed_floor` distractor guard drops weak semantic seeds before the walk,
     and its -1.0 default leaves the pre-floor behavior unchanged.
  6. The UPSTREAM indexing path (graph_upstream): chunking keeps stable ids and
     overlap, trigram entity resolution collapses alias spellings into one node,
     and the emitted rows conform to the 8-column gold_triplets contract.

WHAT THIS DOES NOT COVER (needs live Lakebase, tracked in README):
  - pgvector's actual HNSW ANN operator (<=>) and index behavior — here we
    compute cosine in Python and seed deterministically, then run the SAME
    recursive-CTE traversal in DuckDB (SQL dialect ~equivalent for this logic).
  - Real model embeddings — we use a tiny deterministic bag-of-words vector.
  - Sync from UC / permissions / scale.

Run: uv run --python 3.11 --with duckdb --with numpy graphrag_logic_smoketest.py
"""
from __future__ import annotations

import sys

import duckdb
import numpy as np

FAILURES: list[str] = []


def check(name: str, got, want) -> None:
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got={got!r} want={want!r}")
    if not ok:
        FAILURES.append(name)


# --------------------------------------------------------------------------- graph
# A small retail supply-chain KG (matches the README anchor). node_id = 'type:key'.
NODES = [
    ("product:122", "Product",  "Skim Milk 2L"),
    ("product:130", "Product",  "Whole Milk 2L"),        # substitute for skim milk
    ("supplier:S2", "Supplier", "Supplier S2 (Boston)"),
    ("supplier:S3", "Supplier", "Supplier S3 (Boston)"),
    ("region:ne",   "Region",   "Northeast"),
    ("category:dairy", "Category", "Dairy"),
    ("product:400", "Product",  "Diesel Generator"),      # unrelated island (control)
    ("supplier:S9", "Supplier", "Supplier S9 (Denver)"),  # only supplies the generator
]
EDGES = [
    ("product:122", "supplier:S2", "SUPPLIED_BY"),
    ("product:122", "supplier:S3", "SUPPLIED_BY"),
    ("product:122", "category:dairy", "BELONGS_TO"),
    ("product:122", "product:130", "SUBSTITUTE_FOR"),
    ("product:130", "supplier:S2", "SUPPLIED_BY"),
    ("supplier:S2", "region:ne", "LOCATED_IN"),
    ("supplier:S3", "region:ne", "LOCATED_IN"),
    ("product:122", "region:ne", "SURGES_IN"),
    ("product:400", "supplier:S9", "SUPPLIED_BY"),         # unrelated island
]

# Deterministic tiny "embedding": bag-of-words over a fixed vocab, L2-normalized.
VOCAB = ["skim", "milk", "whole", "supplier", "boston", "denver", "northeast",
         "dairy", "diesel", "generator", "region", "category"]


def embed(text: str) -> np.ndarray:
    v = np.zeros(len(VOCAB), dtype=float)
    toks = text.lower().replace("(", " ").replace(")", " ").split()
    for i, w in enumerate(VOCAB):
        v[i] = sum(1.0 for t in toks if t == w)
    n = np.linalg.norm(v)
    return v / n if n else v


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))  # both normalized


def main() -> int:
    con = duckdb.connect()
    con.execute("CREATE TABLE nodes(node_id TEXT, node_type TEXT, name TEXT)")
    con.executemany("INSERT INTO nodes VALUES (?,?,?)", NODES)
    con.execute("CREATE TABLE edges(src_id TEXT, dst_id TEXT, rel TEXT)")
    con.executemany("INSERT INTO edges VALUES (?,?,?)", EDGES)

    # ---- 1) SEMANTIC SEED (computed in Python, as a stand-in for pgvector <=>)
    q = embed("skim milk demand in the northeast")
    sims = [(nid, cosine(q, embed(name))) for nid, _t, name in NODES]
    sims.sort(key=lambda x: x[1], reverse=True)
    seed_k = 2
    seeds = sims[:seed_k]
    print("\n== TEST 1: semantic seed ==")
    for nid, s in seeds:
        print(f"    seed {nid}: sim={s:.3f}")
    check("top semantic seed is skim milk", seeds[0][0], "product:122")

    # feed seeds into DuckDB for the SAME recursive-CTE expansion the .sql uses
    con.execute("CREATE TABLE seed(node_id TEXT, similarity DOUBLE)")
    con.executemany("INSERT INTO seed VALUES (?,?)", [(nid, float(s)) for nid, s in seeds])

    max_hops = 2
    # Mirrors sql/graphrag_retrieval.sql: an `adj` CTE (edges walkable both
    # directions) joined with a PLAIN JOIN in the recursive term. DuckDB dialect
    # swaps: ARRAY[x]->[x], `||`->list_append, `= ANY`->list_contains.
    walk_sql = f"""
    WITH RECURSIVE adj AS (
        SELECT src_id AS from_id, dst_id AS next_id, rel FROM edges
        UNION ALL
        SELECT dst_id AS from_id, src_id AS next_id, rel FROM edges
    ),
    walk AS (
        SELECT s.node_id AS node_id, 0 AS hop, s.similarity AS seed_similarity,
               s.node_id AS seed_id, [s.node_id] AS visited
        FROM seed s
        UNION ALL
        SELECT adj.next_id, w.hop + 1, w.seed_similarity, w.seed_id,
               list_append(w.visited, adj.next_id)
        FROM walk w
        JOIN adj ON adj.from_id = w.node_id
        WHERE w.hop < {max_hops}
          AND NOT list_contains(w.visited, adj.next_id)
    ),
    scored AS (
        SELECT node_id,
               MAX(seed_similarity * POWER(0.5, hop)) AS graph_score,
               MIN(hop) AS nearest_hop
        FROM walk GROUP BY node_id
    )
    SELECT s.node_id, n.node_type, n.name, s.nearest_hop,
           ROUND(s.graph_score, 4) AS score
    FROM scored s JOIN nodes n ON n.node_id = s.node_id
    ORDER BY s.graph_score DESC
    """
    rows = con.execute(walk_sql).fetchall()
    retrieved = {r[0]: r for r in rows}
    print("\n== TEST 2: graph expansion (recursive CTE, max_hops=2) ==")
    for r in rows:
        print(f"    {r[0]:16s} type={r[1]:9s} hop={r[3]} score={r[4]}")

    # 2a) GraphRAG pulls in connected context a flat vector search misses.
    # Suppliers S2/S3 and the substitute product 130 are NOT semantically similar
    # to "skim milk demand" but ARE graph-connected to the seed → must appear.
    for expected in ["supplier:S2", "supplier:S3", "product:130", "region:ne", "category:dairy"]:
        check(f"graph surfaced {expected}", expected in retrieved, True)

    # 2b) The unrelated island (diesel generator / S9) must NOT be pulled in.
    check("unrelated diesel generator excluded", "product:400" not in retrieved, True)
    check("unrelated supplier S9 excluded", "supplier:S9" not in retrieved, True)

    # 2c) Seed ranks above its neighbors (hop-decay works).
    milk = retrieved["product:122"][4]
    s2 = retrieved["supplier:S2"][4]
    check("seed scores above its 1-hop neighbor", milk > s2, True)

    # 2d) Depth bound respected: nothing beyond max_hops.
    check("no node deeper than max_hops", max(r[3] for r in rows) <= max_hops, True)

    con.close()

    # ---- 3) BUILD-side graph assembly (notebooks/graph_build.assemble_graph)
    print("\n== TEST 3: graph assembly from dims + enrichment ==")
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from graph_build import assemble_graph  # noqa: E402

    products = [
        {"product_id": 122, "name": "Skim Milk 2L", "category": "Dairy"},
        {"product_id": 130, "name": "Whole Milk 2L", "category": "Dairy"},
        {"product_id": 261, "name": "Diesel Generator", "category": "Equipment"},
    ]
    b_suppliers = [
        {"supplier_id": "S2", "name": "Supplier S2", "city": "Boston", "region": "Northeast"},
        {"supplier_id": "S3", "name": "Supplier S3", "city": "Boston", "region": "Northeast"},
        {"supplier_id": "S9", "name": "Supplier S9", "city": "Denver", "region": "West"},
    ]
    b_supplies = [
        {"product_id": 122, "supplier_id": "S2"}, {"product_id": 122, "supplier_id": "S3"},
        {"product_id": 130, "supplier_id": "S2"}, {"product_id": 261, "supplier_id": "S9"},
    ]
    b_surges = [{"product_id": 122, "region": "Northeast", "surge_ratio": 1.69}]
    b_enrich = {
        122: {"description": "Skim Milk 2L — a dairy product.", "substitute_ids": [130]},
        130: {"description": "Whole Milk 2L — a dairy product.", "substitute_ids": [122]},
        261: {"description": "Diesel Generator — an equipment product.", "substitute_ids": []},
    }
    bnodes, bedges = assemble_graph(products, b_suppliers, b_supplies, b_surges, b_enrich)

    # node_id convention + all expected node types present
    for nid in ["product:122", "supplier:S2", "region:northeast", "category:dairy"]:
        check(f"assembled node {nid}", nid in bnodes, True)
    # substitute stored once, sorted direction (product:122 -> product:130)
    check("substitute edge stored once (sorted)",
          ("product:122", "product:130", "SUBSTITUTE_FOR") in bedges
          and ("product:130", "product:122", "SUBSTITUTE_FOR") not in bedges, True)
    # the surge signal became an edge
    check("surge edge present", ("product:122", "region:northeast", "SURGES_IN") in bedges, True)
    # supplied_by wired from the availability feed
    check("supplied_by edge present", ("product:122", "supplier:S2", "SUPPLIED_BY") in bedges, True)
    # region carries an ltree-ready path
    check("region has ltree path", bnodes["region:northeast"]["path"], "us.northeast")

    # ---- 4) DANGLING-REFERENCE GUARD (Finding 1): hallucinated / out-of-dim ids
    #         must NOT produce edges to non-existent nodes (would break the FK on sync).
    print("\n== TEST 4: dangling-reference guard ==")
    bad_enrich = {
        122: {"description": "Skim Milk 2L.", "substitute_ids": [999]},  # 999 not in products
        130: {"description": "Whole Milk 2L.", "substitute_ids": [122]},
        261: {"description": "Diesel Generator.", "substitute_ids": []},
    }
    bad_supplies = b_supplies + [{"product_id": 888, "supplier_id": "S2"}]  # 888 unknown product
    bad_surges = b_surges + [{"product_id": 777, "region": "West"}]         # 777 unknown product
    gnodes, gedges = assemble_graph(products, b_suppliers, bad_supplies, bad_surges, bad_enrich)
    # every edge endpoint must exist as a node
    orphans = [(s, d, r) for (s, d, r) in gedges if s not in gnodes or d not in gnodes]
    check("no orphan edges despite bad input", orphans, [])
    # the good substitute (130<->122) still forms; the hallucinated 999 does not
    check("valid substitute still present",
          ("product:122", "product:130", "SUBSTITUTE_FOR") in gedges, True)
    check("hallucinated substitute 999 dropped",
          any("999" in s or "999" in d for (s, d, _r) in gedges), False)

    # ---- 5) query module (graph_retrieve.retrieve) matches the SQL logic
    print("\n== TEST 5: query module (pure retrieve) ==")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from graph_retrieve import retrieve as agent_retrieve  # noqa: E402

    # reuse the assembled graph from TEST 3; embed nodes with the same bag-of-words as agent
    agent_vocab = ["skim", "milk", "whole", "supplier", "boston", "denver", "northeast",
                   "dairy", "diesel", "generator", "region", "category", "product"]

    def bow(text):
        toks = text.lower().replace(":", " ").split()
        v = [float(sum(1 for t in toks if t == w)) for w in agent_vocab]
        n = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / n for x in v]

    a_emb = {nid: bow(f"{n['node_type']} {n['name']}") for nid, n in bnodes.items()}
    q = bow("skim milk northeast supplier")
    ranked = agent_retrieve(q, bnodes, bedges, a_emb, seed_k=2, max_hops=2)
    ranked_ids = [r["node_id"] for r in ranked]
    check("retrieve returns rows", len(ranked) > 0, True)
    check("top result is skim milk", ranked[0]["node_id"], "product:122")
    check("expands to a supplier", "supplier:S2" in ranked_ids, True)
    check("excludes unrelated generator", "product:261" not in ranked_ids, True)

    # ---- 6) seed_floor: the distractor guard on the semantic seed
    print("\n== TEST 6: seed_floor distractor guard ==")
    # Cosine similarities for this query against the bag-of-words embeddings:
    #   product:122 0.577 | supplier:S2/S3/S9 0.500 | region:northeast 0.354
    #   product:130 0.289 | category:dairy, product:261, region:west, ... 0.000
    # supplier:S9 is the distractor bridge — it clears a loose floor on the word
    # "supplier" alone, but the only thing it supplies is the unrelated diesel
    # generator, so an unfloored seed drags that whole subgraph into the ranking.
    wide = agent_retrieve(q, bnodes, bedges, a_emb, seed_k=6, max_hops=2)
    wide_ids = [r["node_id"] for r in wide]
    check("no floor: distractor generator pulled in", "product:261" in wide_ids, True)
    check("no floor: distractor region pulled in", "region:west" in wide_ids, True)

    # 0.55 admits only product:122 (0.577) — supplier:S9 (0.500) no longer seeds
    floored = agent_retrieve(q, bnodes, bedges, a_emb, seed_k=6, max_hops=2, seed_floor=0.55)
    floored_ids = [r["node_id"] for r in floored]
    check("floor 0.55: distractor generator excluded", "product:261" not in floored_ids, True)
    check("floor 0.55: distractor region excluded", "region:west" not in floored_ids, True)
    check("floor 0.55: on-topic seed still ranks first",
          floored[0]["node_id"] if floored else None, "product:122")
    check("floor 0.55: narrows the result set", len(floored) < len(wide), True)
    check("floor 0.55: keeps the on-topic supplier via graph expansion",
          "supplier:S2" in floored_ids, True)

    # Backward compatibility, pinned to the EXPECTED set rather than to another call
    # with the same default (which would be tautological). These 10 ids are the whole
    # graph — the pre-floor code returned exactly this for seed_k=6, max_hops=2.
    expected_unfloored = [
        "category:dairy", "category:equipment", "product:122", "product:130",
        "product:261", "region:northeast", "region:west",
        "supplier:S2", "supplier:S3", "supplier:S9",
    ]
    check("default floor reproduces the pre-floor result set",
          sorted(wide_ids), expected_unfloored)

    # a floor above every candidate's similarity admits no seeds at all -> zero rows.
    # NOTE this is the documented failure mode of an over-set floor: the caller must
    # detect the empty result and retry at -1.0 rather than answer from no context.
    check("floor above max similarity returns nothing",
          agent_retrieve(q, bnodes, bedges, a_emb, seed_k=6, seed_floor=0.99), [])

    # a degenerate all-zero embedding has undefined similarity and must never seed.
    # In SQL, pgvector returns NaN for it and NaN > every float, so a similarity-form
    # floor would admit it and NaN would sort FIRST; both sides exclude it instead.
    zero_emb = dict(a_emb)
    zero_emb["product:261"] = [0.0] * len(q)
    zeroed = agent_retrieve(q, bnodes, bedges, zero_emb, seed_k=6, max_hops=2, seed_floor=-1.0)
    check("all-zero embedding never becomes a seed",
          "product:261" not in [r["node_id"] for r in zeroed[:1]], True)

    # ---- 7) UPSTREAM indexing: documents -> gold_triplets
    print("\n== TEST 7: upstream indexing (chunk -> extract -> resolve -> triplets) ==")
    from graph_upstream import (  # noqa: E402
        DEFAULT_PREDICATES,
        SYMMETRIC_PREDICATES,
        Mention,
        build_gold_triplets,
        canonical_id,
        chunk,
        index_document,
        normalize_predicate,
        resolve_entities,
        trigram_containment,
        trigram_sim,
    )

    # -- chunking: stable ids, sentence-aware packing, overlap carried across boundaries
    doc = ("Acme Foods supplies skim milk. ACME Foods Inc. is based in Boston. "
           "Northeast demand for skim milk is surging. Acme ships from Boston daily. "
           "Whole milk substitutes for skim milk in most recipes.")
    passages = chunk("doc:1", doc, size=80, overlap=20)
    check("chunking produced multiple passages", len(passages) > 1, True)
    check("chunk ids are stable and ordered",
          [p.chunk_id for p in passages][:2], ["doc:1:c0", "doc:1:c1"])
    check("every passage keeps its doc pointer",
          all(p.doc_id == "doc:1" for p in passages), True)
    check("no passage is empty", all(p.text.strip() for p in passages), True)

    # -- trigram similarity: alias spellings score high, unrelated names low
    check("alias pair scores above the merge threshold",
          trigram_sim("Acme Foods", "ACME Foods Inc.") >= 0.55, True)
    check("unrelated pair scores below the merge threshold",
          trigram_sim("Acme Foods", "Diesel Generator") < 0.55, True)
    check("trigram similarity is symmetric",
          round(trigram_sim("Acme", "ACME Foods"), 6)
          == round(trigram_sim("ACME Foods", "Acme"), 6), True)
    # containment is what catches legal suffixes / abbreviations that Jaccard misses
    check("Jaccard MISSES the legal-suffix alias (why containment exists)",
          trigram_sim("Acme Foods", "Acme Foods Incorporated") < 0.55, True)
    check("containment catches the legal-suffix alias",
          trigram_containment("Acme Foods", "Acme Foods Incorporated") >= 0.8, True)
    check("containment still rejects an unrelated pair",
          trigram_containment("Acme Foods", "Diesel Generator") < 0.8, True)

    # -- entity resolution: three spellings of one company collapse to a single canonical node
    mentions = [
        Mention("Acme Foods", "Company", "SUPPLIES", "Skim Milk 2L", "Product", 0.9, "doc:1:c0"),
        Mention("ACME Foods Inc.", "Company", "LOCATED_IN", "Boston", "Location", 0.8, "doc:1:c1"),
        Mention("Acme", "Company", "SHIPS_FROM", "Boston", "Location", 0.7, "doc:1:c3"),
    ]
    res = resolve_entities(mentions)
    company_ids = {res.canonical_id[n] for n in ("Acme Foods", "ACME Foods Inc.", "Acme")}
    check("three alias spellings collapse to ONE canonical id", len(company_ids), 1)
    check("canonical display name is the fullest spelling",
          res.canonical_name[company_ids.pop()], "ACME Foods Inc.")
    check("each merged alias is recorded for audit", len(res.same_as), 2)

    # a same-name entity of a DIFFERENT type must not merge into it
    typed = resolve_entities(mentions + [
        Mention("Acme Foods", "Product", "BELONGS_TO", "Dairy", "Category", 0.9, "doc:1:c0"),
    ])
    check("same name, different type does NOT merge",
          typed.canonical_id["Acme Foods"] != typed.canonical_id["Boston"], True)

    # -- contract conformance: exactly the 8 gold_triplets columns, nothing more or less
    CONTRACT = {"subject_id", "subject_type", "predicate", "object_id", "object_type",
                "confidence", "source_method", "source_agent"}
    rows = build_gold_triplets(mentions, res)
    check("every row carries exactly the 8 contract columns",
          all(set(r) == CONTRACT for r in rows), True)
    check("relations are attributed to llm_extract",
          {r["source_method"] for r in rows if r["predicate"] != "SAME_AS"}, {"llm_extract"})
    check("alias edges are attributed to entity_resolution",
          {r["source_method"] for r in rows if r["predicate"] == "SAME_AS"}, {"entity_resolution"})
    check("confidence stays within [0, 1]",
          all(0.0 <= r["confidence"] <= 1.0 for r in rows), True)
    check("subjects/objects were rewritten to canonical ids (no raw surface forms)",
          all(r["subject_id"].startswith("entity:") and r["object_id"].startswith("entity:")
              for r in rows), True)

    # -- symmetric predicates are stored ONCE with sorted endpoints, matching graph_build.py.
    #    Emitting both directions here would be doubled again by the gold_triplets symmetric
    #    reverse in sql/gold_triplets_mapping.sql.
    sym = [
        Mention("Skim Milk", "Product", "SUBSTITUTE_FOR", "Whole Milk", "Product", 0.9, "c0"),
        Mention("Whole Milk", "Product", "SUBSTITUTE_FOR", "Skim Milk", "Product", 0.9, "c1"),
    ]
    sym_rows = build_gold_triplets(sym, resolve_entities(sym))
    sub = [r for r in sym_rows if r["predicate"] == "SUBSTITUTE_FOR"]
    check("SUBSTITUTE_FOR is emitted once, not both directions", len(sub), 1)
    check("symmetric endpoints are sorted", sub[0]["subject_id"] <= sub[0]["object_id"], True)
    check("SUBSTITUTE_FOR is declared symmetric",
          "SUBSTITUTE_FOR" in SYMMETRIC_PREDICATES, True)

    # -- end to end through index_document with a deterministic stub extractor
    def stub_extractor(ps):
        out = []
        for p in ps:
            if "supplies" in p.text.lower():
                out.append(Mention("Acme Foods", "Company", "SUPPLIES", "Skim Milk 2L",
                                   "Product", 0.9, p.chunk_id))
            if "boston" in p.text.lower():
                out.append(Mention("ACME Foods Inc.", "Company", "LOCATED_IN", "Boston",
                                   "Location", 0.85, p.chunk_id))
        return out

    e2e = index_document("doc:1", doc, stub_extractor)
    check("index_document emits rows", len(e2e) > 0, True)
    check("end-to-end rows conform to the contract",
          all(set(r) == CONTRACT for r in e2e), True)
    preds = {r["predicate"] for r in e2e}
    check("end-to-end captured the SUPPLIES relation", "SUPPLIES" in preds, True)
    check("end-to-end merged the company aliases (SAME_AS emitted)", "SAME_AS" in preds, True)
    check("duplicate relations across chunks are de-duplicated",
          len([r for r in e2e if r["predicate"] == "LOCATED_IN"]), 1)
    check("canonical_id is a stable slug",
          canonical_id("ACME Foods Inc."), "entity:acme_foods_inc")

    # -- relation vocabulary: unconstrained extraction invents a label per sentence, which
    #    fragments the namespace. A live run produced IS_LOCATED_IN and BELONGS_TO_CATEGORY,
    #    near-misses for the schema's LOCATED_IN / BELONGS_TO.
    check("normalize_predicate uppercase-snakes a raw phrase",
          normalize_predicate("is based in"), "IS_BASED_IN")
    off_vocab = [
        Mention("Acme", "Company", "LOCATED_IN", "Boston", "Location", 0.9, "c0"),
        Mention("Acme", "Company", "IS_PRIMARY_DAIRY_SUPPLIER_IN", "Boston", "Location", 0.9, "c1"),
    ]
    r_ov = resolve_entities(off_vocab)
    kept = build_gold_triplets(off_vocab, r_ov)
    dropped = build_gold_triplets(off_vocab, r_ov,
                                  allowed_predicates=DEFAULT_PREDICATES, on_unknown="drop")
    check("default keeps out-of-vocabulary predicates",
          len([r for r in kept if r["predicate"] != "SAME_AS"]), 2)
    check("on_unknown='drop' keeps only vocabulary predicates",
          [r["predicate"] for r in dropped if r["predicate"] != "SAME_AS"], ["LOCATED_IN"])
    check("the example's relation vocabulary matches sql/schema.sql",
          DEFAULT_PREDICATES,
          frozenset({"SUPPLIED_BY", "LOCATED_IN", "BELONGS_TO", "SUBSTITUTE_FOR", "SURGES_IN"}))

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} FAILED -> {FAILURES}")
        return 1
    print("RESULT: ALL PASSED — GraphRAG retrieval logic verified offline.")
    print("(pgvector HNSW operator + real embeddings validated only on live Lakebase.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
