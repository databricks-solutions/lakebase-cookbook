export interface Resource {
  title: string;
  type: string;
  category: string;
  url: string;
  summary: string;
}

export const RESOURCES: Resource[] = [
  {
    title: 'Lakebase product overview',
    type: 'Documentation',
    category: 'Overview',
    url: 'https://www.databricks.com/product/lakebase',
    summary:
      'Official announcement and product page for Databricks Lakebase, the managed Postgres-compatible OLTP database.',
  },
  {
    title: 'Lakebase / OLTP documentation',
    type: 'Documentation',
    category: 'Overview',
    url: 'https://docs.databricks.com/aws/en/oltp/',
    summary:
      'Official documentation covering Lakebase projects, branches, Postgres roles, synced tables, and the Data API.',
  },
  {
    title: 'Postgres roles in Lakebase',
    type: 'Documentation',
    category: 'Security',
    url: 'https://docs.databricks.com/aws/en/oltp/projects/postgres-roles',
    summary:
      'How to create and manage Postgres roles for users and service principals against a Lakebase project.',
  },
  {
    title: 'Genie Caching example',
    type: 'Code sample',
    category: 'Apps',
    url: 'https://github.com/databricks-solutions/lakebase-cookbook/tree/main/genie_caching',
    summary:
      'A Databricks App that fronts Genie with a Lakebase (pgvector) semantic query cache, deployable via Asset Bundles.',
  },
];
