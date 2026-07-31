export interface ExampleCard {
  tag: string;
  title: string;
  bracket: string;
  description: string;
  href: string;
  status: 'ready' | 'soon';
}

export const EXAMPLES: ExampleCard[] = [
  {
    tag: 'Genie Caching',
    title: 'Semantic cache in front of Genie',
    bracket: 'pgvector similarity, per-gateway TTL, Genie-compatible REST + MCP',
    description:
      'A Databricks App that fronts Genie with a Lakebase pgvector cache. Repeated or semantically similar questions skip NL→SQL and reuse cached SQL against your warehouse for fresher numbers with less work.',
    href: '/docs/examples/genie-caching/',
    status: 'ready',
  },
  {
    tag: 'GraphRAG',
    title: 'Knowledge-graph RAG on Lakebase',
    bracket: 'pgvector seed, recursive-CTE graph traversal',
    description:
      'Augment RAG with a knowledge graph stored in Lakebase. A pgvector semantic seed finds entry nodes, a recursive CTE traverses relationships out to k hops, and a blended score ranks the expanded context — surfacing connections flat retrieval misses.',
    href: '/docs/examples/graphrag/',
    status: 'ready',
  },
  {
    tag: 'Branching CI/CD',
    title: 'Ship schema changes with confidence',
    bracket: 'branch-per-PR, AI impact review, exactly-once deploy',
    description:
      'A GitHub CI/CD workflow that forks a Lakebase branch off production for every PR touching migrations, runs the changed SQL there, and posts an AI impact review before merge — then applies migrations to production exactly once.',
    href: '/docs/examples/branching-cicd/',
    status: 'ready',
  },
  {
    tag: 'AI Memory',
    title: 'Durable memory for agents',
    bracket: 'Postgres-backed short- and long-term memory',
    description:
      'Give agents persistent, queryable memory backed by Lakebase Postgres — conversation history, facts, and embeddings on one governed store.',
    href: '/docs/examples/ai-memory/',
    status: 'soon',
  },
  {
    tag: 'FastAPI App',
    title: 'FastAPI backend on Lakebase',
    bracket: 'Databricks App, OAuth rotation, scale-to-zero pooling',
    description:
      'A Databricks App that serves a Lakebase synced table through a FastAPI REST API — with automatic OAuth token rotation, a scale-to-zero-aware connection pool, and fully bundle-driven provisioning of the project, endpoint, catalog, and synced table.',
    href: '/docs/examples/lakebase-fastapi/',
    status: 'ready',
  },
  {
    tag: 'Feature Store',
    title: 'Online feature serving',
    bracket: 'synced tables → model serving',
    description:
      'Serve features to models with low latency by syncing lakehouse tables into Lakebase — no bespoke online store to build or operate.',
    href: '/docs/examples/feature-store/',
    status: 'soon',
  },
  {
    tag: 'Reverse ETL',
    title: 'Lakehouse → operational store',
    bracket: 'managed sync, no custom pipelines',
    description:
      'Push analytical results back into Lakebase for low-latency serving to applications, without building and maintaining reverse-ETL pipelines.',
    href: '/docs/examples/reverse-etl/',
    status: 'soon',
  },
];
