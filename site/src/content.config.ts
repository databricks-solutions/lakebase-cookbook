import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

const docs = defineCollection({
  loader: glob({ pattern: '**/*.{md,mdx}', base: './src/content/docs' }),
  schema: z.object({
    title: z.string(),
    description: z.string().optional(),
    // Lower numbers sort first in the sidebar. Defaults to 100.
    sidebar_position: z.number().default(100),
    // Optional short label used in the sidebar instead of the full title.
    sidebar_label: z.string().optional(),
    // Category groups examples in the sidebar and on the landing page,
    // e.g. "Agents", "Developer Experience". Omit for ungrouped docs.
    category: z.string().optional(),
    draft: z.boolean().default(false),
  }),
});

export const collections = { docs };
