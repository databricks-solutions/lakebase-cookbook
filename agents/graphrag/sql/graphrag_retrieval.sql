-- GraphRAG hybrid retrieval on Lakebase (real Postgres / pgvector)
-- ---------------------------------------------------------------------------
-- The core of GraphRAG: seed with SEMANTIC similarity (pgvector), then EXPAND
-- along relationships (recursive CTE) to pull in graph-connected context that
-- pure vector search would miss. Returns a ranked context set for the agent
-- to synthesize an answer from.
--
-- Parameters (bind at call time from the agent):
--   :query_embedding  VECTOR(1024)  -- embedding of the user question (from your embeddings endpoint)
--   :seed_k           INT           -- how many semantic seed nodes (e.g. 5)
--   :max_hops         INT           -- traversal depth bound (e.g. 2)
--   :seed_floor       FLOAT         -- min cosine similarity a seed must clear. Cosine ranges
--                                      [-1, 1], so -1.0 keeps ALL seeds (same as no floor).
--                                      Raise it to guard against distractor
--                                      pollution: under heavy off-topic content, weak seeds
--                                      drag unrelated subgraphs in and dilute the ranking.
--
-- Distance: cosine. pgvector '<=>' returns cosine DISTANCE (0=identical),
-- so similarity = 1 - distance. HNSW index (vector_cosine_ops) backs the ORDER BY.
-- ---------------------------------------------------------------------------

WITH RECURSIVE
-- 1) SEMANTIC SEED — nearest nodes to the question by embedding.
seed AS (
    SELECT
        e.node_id,
        1 - (e.embedding <=> :query_embedding) AS similarity
    FROM graph.node_embeddings e
    WHERE 1 - (e.embedding <=> :query_embedding) >= :seed_floor   -- drop weak seeds (distractor guard; -1.0 = keep all)
    ORDER BY e.embedding <=> :query_embedding      -- HNSW ANN scan
    LIMIT :seed_k
),

-- Undirected adjacency: every edge is walkable in both directions so that
-- undirected relations (e.g. SUBSTITUTE_FOR) and reverse questions ("what
-- depends on supplier X") both work. Materialized once, then joined in the
-- recursive term with a PLAIN JOIN (not LATERAL) — Postgres restricts the
-- recursive self-reference, and a plain join against this view is the
-- portable form (and the one the offline smoke test validates).
adj AS (
    SELECT src_id AS from_id, dst_id AS next_id, rel FROM graph.edges
    UNION ALL
    SELECT dst_id AS from_id, src_id AS next_id, rel FROM graph.edges
),

-- 2) GRAPH EXPANSION — walk edges out from each seed up to :max_hops.
--    Track depth to bound the walk and a per-path visited list to stop cycles.
walk AS (
    -- base: the seeds themselves at hop 0, carrying their semantic score
    SELECT
        s.node_id                              AS node_id,
        0                                      AS hop,
        s.similarity                           AS seed_similarity,
        s.node_id                              AS seed_id,
        ARRAY[s.node_id]                       AS visited,
        NULL::TEXT                             AS via_rel
    FROM seed s

    UNION ALL

    -- step: follow any edge touching the frontier node, either direction
    SELECT
        adj.next_id                            AS node_id,
        w.hop + 1                              AS hop,
        w.seed_similarity                      AS seed_similarity,
        w.seed_id                              AS seed_id,
        w.visited || adj.next_id               AS visited,
        adj.rel                                AS via_rel
    FROM walk w
    JOIN adj ON adj.from_id = w.node_id
    WHERE w.hop < :max_hops
      AND NOT (adj.next_id = ANY(w.visited))   -- per-path cycle guard (dedup happens in `scored`)
),

-- 3) SCORE — a node's relevance combines its best seed similarity with a
--    hop-distance decay (closer to a seed = more relevant). If a node is
--    reachable from multiple seeds, keep its strongest path.
scored AS (
    SELECT
        node_id,
        MAX(seed_similarity * POWER(0.5, hop)) AS graph_score,
        MIN(hop)                               AS nearest_hop,
        ARRAY_AGG(DISTINCT via_rel) FILTER (WHERE via_rel IS NOT NULL) AS rels
    FROM walk
    GROUP BY node_id
)

-- 4) ASSEMBLE CONTEXT — join back to node detail, rank by blended score.
SELECT
    n.node_id,
    n.node_type,
    n.name,
    n.props,
    s.nearest_hop,
    s.rels,
    ROUND(s.graph_score::numeric, 4) AS score
FROM scored s
JOIN graph.nodes n ON n.node_id = s.node_id
ORDER BY s.graph_score DESC
LIMIT 25;
