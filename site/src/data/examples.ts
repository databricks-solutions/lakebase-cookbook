export interface ExampleCard {
  category: string;
  tag: string;
  title: string;
  bracket: string;
  description: string;
  href: string;
  status: 'ready' | 'soon';
}

// Order categories appear on the landing page. Categories not listed fall to
// the end. Keep in sync with CATEGORY_POSITIONS in src/lib/docs.ts.
export const CATEGORY_ORDER = [
  'Agents',
  'Developer Experience',
  'Apps',
  'Data',
];

export const EXAMPLES: ExampleCard[] = [
  {
    category: 'Agents',
    tag: 'GraphRAG',
    title: 'Knowledge-graph RAG on Lakebase',
    bracket: 'pgvector seed, recursive-CTE graph traversal',
    description:
      'Augment RAG with a knowledge graph stored in Lakebase. A pgvector semantic seed finds entry nodes, a recursive CTE traverses relationships out to k hops, and a blended score ranks the expanded context — surfacing connections flat retrieval misses.',
    href: '/docs/examples/graphrag/',
    status: 'ready',
  },
  {
    category: 'Agents',
    tag: 'AI Memory',
    title: 'Durable memory for agents',
    bracket: 'Postgres-backed short- and long-term memory',
    description:
      'Give agents persistent, queryable memory backed by Lakebase Postgres — conversation history, facts, and embeddings on one governed store.',
    href: '/docs/examples/ai-memory/',
    status: 'soon',
  },
  {
    category: 'Developer Experience',
    tag: 'Branching CI/CD',
    title: 'Ship schema changes with confidence',
    bracket: 'branch-per-PR, AI impact review, exactly-once deploy',
    description:
      'A GitHub CI/CD workflow that forks a Lakebase branch off production for every PR touching migrations, runs the changed SQL there, and posts an AI impact review before merge — then applies migrations to production exactly once.',
    href: '/docs/examples/branching-cicd/',
    status: 'ready',
  },
  {
    category: 'Apps',
    tag: 'FastAPI App',
    title: 'FastAPI backend on Lakebase',
    bracket: 'Databricks App, OAuth rotation, scale-to-zero pooling',
    description:
      'A Databricks App that serves a Lakebase synced table through a FastAPI REST API — with automatic OAuth token rotation, a scale-to-zero-aware connection pool, and fully bundle-driven provisioning of the project, endpoint, catalog, and synced table.',
    href: '/docs/examples/lakebase-fastapi/',
    status: 'ready',
  },
  {
    category: 'Data',
    tag: 'Feature Store',
    title: 'Online feature serving',
    bracket: 'synced tables → model serving',
    description:
      'Serve features to models with low latency by syncing lakehouse tables into Lakebase — no bespoke online store to build or operate.',
    href: '/docs/examples/feature-store/',
    status: 'soon',
  },
  {
    category: 'Data',
    tag: 'Reverse ETL',
    title: 'Lakehouse → operational store',
    bracket: 'managed sync, no custom pipelines',
    description:
      'Push analytical results back into Lakebase for low-latency serving to applications, without building and maintaining reverse-ETL pipelines.',
    href: '/docs/examples/reverse-etl/',
    status: 'soon',
  },
];
