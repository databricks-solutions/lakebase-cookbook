"""Pure GraphRAG retrieval logic — the in-memory twin of sql/graphrag_retrieval.sql.

Kept dependency-free so the agent's retrieval step is unit-testable offline and so
mock mode needs no Lakebase. The LIVE path (see graphrag_agent.py) runs the SQL against
Lakebase via pgvector HNSW + recursive CTE; this module reproduces the SAME algorithm
(cosine seed -> k-hop expansion both directions -> blended seed_sim * 0.5^hop score) so
behavior matches and is verifiable without infra.
"""
from __future__ import annotations

import math


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def retrieve(query_embedding, nodes, edges, embeddings, seed_k=2, max_hops=2, limit=25):
    """Mirror of graphrag_retrieval.sql.

    Args:
      query_embedding: list[float]
      nodes: dict node_id -> {"node_type","name","props",...}
      edges: iterable of (src_id, dst_id, rel)
      embeddings: dict node_id -> list[float]
    Returns: list of dicts {node_id,node_type,name,nearest_hop,rels,score} desc by score.
    """
    # 1) semantic seed — top-k by cosine similarity
    sims = sorted(
        ((nid, cosine(query_embedding, emb)) for nid, emb in embeddings.items()),
        key=lambda x: x[1], reverse=True,
    )[:seed_k]

    # undirected adjacency (both directions), mirrors the `adj` CTE
    adj: dict = {}
    for s, d, r in edges:
        adj.setdefault(s, []).append((d, r))
        adj.setdefault(d, []).append((s, r))

    # 2) bounded k-hop walk with per-path cycle guard
    best: dict = {}          # node_id -> best graph_score
    nearest: dict = {}       # node_id -> min hop
    rels: dict = {}          # node_id -> set of via rels
    frontier: list = [(nid, 0, sim, (nid,)) for nid, sim in sims]
    while frontier:
        nid, hop, seed_sim, visited = frontier.pop()
        score = seed_sim * (0.5 ** hop)
        if nid not in best or score > best[nid]:
            best[nid] = score
        if nid not in nearest or hop < nearest[nid]:
            nearest[nid] = hop
        if hop >= max_hops:
            continue
        for nxt, rel in adj.get(nid, []):
            if nxt in visited:
                continue
            rels.setdefault(nxt, set()).add(rel)
            frontier.append((nxt, hop + 1, seed_sim, visited + (nxt,)))

    # 3) assemble + rank
    out = []
    for nid, score in best.items():
        if nid not in nodes:
            continue
        n = nodes[nid]
        out.append({
            "node_id": nid,
            "node_type": n["node_type"],
            "name": n["name"],
            "nearest_hop": nearest[nid],
            "rels": sorted(rels.get(nid, [])),
            "score": round(score, 4),
        })
    out.sort(key=lambda r: r["score"], reverse=True)
    return out[:limit]
