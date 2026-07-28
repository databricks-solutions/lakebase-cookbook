export const SITE = {
  title: 'Lakebase Cookbook',
  tagline: 'Examples and guides to accelerate your Databricks Lakebase projects',
  url: 'https://lakebase-cookbook.com',
  github: 'https://github.com/databricks-solutions/lakebase-cookbook',
};

export const NAV: { label: string; href: string }[] = [
  { label: 'Examples', href: '/docs/' },
  { label: 'Why Lakebase', href: '/why-lakebase/' },
  { label: 'Archives', href: '/archives/' },
  { label: 'Blog', href: '/blog/' },
  { label: 'Resources', href: '/resources/' },
];

export const FOOTER = {
  columns: [
    {
      title: 'Docs',
      links: [
        { label: 'Introduction', href: '/docs/' },
        { label: 'Examples', href: '/docs/' },
        { label: 'Why Lakebase', href: '/why-lakebase/' },
      ],
    },
    {
      title: 'Lakebase',
      links: [
        { label: 'Announcement Blog', href: 'https://www.databricks.com/product/lakebase' },
        { label: 'Documentation', href: 'https://docs.databricks.com/aws/en/oltp/' },
      ],
    },
    {
      title: 'More',
      links: [
        { label: 'Blog', href: '/blog/' },
        { label: 'Resources', href: '/resources/' },
        { label: 'GitHub', href: 'https://github.com/databricks-solutions/lakebase-cookbook' },
      ],
    },
  ],
};
