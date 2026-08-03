// Shared helpers for the docs section: a flat sorted list (for routing and
// prev/next) and a grouped sidebar. Docs live in `src/content/docs/`, with the
// landing doc at `intro` and example pages under `examples/`.
import { getCollection } from 'astro:content';
import type { CollectionEntry } from 'astro:content';

export type DocEntry = CollectionEntry<'docs'>;

export interface SidebarItem {
  label: string;
  href: string;
}

export interface SidebarGroup {
  label: string | null;
  items: SidebarItem[];
}

// Lower sidebar_position sorts first; ties break on the display label. `intro`
// is always pinned to the very top regardless of its position.
function byOrder(a: DocEntry, b: DocEntry): number {
  if (a.id === 'intro') return -1;
  if (b.id === 'intro') return 1;
  const pa = a.data.sidebar_position ?? 100;
  const pb = b.data.sidebar_position ?? 100;
  if (pa !== pb) return pa - pb;
  const la = a.data.sidebar_label ?? a.data.title;
  const lb = b.data.sidebar_label ?? b.data.title;
  return la.localeCompare(lb);
}

/** All published docs in flat, sorted order (intro first). */
export async function getDocs(): Promise<DocEntry[]> {
  const docs = await getCollection('docs', ({ data }) => !data.draft);
  return docs.sort(byOrder);
}

function href(id: string): string {
  return `/docs/${id === 'intro' ? '' : id + '/'}`;
}

function label(entry: DocEntry): string {
  return entry.data.sidebar_label ?? entry.data.title;
}

/** Docs grouped for the sidebar: top-level pages, then Examples. */
export async function getSidebar(): Promise<SidebarGroup[]> {
  const docs = await getDocs();

  const topLevel = docs.filter((d) => !d.id.includes('/'));
  const examples = docs.filter((d) => d.id.startsWith('examples/'));

  const groups: SidebarGroup[] = [];

  if (topLevel.length) {
    groups.push({
      label: null,
      items: topLevel.map((d) => ({ label: label(d), href: href(d.id) })),
    });
  }

  if (examples.length) {
    groups.push({
      label: 'Examples',
      items: examples.map((d) => ({ label: label(d), href: href(d.id) })),
    });
  }

  return groups;
}
