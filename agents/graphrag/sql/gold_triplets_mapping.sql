-- gold_triplets — portable cross-stack triplet shape over the GraphRAG graph
-- ---------------------------------------------------------------------------
-- A knowledge graph is portable across engines (Spark/Python builders, other graph
-- stacks, this Lakebase serve layer) when they all agree on ONE row shape. This view
-- projects the local nodes/edges into that canonical 8-column contract so the same
-- graph can be emitted/consumed elsewhere WITHOUT migrating tables.
--
-- Contract — one row per DIRECTED relationship, exactly 8 columns:
--   subject_id, subject_type, predicate, object_id, object_type, confidence,
--   source_method, source_agent
--
-- It is a *column contract*, not a dependency: nothing here imports an external
-- package, and the underlying nodes/edges tables are unchanged.
--
-- SYMMETRY: graph_build.py stores undirected relations ONCE with sorted endpoints
-- (SUBSTITUTE_FOR), and the retrieval SQL makes them bidirectional at query time in
-- its `adj` CTE. A consumer reading subject -> predicate -> object as directed would
-- therefore miss the reverse — "what substitutes for Whole Milk 2L?" would return
-- nothing even though the Lakebase retrieval path answers it. So this view emits
-- BOTH directions for the symmetric relations listed in `symmetric_rels`, keeping
-- the contract self-contained for directed consumers. Add to that list if you
-- introduce further undirected relations.
--
-- PROVENANCE: if an edge carries confidence/source_method/source_agent in its JSONB
-- props (a richer builder can populate these), those win. Otherwise we derive
-- sensible values from the edge itself — source_method reflects whether the
-- relationship was structured or LLM-inferred (SUBSTITUTE_FOR is the enrichment edge
-- in graph_build.py).
--
-- CONFIDENCE: absent props -> 1.0 (a structured edge we fully trust). Present but
-- unparseable, or numeric-but-outside [0, 1] -> NULL, deliberately NOT 1.0: a
-- consumer filtering `WHERE confidence >= 0.9` must not silently ingest malformed
-- rows as gold. NULL makes the gap visible.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW graph.gold_triplets AS
WITH symmetric_rels AS (
    SELECT unnest(ARRAY['SUBSTITUTE_FOR']) AS rel
),
directed AS (
    SELECT
        e.src_id                                              AS subject_id,
        ns.node_type                                          AS subject_type,
        e.rel                                                 AS predicate,
        e.dst_id                                              AS object_id,
        nd.node_type                                          AS object_type,
        CASE
            -- no props value: a structured edge we fully trust
            WHEN e.props ->> 'confidence' IS NULL THEN 1.0
            -- parseable AND in range: take it (accepts .9, +0.5, 8.5e-1)
            WHEN e.props ->> 'confidence' ~ '^[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?$'
                 AND (e.props ->> 'confidence')::double precision BETWEEN 0 AND 1
                THEN (e.props ->> 'confidence')::double precision
            -- malformed or out of range: NULL, so consumers can see the gap
            ELSE NULL
        END                                                   AS confidence,
        COALESCE(
            e.props ->> 'source_method',
            CASE WHEN e.rel = 'SUBSTITUTE_FOR' THEN 'llm_enrichment' ELSE 'structured' END
        )                                                     AS source_method,
        COALESCE(e.props ->> 'source_agent', 'lakebase-graphrag') AS source_agent
    FROM graph.edges e
    JOIN graph.nodes ns ON ns.node_id = e.src_id
    JOIN graph.nodes nd ON nd.node_id = e.dst_id
)
SELECT * FROM directed
UNION ALL
-- reverse direction for the symmetric relations (stored once, sorted, upstream)
SELECT
    d.object_id    AS subject_id,
    d.object_type  AS subject_type,
    d.predicate,
    d.subject_id   AS object_id,
    d.subject_type AS object_type,
    d.confidence,
    d.source_method,
    d.source_agent
FROM directed d
JOIN symmetric_rels s ON s.rel = d.predicate;

-- Consume from any stack:  SELECT * FROM graph.gold_triplets;
-- Ingest the same shape back into nodes/edges by inserting the subject/object as
-- nodes and (subject_id, object_id, predicate) as an edge (props carrying
-- confidence/source_method/source_agent). NOTE: symmetric predicates appear TWICE
-- here by design, so de-duplicate them on ingest (sort the endpoints) rather than
-- storing both directions.
