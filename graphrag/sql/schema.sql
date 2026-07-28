-- GraphRAG on Lakebase — served graph schema (real Postgres / pgvector)
-- ---------------------------------------------------------------------------
-- This is the SERVE-side schema: what the graph + embeddings look like once
-- synced from Unity Catalog into Lakebase Postgres for low-latency retrieval.
-- Runs on Databricks Lakebase (managed Postgres 16/17). Uses only extensions
-- verified as supported on Lakebase: vector (pgvector 0.8.0), ltree, pg_trgm.
-- There is NO Apache AGE / native graph engine — the graph is relational
-- (nodes + edges tables) and traversal is done with recursive CTEs.
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS vector;    -- pgvector: embeddings + HNSW
CREATE EXTENSION IF NOT EXISTS ltree;     -- hierarchical paths (category trees, region rollups)
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- fuzzy entity linking on names

CREATE SCHEMA IF NOT EXISTS graph;

-- --------------------------------------------------------------------- nodes
-- One row per entity. `type` discriminates Product / Supplier / Region /
-- Category / DemandSignal. Free-form attributes live in JSONB so the same
-- table serves every node type without schema churn.
CREATE TABLE IF NOT EXISTS graph.nodes (
    node_id      TEXT PRIMARY KEY,               -- stable business key, e.g. 'product:122'
    node_type    TEXT NOT NULL,                  -- Product | Supplier | Region | Category | DemandSignal
    name         TEXT NOT NULL,                  -- human label, e.g. 'Skim Milk 2L'
    props        JSONB NOT NULL DEFAULT '{}',    -- type-specific attributes
    path         LTREE                           -- optional hierarchy (e.g. region: 'us.northeast.boston')
);

CREATE INDEX IF NOT EXISTS nodes_type_idx  ON graph.nodes (node_type);
CREATE INDEX IF NOT EXISTS nodes_name_trgm ON graph.nodes USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS nodes_path_gist ON graph.nodes USING gist (path);

-- --------------------------------------------------------------------- edges
-- Directed, typed relationships. Undirected concepts (SUBSTITUTE_FOR) are
-- stored once and traversed in both directions by the retrieval query.
CREATE TABLE IF NOT EXISTS graph.edges (
    src_id   TEXT NOT NULL REFERENCES graph.nodes (node_id),
    dst_id   TEXT NOT NULL REFERENCES graph.nodes (node_id),
    rel      TEXT NOT NULL,                      -- SUPPLIED_BY | LOCATED_IN | BELONGS_TO | SUBSTITUTE_FOR | SURGES_IN
    props    JSONB NOT NULL DEFAULT '{}',        -- edge attributes: cost, lead_time_days, surge_ratio, ...
    PRIMARY KEY (src_id, dst_id, rel)
);

CREATE INDEX IF NOT EXISTS edges_src_rel_idx ON graph.edges (src_id, rel);
CREATE INDEX IF NOT EXISTS edges_dst_rel_idx ON graph.edges (dst_id, rel);

-- ---------------------------------------------------------------- embeddings
-- Node embeddings for the semantic-seed step. Dimension must match the
-- embedding model (e.g. 1024 for databricks-gte-large-en).
-- HNSW with cosine distance (vector_cosine_ops) for approximate NN search.
CREATE TABLE IF NOT EXISTS graph.node_embeddings (
    node_id    TEXT PRIMARY KEY REFERENCES graph.nodes (node_id),
    embedding  VECTOR(1024) NOT NULL
);

CREATE INDEX IF NOT EXISTS node_embeddings_hnsw
    ON graph.node_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ---------------------------------------------------------------------------
-- Notes
-- * nodes/edges/node_embeddings are populated by the build notebook (entity
--   entity extraction → UC Delta) and synced here via Lakebase synced tables;
--   on the served copy, only reads + index creation are permitted.
-- * Recursive-CTE traversal (see graphrag_retrieval.sql) is well-suited to
--   bounded k-hop operational queries. It is NOT a billion-edge graph-analytics
--   engine — for that, use a dedicated graph system.
-- ---------------------------------------------------------------------------
