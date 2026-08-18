-- Upstream indexing — the two steps that need a workspace (Databricks AI Functions)
-- ---------------------------------------------------------------------------
-- graph_upstream.py covers chunking, entity resolution and triplet assembly in pure Python so
-- the logic is testable with no infra. Parse and extract cannot be: they need
-- `ai_parse_document` and a chat endpoint. Run these in a workspace with AI Functions
-- available, then feed the extracted triples into graph_upstream.resolve_entities() and
-- build_gold_triplets().
--
-- Substitute the bundle variables (see databricks.yml) before running:
--   ${var.catalog}, ${var.schema}, ${var.docs_volume}, ${var.chat_endpoint}
--
-- Cost note: step 3 calls the chat endpoint once per passage. Extraction dominates the cost of
-- building a graph this way, so start on a small document set and check the triples look right
-- before pointing it at a whole corpus.
-- ---------------------------------------------------------------------------

-- 1) PARSE — unstructured files (PDF/DOCX/HTML) in a Volume -> text.
--    NOTE ON THE OUTPUT SHAPE (verified against a live workspace): ai_parse_document returns
--    schema **version 2.0**, whose text lives in `document.elements[].content` with a `type` per
--    element. There is NO `document.text` field — reading `parsed:document.text` yields NULL and
--    the whole pipeline silently produces nothing. Concatenate the text elements instead.
CREATE OR REPLACE TABLE ${var.catalog}.${var.schema}.doc_text AS
SELECT
    path AS doc_id,
    concat_ws('\n\n', transform(
        filter(
            from_json(
                to_json(ai_parse_document(content):document.elements),
                'ARRAY<STRUCT<content:STRING, type:STRING, id:INT>>'
            ),
            e -> e.type = 'text'          -- also 'table', 'figure', ... — include what you need
        ),
        e -> e.content
    )) AS text
FROM READ_FILES(
    '/Volumes/${var.catalog}/${var.schema}/${var.docs_volume}/',
    format => 'binaryFile'
);

-- 2) CHUNK — passages with stable ids and a source pointer.
--    This is the SQL mirror of graph_upstream.chunk(). It splits on sentence boundaries; the
--    Python version additionally packs sentences up to `size` with `overlap` carry-over, so
--    prefer it when passage size matters to your extraction quality.
CREATE OR REPLACE TABLE ${var.catalog}.${var.schema}.passages AS
SELECT
    doc_id,
    concat(doc_id, ':c', cast(p.pos AS string)) AS chunk_id,
    p.col                                       AS text
FROM ${var.catalog}.${var.schema}.doc_text
LATERAL VIEW posexplode(
    split(text, '(?<=[.!?])\\s+')
) AS p
-- Drop empty passages: split() on text with trailing whitespace yields an empty trailing
-- element, and step 3 bills a model call per row — so an empty passage is a paid no-op.
WHERE nullif(trim(p.col), '') IS NOT NULL;

-- Surface parse failures rather than letting documents vanish. A file with a non-empty
-- error_status produces NULL text and would silently disappear from `passages`.
SELECT doc_id, error_status
FROM ${var.catalog}.${var.schema}.doc_text
WHERE error_status IS NOT NULL OR nullif(trim(text), '') IS NULL;

-- 3) EXTRACT — typed triples per passage via ai_query with a constrained response schema.
--    The schema keeps the model inside the entity types you allow and keeps the output
--    parseable; the prompt tells it to emit only relations the text actually states, which is
--    what keeps a knowledge graph from filling with plausible-sounding fabrications.
--
--    NOTE ON THE RESPONSE FORMAT (verified against a live workspace): `ai_query` rejects a DDL
--    string whose TOP-LEVEL field is an array —
--      responseFormat => 'STRUCT<triples: ARRAY<...>>'
--    fails with AI_FUNCTION_UNSUPPORTED_RESPONSE_FORMAT.DDL_STRING ("The top-level field
--    `triples` should be StructType, but found: ArrayType"). Use the JSON-schema form to
--    constrain the model, then `from_json` with the DDL string to type the result.
CREATE OR REPLACE TABLE ${var.catalog}.${var.schema}.raw_triplets AS
SELECT
    chunk_id,
    from_json(
        ai_query(
            '${var.chat_endpoint}',
            concat(
                'Extract factual (subject, subject_type, predicate, object, object_type, ',
                'confidence) triples from the text. Use only these entity types: Product, ',
                'Supplier, Region, Category. Use ONLY these predicates: SUPPLIED_BY, ',
                'LOCATED_IN, BELONGS_TO, SUBSTITUTE_FOR, SURGES_IN — if a stated relation ',
                'fits none of them, omit it rather than inventing a label. Emit only relations ',
                'the text explicitly states; if the text states none, return an empty array. ',
                'Text: ', text
            ),
            -- `required` + `additionalProperties:false` matter: without them the model may
            -- legally omit `subject` or `confidence`, from_json yields NULLs, and the
            -- downstream handoff receives rows it cannot resolve. `confidence` is bounded to
            -- [0, 1] because gold_triplets_mapping.sql NULLs out-of-range values — a model
            -- answering 95 instead of 0.95 would silently lose its provenance.
            responseFormat => '{"type":"json_schema","json_schema":{"name":"extraction",
                "schema":{"type":"object","additionalProperties":false,
                "required":["triples"],"properties":{"triples":{"type":"array","items":
                {"type":"object","additionalProperties":false,
                "required":["subject","subject_type","predicate","object","object_type",
                "confidence"],"properties":{"subject":{"type":"string"},
                "subject_type":{"type":"string"},"predicate":{"type":"string"},
                "object":{"type":"string"},"object_type":{"type":"string"},
                "confidence":{"type":"number","minimum":0,"maximum":1}}}}}},"strict":true}}'
        ),
        'STRUCT<triples: ARRAY<STRUCT<subject:STRING, subject_type:STRING, predicate:STRING,
                object:STRING, object_type:STRING, confidence:DOUBLE>>>'
    ).triples AS triples
FROM ${var.catalog}.${var.schema}.passages;

-- Flatten to one row per triple. Pinning the predicate list in the prompt above is what keeps
-- edge labels stable: left free, the model invents a label per sentence. A live run over two
-- short documents produced SUPPLIES_TO_RETAILERS_ACROSS, OPERATES_DISTRIBUTION_CENTER_IN,
-- IS_LOCATED_IN and BELONGS_TO_CATEGORY — the last two near-misses for LOCATED_IN and
-- BELONGS_TO. Belt and braces: graph_upstream.build_gold_triplets(allowed_predicates=...,
-- on_unknown="drop") filters anything that still slips through.
CREATE OR REPLACE TABLE ${var.catalog}.${var.schema}.mentions AS
SELECT
    chunk_id,
    t.subject, t.subject_type, t.predicate, t.object, t.object_type, t.confidence
FROM ${var.catalog}.${var.schema}.raw_triplets
LATERAL VIEW explode(triples) AS t;

-- 3b) UNPIVOT to surface forms. Entity resolution compares *names*, but a mention carries
--     TWO of them (subject and object), so flatten before blocking. This is the table step 4
--     reads; without it step 4 has no `name`/`entity_type` column to work with.
CREATE OR REPLACE TABLE ${var.catalog}.${var.schema}.mention_surfaces AS
SELECT DISTINCT
    md5(concat_ws('|', name, entity_type)) AS mention_id,
    name,
    entity_type
FROM (
    SELECT subject AS name, subject_type AS entity_type
    FROM ${var.catalog}.${var.schema}.mentions
    UNION ALL
    SELECT object AS name, object_type AS entity_type
    FROM ${var.catalog}.${var.schema}.mentions
)
WHERE nullif(trim(name), '') IS NOT NULL;

-- 4) ENTITY-RESOLUTION BLOCKING (on Lakebase) — generate candidate pairs with pg_trgm rather
--    than comparing every surface form to every other. The merge itself (union-find plus
--    canonical selection) is graph_upstream.resolve_entities().
--
--    Requires on the Lakebase side:  CREATE EXTENSION IF NOT EXISTS pg_trgm;
--    plus a trigram index:           CREATE INDEX ... USING gin (name gin_trgm_ops);
--    (graph.nodes already has nodes_name_trgm in sql/schema.sql — mirror it for mentions.)
--
--    IMPORTANT: block on BOTH measures. `similarity()` is Jaccard, which misses exactly the
--    alias case that matters — "Acme Foods" vs "Acme Foods Incorporated" scores 0.42 and would
--    never be proposed as a candidate, so resolve_entities() would never get the chance to
--    merge it and its containment path would be unreachable. `word_similarity()` (operator
--    `<%`) is the containment measure; it is asymmetric, so take the greatest of both
--    directions. This mirrors trigram_sim + trigram_containment in graph_upstream.py.
SELECT
    a.mention_id AS a_id,
    b.mention_id AS b_id,
    a.name       AS a_name,
    b.name       AS b_name,
    similarity(a.name, b.name)                                                AS jaccard_sim,
    greatest(word_similarity(a.name, b.name), word_similarity(b.name, a.name)) AS containment
FROM mention_surfaces a
JOIN mention_surfaces b
  ON a.entity_type = b.entity_type      -- only same-type forms are candidates
 AND a.mention_id < b.mention_id        -- each unordered pair once
 AND (a.name % b.name OR a.name <% b.name OR b.name <% a.name)
WHERE similarity(a.name, b.name) >= 0.55
   OR greatest(word_similarity(a.name, b.name), word_similarity(b.name, a.name)) >= 0.8;

-- The resolved triples land in the 8-column gold_triplets contract
-- (sql/gold_triplets_mapping.sql), so everything downstream — embeddings, HNSW, the recursive
-- CTE in sql/graphrag_retrieval.sql — is unchanged.
