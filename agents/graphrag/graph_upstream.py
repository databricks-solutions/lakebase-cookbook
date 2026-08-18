"""Upstream indexing: raw document text -> gold_triplets rows.

`graph_build.py` assembles a graph from *structured* dims plus LLM enrichment. This module
covers the phase before that — turning unstructured documents into the same graph shape:

    parse -> chunk -> extract (typed triples) -> entity resolution -> gold_triplets

Parse and extract are the two steps that need a workspace: `ai_parse_document` for files in a
Volume and `ai_query` with a response schema for typed extraction. Both live in
`sql/upstream_ai_functions.sql`. Everything here is pure Python — chunking, trigram entity
resolution and triplet assembly — with extraction behind an `Extractor` protocol so the offline
smoke test drives it deterministically with no infra.

Entity resolution is the part that matters most in practice: the same entity is written many
ways across documents ("Acme", "Acme Foods", "ACME Foods Inc.") and each spelling would
otherwise become its own node, fragmenting the graph exactly where multi-hop retrieval needs it
joined. We block candidates by character-trigram similarity and merge with union-find, mirroring
`pg_trgm` from the serve layer up into the build.

Output lands in the 8-column `gold_triplets` contract (see `sql/gold_triplets_mapping.sql`), so
embeddings and Lakebase sync downstream are unchanged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

# Predicates that are symmetric, i.e. A-rel-B means B-rel-A. graph_build.py stores these ONCE
# with sorted endpoints, and sql/graphrag_retrieval.sql walks them in both directions via its
# `adj` CTE. Upstream must follow the same convention: emitting both directions here would
# double them again when gold_triplets projects its symmetric reverse, so we normalize instead.
SYMMETRIC_PREDICATES = frozenset({"SUBSTITUTE_FOR", "SAME_AS_CANDIDATE"})

# The relation vocabulary this example's graph uses (see sql/schema.sql). Constrain extraction to
# it: left free, an LLM invents a new label per sentence — a live run over two short documents
# produced SUPPLIES_TO_RETAILERS_ACROSS, OPERATES_DISTRIBUTION_CENTER_IN, IS_LOCATED_IN and
# BELONGS_TO_CATEGORY, where the last two are near-misses for LOCATED_IN and BELONGS_TO. Every
# spelling becomes its own edge label, so the relation namespace fragments and the typed-path
# logic in sql/graphrag_retrieval.sql degrades toward an untyped walk. Entity types were already
# constrained by the response schema; predicates need the same treatment.
DEFAULT_PREDICATES = frozenset({
    "SUPPLIED_BY", "LOCATED_IN", "BELONGS_TO", "SUBSTITUTE_FOR", "SURGES_IN",
})


# --------------------------------------------------------------------------- chunk
@dataclass
class Passage:
    chunk_id: str
    doc_id: str
    text: str


def chunk(doc_id: str, text: str, size: int = 240, overlap: int = 40) -> list[Passage]:
    """Split parsed text into overlapping passages with stable ids and a source pointer.

    Sentence-aware: packs whole sentences up to `size` characters, carrying `overlap`
    characters into the next passage so a fact spanning a boundary is not lost.
    """
    sents = re.split(r"(?<=[.!?])\s+", text.strip())
    passages: list[Passage] = []
    buf = ""
    for s in sents:
        if buf and len(buf) + len(s) + 1 > size:
            passages.append(Passage(f"{doc_id}:c{len(passages)}", doc_id, buf.strip()))
            buf = (buf[-overlap:] + " " + s) if overlap else s
        else:
            buf = f"{buf} {s}".strip()
    if buf.strip():
        passages.append(Passage(f"{doc_id}:c{len(passages)}", doc_id, buf.strip()))
    return passages


# --------------------------------------------------------------------------- extract
@dataclass
class Mention:
    """One extracted triple, still carrying raw (unresolved) entity surface forms."""
    subject: str
    subject_type: str
    predicate: str
    object: str
    object_type: str
    confidence: float
    chunk_id: str


class Extractor(Protocol):
    """Turn passages into typed mentions. In production this is `ai_query` with a response
    schema (see sql/upstream_ai_functions.sql); offline it is a deterministic stub."""

    def __call__(self, passages: list[Passage]) -> list[Mention]: ...


# --------------------------------------------------------------------------- entity resolution
def _trigrams(s: str) -> set[str]:
    s = "  " + re.sub(r"[^a-z0-9]+", " ", s.lower()).strip() + "  "
    return {s[i:i + 3] for i in range(len(s) - 2)}


def trigram_sim(a: str, b: str) -> float:
    """Jaccard similarity over character trigrams — the same shape as pg_trgm's `similarity()`."""
    ta, tb = _trigrams(a), _trigrams(b)
    return len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0


def trigram_containment(a: str, b: str) -> float:
    """How completely the SHORTER form is contained in the longer: |A n B| / min(|A|, |B|).

    Mirrors pg_trgm's `word_similarity()`, which scores a string against the most similar
    *portion* of another. Jaccard alone is the wrong tool for entity aliases because it
    penalizes length difference: "Acme Foods" vs "Acme Foods Incorporated" scores 0.42 by
    Jaccard (below any sane threshold) but 0.92 by containment. Legal suffixes and
    abbreviations — Inc., Ltd., Corp., initialisms — are the single most common way the same
    organization appears written differently, so a resolver that misses them fragments the
    graph precisely where multi-hop retrieval needs it joined.
    """
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def canonical_id(name: str) -> str:
    return "entity:" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


@dataclass
class Resolution:
    canonical_id: dict[str, str] = field(default_factory=dict)    # surface form -> canonical id
    canonical_name: dict[str, str] = field(default_factory=dict)  # canonical id -> display name
    same_as: list[tuple[str, str]] = field(default_factory=list)  # (surface, canonical_id) merges


def resolve_entities(mentions: list[Mention], threshold: float = 0.55,
                    containment_threshold: float = 0.8, min_trigrams: int = 4) -> Resolution:
    """Trigram blocking plus union-find: merge same-type surface forms that look like aliases.

    Two forms merge when EITHER measure clears its threshold:
      * `trigram_sim` (Jaccard) >= `threshold` — forms of comparable length;
      * `trigram_containment` >= `containment_threshold` — a short form inside a longer one
        (abbreviations, legal suffixes), which Jaccard systematically misses.

    `min_trigrams` guards the containment path: a very short surface form is trivially contained
    in many longer ones, so forms below this many trigrams (roughly 2 characters) only merge on
    the Jaccard path.

    Canonical display name is the longest surface form in a cluster, on the assumption that the
    fullest spelling ("ACME Foods Inc.") is the most identifying. Only same-type forms merge, so
    a Company and a Product sharing a name stay distinct.

    LIMITATION worth knowing before you point this at a real corpus: containment cannot tell a
    legitimate abbreviation from a genuine short-name collision. "Acme" merging into "Acme
    Foods" is right; "Acme" merging into "Acme Widgets" when they are different companies is
    wrong, and no character-level measure can separate those two cases. On a graph where a bad
    merge is expensive, review the emitted SAME_AS edges (that is why they are written to the
    graph) or add a disambiguating signal such as co-occurring locations or identifiers.
    """
    surfaces: dict[str, str] = {}  # surface -> type (first seen wins)
    for m in mentions:
        surfaces.setdefault(m.subject, m.subject_type)
        surfaces.setdefault(m.object, m.object_type)

    parent: dict[str, str] = {s: s for s in surfaces}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    names = list(surfaces)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            if surfaces[a] != surfaces[b]:
                continue
            if trigram_sim(a, b) >= threshold:
                union(a, b)
            elif (min(len(_trigrams(a)), len(_trigrams(b))) >= min_trigrams
                    and trigram_containment(a, b) >= containment_threshold):
                union(a, b)

    clusters: dict[str, list[str]] = {}
    for s in names:
        clusters.setdefault(find(s), []).append(s)

    res = Resolution()
    for members in clusters.values():
        rep = max(members, key=len)
        cid = canonical_id(rep)
        res.canonical_name[cid] = rep
        for s in members:
            res.canonical_id[s] = cid
            if s != rep:
                res.same_as.append((s, cid))
    return res


# --------------------------------------------------------------------------- assemble
def normalize_predicate(raw: str) -> str:
    """Uppercase-snake a raw predicate ("is based in" -> IS_BASED_IN) without judging it."""
    return re.sub(r"[^A-Z0-9]+", "_", raw.strip().upper()).strip("_")


def build_gold_triplets(mentions: list[Mention], res: Resolution, *,
                        source_agent: str = "graphrag-upstream",
                        allowed_predicates: frozenset[str] | None = None,
                        on_unknown: str = "keep") -> list[dict]:
    """Rewrite mentions onto canonical ids and emit gold_triplets rows.

    Also emits one SAME_AS row per merged alias, so the resolution decision is auditable in the
    graph itself rather than lost in the pipeline — you can always ask why two spellings became
    one node. Symmetric predicates get sorted endpoints (see SYMMETRIC_PREDICATES).

    `source_method` vocabulary: `llm_extract` for an extracted relation, `entity_resolution` for
    a SAME_AS alias edge. The view in sql/gold_triplets_mapping.sql uses `structured` and
    `llm_enrichment` for the graph_build path; all four are valid values of the same column.

    `allowed_predicates` pins the relation vocabulary (see DEFAULT_PREDICATES for why). With
    `on_unknown="drop"` a relation outside the vocabulary is discarded; with the default "keep"
    it is emitted as-is, which is fine for exploration but fragments the namespace at scale.
    Constrain the extraction prompt to the same vocabulary as well — filtering here only cleans
    up what the model already spent tokens producing.
    """
    rows: list[dict] = []
    seen: set = set()
    for m in mentions:
        if (allowed_predicates is not None and on_unknown == "drop"
                and m.predicate not in allowed_predicates):
            continue
        s_id, o_id = res.canonical_id[m.subject], res.canonical_id[m.object]
        s_type, o_type = m.subject_type, m.object_type
        if m.predicate in SYMMETRIC_PREDICATES and s_id > o_id:
            s_id, o_id = o_id, s_id
            s_type, o_type = o_type, s_type
        key = (s_id, m.predicate, o_id)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "subject_id": s_id, "subject_type": s_type, "predicate": m.predicate,
            "object_id": o_id, "object_type": o_type,
            "confidence": round(m.confidence, 4),
            "source_method": "llm_extract", "source_agent": source_agent,
        })
    for surface, cid in res.same_as:
        rows.append({
            "subject_id": canonical_id(surface), "subject_type": "Entity", "predicate": "SAME_AS",
            "object_id": cid, "object_type": "Entity", "confidence": 1.0,
            "source_method": "entity_resolution", "source_agent": source_agent,
        })
    return rows


def index_document(doc_id: str, text: str, extractor: Extractor, *,
                   source_agent: str = "graphrag-upstream",
                   allowed_predicates: frozenset[str] | None = None,
                   on_unknown: str = "keep") -> list[dict]:
    """End to end: chunk -> extract -> resolve -> gold_triplets rows.

    Parse happens upstream of this — pass already-parsed text, e.g. the output of
    `ai_parse_document` (see sql/upstream_ai_functions.sql). Pass
    `allowed_predicates=DEFAULT_PREDICATES, on_unknown="drop"` to pin the relation vocabulary.
    """
    passages = chunk(doc_id, text)
    mentions = extractor(passages)
    res = resolve_entities(mentions)
    return build_gold_triplets(mentions, res, source_agent=source_agent,
                               allowed_predicates=allowed_predicates, on_unknown=on_unknown)
