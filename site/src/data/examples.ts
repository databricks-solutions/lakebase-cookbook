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
    tag: 'AI Memory',
    title: 'Durable memory for agents',
    bracket: 'Postgres-backed short- and long-term memory',
    description:
      'Give agents persistent, queryable memory backed by Lakebase Postgres — conversation history, facts, and embeddings on one governed store.',
    href: '/docs/examples/ai-memory/',
    status: 'soon',
  },
  {
    tag: 'Apps',
    title: 'Full-stack apps on Lakebase',
    bracket: 'low-latency reads, transactional writes',
    description:
      'Build interactive applications that read and write operational data with single-digit-millisecond latency, colocated with your lakehouse.',
    href: '/docs/examples/apps/',
    status: 'soon',
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
