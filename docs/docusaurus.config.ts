import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

const config: Config = {
  title: 'Lakebase Cookbook',
  tagline:
    'Examples and guides to accelerate your Databricks Lakebase projects',
  favicon: 'img/lakebase-icon.png',

  // Future flags, see https://docusaurus.io/docs/api/docusaurus-config#future
  future: {
    v4: true, // Improve compatibility with the upcoming Docusaurus v4
  },

  // Set the production url of your site here
  url: 'https://lakebase-cookbook.com',
  // Set the /<baseUrl>/ pathname under which your site is served
  baseUrl: '/',

  organizationName: 'databricks-solutions',
  projectName: 'lakebase-cookbook',

  onBrokenLinks: 'throw',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          editUrl:
            'https://github.com/databricks-solutions/lakebase-cookbook/edit/main/docs/',
        },
        blog: {
          showReadingTime: true,
          feedOptions: {
            type: ['rss', 'atom'],
            xslt: true,
          },
          onInlineTags: 'warn',
          onInlineAuthors: 'warn',
          onUntruncatedBlogPosts: 'warn',
        },
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  plugins: ['./src/plugins/tailwind-config.js'],

  themeConfig: {
    image: 'img/docusaurus-social-card.jpg',
    colorMode: {
      defaultMode: 'light',
      disableSwitch: true,
      respectPrefersColorScheme: false,
    },
    navbar: {
      title: 'Lakebase Cookbook',
      logo: {
        alt: 'Lakebase Cookbook Logo',
        src: 'img/lakebase-icon.png',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'tutorialSidebar',
          position: 'left',
          label: 'Examples',
        },
        {to: '/why-lakebase', label: 'Why Lakebase', position: 'left'},
        {to: '/archives', label: 'Archives', position: 'left'},
        {to: '/blog', label: 'Blog', position: 'left'},
        {to: '/resources', label: 'Resources', position: 'left'},
        {
          href: 'https://github.com/databricks-solutions/lakebase-cookbook',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            {
              label: 'Introduction',
              to: '/docs/intro',
            },
          ],
        },
        {
          title: 'Lakebase',
          items: [
            {
              label: 'Announcement Blog',
              href: 'https://www.databricks.com/product/lakebase',
            },
            {
              label: 'Documentation',
              href: 'https://docs.databricks.com/aws/en/oltp/',
            },
          ],
        },
        {
          title: 'More',
          items: [
            {
              label: 'Blog',
              to: '/blog',
            },
            {
              label: 'GitHub',
              href: 'https://github.com/databricks-solutions/lakebase-cookbook',
            },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Databricks, Inc. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'sql', 'python'],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
