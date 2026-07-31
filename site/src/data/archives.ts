export type MediaType = 'Video' | 'Blog' | 'Announcement';

export interface ArchiveEntry {
  title: string;
  mediaType: MediaType;
  source: string;
  date: string;
  url: string;
  summary: string;
}

// To add an entry, append to this list and open a pull request.
export const ARCHIVE: ArchiveEntry[] = [
  {
    title: 'From monolith to Lakebase to LTAP: rethinking the database from storage up',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Jun 2026',
    url: 'https://www.databricks.com/blog/lakebase-ltap-rethinking-database-storage',
    summary:
      'Reynold Xin walks through how Lakebase re-architects the database by separating compute from storage — externalizing the write-ahead log and data files into independent SafeKeeper and PageServer services — and introduces LTAP (Lake Transactional/Analytical Processing), which unifies transactions and analytics on a single copy of data at the storage layer.',
  },
  {
    title: 'Inside Lakebase: fully-managed serverless Postgres',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Jun 2026',
    url: 'https://www.youtube.com/watch?v=NqJIyP9rIW8',
    summary:
      'Nikita Shamgunov (VP Engineering, Databricks) introduces Lakebase — a fully-managed, serverless Postgres built natively into the lakehouse — and walks through its architecture: serverless autoscaling, instant branching and rollback, Unity Catalog / Delta integration for zero-ETL access, and cross-cloud disaster recovery.',
  },
  {
    title: 'Safe AI-Driven Development with Lakebase Branches',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Jun 2026',
    url: 'https://www.youtube.com/watch?v=jLX5LBzEDGc',
    summary:
      'A demo of Lakebase’s Git-like, zero-copy database branching: isolated, low-cost sandboxes for schema changes, agentic experimentation, and branch-based CI/CD, letting AI agents safely test against production-like data before promoting changes to production.',
  },
  {
    title: 'How Mastercard standardizes on Lakebase to power agentic operations',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Jun 2026',
    url: 'https://www.youtube.com/watch?v=oyl2XgCpW7E',
    summary:
      'A customer session on how Mastercard standardizes on Lakebase as the operational database powering its agentic workloads, unifying transactional apps and analytics on one governed platform.',
  },
  {
    title: 'Announcing Lakebase Search: agent-native retrieval built into Lakebase Postgres',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Jun 2026',
    url: 'https://www.databricks.com/blog/announcing-lakebase-search-agent-native-retrieval-built-lakebase-postgres',
    summary:
      'Introduces Lakebase Search — hybrid vector and full-text retrieval built into Lakebase Postgres via the native lakebase_vector and lakebase_text extensions — so agents can retrieve context, reason, act, and remember on a single Postgres backend without a separate vector database.',
  },
  {
    title: 'AI Agents That Remember: Building Stateful Systems with Lakebase',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'May 2026',
    url: 'https://www.youtube.com/watch?v=UrIybbk-aY4',
    summary:
      'A walkthrough of using Lakebase as durable memory for AI agents — giving stateful systems persistent, queryable storage for conversation history, facts, and embeddings on managed Postgres.',
  },
  {
    title: 'Data + AI Summit 2026 Keynote — Day 1',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Jun 2026',
    url: 'https://www.youtube.com/watch?v=Qux8E-L1mk8',
    summary:
      'The Data + AI Summit day-one keynote, where Databricks leaders presented the latest Lakebase capabilities, including cross-region and cross-cloud disaster recovery, alongside live product demos.',
  },
  {
    title: 'A New Era of Databases: Lakebase',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Jun 2025',
    url: 'https://www.databricks.com/blog/what-is-a-lakebase',
    summary:
      'The foundational explainer for Lakebase: what a lakebase is, why separating compute from storage on open formats matters, and how it unifies operational and analytical data.',
  },
  {
    title:
      'Databricks Launches Lakebase: a New Class of Operational Database for AI Apps and Agents',
    mediaType: 'Announcement',
    source: 'Databricks Newsroom',
    date: 'Jun 2025',
    url: 'https://www.databricks.com/company/newsroom/press-releases/databricks-launches-lakebase-new-class-operational-database-ai-apps',
    summary:
      "The official launch announcement detailing Lakebase's branching, autoscaling, low-latency high-concurrency performance, and synchronization to and from the lakehouse.",
  },
  {
    title: 'Announcing Lakebase Public Preview',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Jun 2025',
    url: 'https://www.databricks.com/blog/announcing-lakebase-public-preview',
    summary:
      'The public preview announcement, walking through how to get started with Lakebase and the core developer experience.',
  },
  {
    title: 'Databricks Lakebase is now Generally Available',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Feb 2026',
    url: 'https://www.databricks.com/blog/databricks-lakebase-generally-available',
    summary:
      'The general availability milestone for Lakebase, covering production readiness and the capabilities available to all customers.',
  },
  {
    title: 'How the Lakebase Architecture Stays Resilient to Cloud Failures',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: '2025',
    url: 'https://www.databricks.com/blog/how-lakebase-architecture-stays-resilient-cloud-failures',
    summary:
      'A deep dive into the resilience of the Lakebase architecture and how it maintains availability and durability through cloud failures.',
  },
  {
    title: 'Announcing Databricks Lakebase Launch Partners',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Jun 2025',
    url: 'https://www.databricks.com/blog/announcing-databricks-lakebase-launch-partners',
    summary:
      'An overview of the ecosystem of launch partners building on and integrating with Lakebase.',
  },
  {
    title:
      'Databricks Launches LTAP: The First Lake Transactional/Analytical Processing Architecture',
    mediaType: 'Announcement',
    source: 'Databricks Newsroom',
    date: 'Jun 2026',
    url: 'https://www.databricks.com/company/newsroom/press-releases/databricks-launches-ltap-first-lake-transactionalanalytical',
    summary:
      'The announcement of LTAP, unifying transactions, analytics, streaming, and operational data on a single governed copy of storage — the architecture Lakebase builds on.',
  },
];
