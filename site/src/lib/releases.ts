/**
 * Build-time fetching + filtering of Databricks release-note RSS feeds down to
 * the Lakebase product category.
 *
 * The feeds carry ~1,000 entries each across every Databricks product; each
 * <item> is tagged with one or more <category> elements. We keep only the items
 * tagged `Lakebase`, so the Releases page shows Lakebase-specific changes only.
 *
 * This runs at `astro build` (Node), not in the browser — the feeds send no
 * CORS headers, so a client-side fetch would be blocked. Fetching here also
 * means the heavy parse/filter happens once per deploy, not once per visitor.
 */

export type Cloud = 'aws' | 'azure';

export interface ReleaseItem {
  title: string;
  link: string;
  /** ISO date string (sortable); empty if the feed omitted a pubDate. */
  isoDate: string;
  /** Human label, e.g. "August 5, 2026". */
  dateLabel: string;
  /** Grouping key, e.g. "August 2026". */
  monthLabel: string;
  /** Sanitized description HTML with relative links resolved to absolute. */
  descriptionHtml: string;
  /** Categories other than the "Product"/"Lakebase" filter tags. */
  tags: string[];
  /** Release maturity parsed from the title/description, if any. */
  releaseType: 'GA' | 'Public Preview' | 'Beta' | null;
}

interface FeedConfig {
  url: string;
  /** Origin used to resolve relative links inside descriptions. */
  base: string;
  label: string;
}

export const FEEDS: Record<Cloud, FeedConfig> = {
  aws: {
    url: 'https://docs.databricks.com/aws/en/feed.xml',
    base: 'https://docs.databricks.com',
    label: 'AWS',
  },
  azure: {
    url: 'https://learn.microsoft.com/azure/databricks/feed.xml',
    base: 'https://learn.microsoft.com',
    label: 'Azure',
  },
};

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

function decodeEntities(input: string): string {
  return input
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#0?39;/g, "'")
    .replace(/&apos;/g, "'");
}

function firstMatch(block: string, tag: string): string {
  // Handles both `<tag><![CDATA[...]]></tag>` and `<tag>...</tag>`.
  const cdata = new RegExp(`<${tag}><!\\[CDATA\\[([\\s\\S]*?)\\]\\]></${tag}>`).exec(block);
  if (cdata) return cdata[1].trim();
  const plain = new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`).exec(block);
  return plain ? decodeEntities(plain[1].trim()) : '';
}

function detectReleaseType(text: string): ReleaseItem['releaseType'] {
  if (/\bpublic preview\b/i.test(text)) return 'Public Preview';
  if (/\bbeta\b/i.test(text)) return 'Beta';
  if (/general availability|\bgenerally available\b|\(GA\)/i.test(text)) return 'GA';
  return null;
}

/**
 * Rewrite root-relative doc links (`href="/aws/en/..."`) to absolute URLs and
 * force them to open in a new tab. The feed descriptions are authored by
 * Databricks docs, so the markup is trusted, but we still strip anything other
 * than the paragraph/link/code tags they use.
 */
function normalizeDescription(html: string, base: string): string {
  return html
    .replace(/\shref="\/(?!\/)/g, ` target="_blank" rel="noopener noreferrer" href="${base}/`)
    .trim();
}

function parseFeed(xml: string, cfg: FeedConfig): ReleaseItem[] {
  const items: ReleaseItem[] = [];
  const itemBlocks = xml.match(/<item>[\s\S]*?<\/item>/g) ?? [];

  for (const block of itemBlocks) {
    const categories = [...block.matchAll(/<category>([\s\S]*?)<\/category>/g)].map((m) =>
      decodeEntities(m[1].trim()),
    );
    if (!categories.includes('Lakebase')) continue;

    const title = firstMatch(block, 'title');
    const link = firstMatch(block, 'link');
    const rawDate = firstMatch(block, 'pubDate');
    const rawDesc = firstMatch(block, 'description');

    const date = rawDate ? new Date(rawDate) : null;
    const valid = date && !Number.isNaN(date.getTime());
    const dateLabel = valid
      ? `${MONTHS[date.getUTCMonth()]} ${date.getUTCDate()}, ${date.getUTCFullYear()}`
      : '';
    const monthLabel = valid ? `${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}` : 'Undated';

    items.push({
      title,
      link,
      isoDate: valid ? date.toISOString() : '',
      dateLabel,
      monthLabel,
      descriptionHtml: normalizeDescription(rawDesc, cfg.base),
      tags: categories.filter((c) => c !== 'Product' && c !== 'Lakebase'),
      releaseType: detectReleaseType(`${title} ${rawDesc}`),
    });
  }

  // Newest first; undated entries sink to the bottom.
  items.sort((a, b) => (b.isoDate || '').localeCompare(a.isoDate || ''));
  return items;
}

async function fetchFeed(cloud: Cloud): Promise<ReleaseItem[]> {
  const cfg = FEEDS[cloud];
  try {
    const res = await fetch(cfg.url, { headers: { 'user-agent': 'lakebase-cookbook' } });
    if (!res.ok) {
      console.warn(`[releases] ${cfg.label} feed responded ${res.status}; skipping.`);
      return [];
    }
    return parseFeed(await res.text(), cfg);
  } catch (err) {
    // Never fail the build over an unreachable feed — render an empty panel.
    console.warn(`[releases] Could not fetch ${cfg.label} feed:`, (err as Error).message);
    return [];
  }
}

export interface MonthGroup {
  month: string;
  items: ReleaseItem[];
}

/** Group a cloud's items into month buckets, preserving newest-first order. */
export function groupByMonth(items: ReleaseItem[]): MonthGroup[] {
  const groups: MonthGroup[] = [];
  for (const item of items) {
    const last = groups[groups.length - 1];
    if (last && last.month === item.monthLabel) last.items.push(item);
    else groups.push({ month: item.monthLabel, items: [item] });
  }
  return groups;
}

export interface LakebaseReleases {
  aws: ReleaseItem[];
  azure: ReleaseItem[];
}

export async function getLakebaseReleases(): Promise<LakebaseReleases> {
  const [aws, azure] = await Promise.all([fetchFeed('aws'), fetchFeed('azure')]);
  return { aws, azure };
}
