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
    date: '2025',
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
