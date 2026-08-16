-- gold_triplets — portable cross-stack triplet shape over the GraphRAG graph
-- ---------------------------------------------------------------------------
-- A knowledge graph is portable across engines (Spark/Python builders, other graph
-- stacks, this Lakebase serve layer) when they all agree on ONE row shape. This view
-- projects the local nodes/edges into that canonical 8-column contract so the same
-- graph can be emitted/consumed elsewhere WITHOUT migrating tables.
--
-- Contract — one row per relationship, exactly 8 columns:
--   subject_id, subject_type, predicate, object_id, object_type, confidence,
--   source_method, source_agent
--
-- It is a *column contract*, not a dependency: nothing here imports an external
-- package, and the underlying nodes/edges tables are unchanged.
--
-- Provenance columns: if an edge carries confidence/source_method/source_agent in its
-- JSONB props (a richer builder can populate these), those win. Otherwise we derive
-- sensible values from the edge itself — source_method reflects whether the relationship
-- was structured or LLM-inferred (SUBSTITUTE_FOR is the enrichment edge in graph_build.py),
-- and confidence defaults to 1.0. The confidence cast is guarded so a non-numeric props
-- value can never fail the whole view.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW graph.gold_triplets AS
SELECT
    e.src_id                                              AS subject_id,
    ns.node_type                                          AS subject_type,
    e.rel                                                 AS predicate,
    e.dst_id                                              AS object_id,
    nd.node_type                                          AS object_type,
    CASE
        WHEN e.props ->> 'confidence' ~ '^-?[0-9]+(\.[0-9]+)?$'
            THEN (e.props ->> 'confidence')::double precision
        ELSE 1.0
    END                                                   AS confidence,
    COALESCE(
        e.props ->> 'source_method',
        CASE WHEN e.rel = 'SUBSTITUTE_FOR' THEN 'llm_enrichment' ELSE 'structured' END
    )                                                     AS source_method,
    COALESCE(e.props ->> 'source_agent', 'lakebase-graphrag') AS source_agent
FROM graph.edges e
JOIN graph.nodes ns ON ns.node_id = e.src_id
JOIN graph.nodes nd ON nd.node_id = e.dst_id;

-- Consume from any stack:  SELECT * FROM graph.gold_triplets;
-- Ingest the same shape back into nodes/edges by inserting the subject/object as
-- nodes and (subject_id, object_id, predicate) as an edge (props carrying
-- confidence/source_method/source_agent).
