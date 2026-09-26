import type {BriefMetaWire, BriefWire} from '@/api/schemas/brief';
import type {NewsDetailWire} from '@/api/schemas/news';

/**
 * The mock's pre-market brief (increment 5), built from a verified day like
 * the backend's briefing agent: VERIFIED items (not waiting for review),
 * highest market impact first, by sector; high-impact UNVERIFIED items under
 * "Unconfirmed – watch"; MISLEADING, FAKE and pending items only counted.
 */

export const BRIEF_MODEL = 'cloud-openai';
export const BRIEF_PROMPT_VERSION = 'brief-v1';
const TOP_MAX = 8;
const WATCH_MAX = 5;
/** Generated briefs get ids by date, far from the started ones (900001+). */
const GENERATED_BRIEF_OFFSET = 500_000;

/** GICS sectors of the mock's companies (the backend reads universe.yaml). */
const SECTORS: Readonly<Record<string, string>> = {
  AAPL: 'Information Technology',
  MSFT: 'Information Technology',
  NVDA: 'Information Technology',
  AVGO: 'Information Technology',
  ORCL: 'Information Technology',
  AMZN: 'Consumer Discretionary',
  TSLA: 'Consumer Discretionary',
  HD: 'Consumer Discretionary',
  GOOGL: 'Communication Services',
  META: 'Communication Services',
  JPM: 'Financials',
  V: 'Financials',
  MA: 'Financials',
  LLY: 'Health Care',
  UNH: 'Health Care',
  JNJ: 'Health Care',
  XOM: 'Energy',
  COST: 'Consumer Staples',
  WMT: 'Consumer Staples',
  PG: 'Consumer Staples',
};

/** The sectors a watchlist can follow. */
export const MOCK_SECTORS: readonly string[] = [
  ...new Set(Object.values(SECTORS)),
].sort();

export const OTHER_SECTOR = 'Other';

function sectorOf(item: NewsDetailWire): string {
  for (const ticker of item.tickers) {
    const sector = SECTORS[ticker];
    if (sector !== undefined) {
      return sector;
    }
  }
  return OTHER_SECTOR;
}

function byImpact(a: NewsDetailWire, b: NewsDetailWire): number {
  return (
    (b.verification?.impact_score ?? 0) - (a.verification?.impact_score ?? 0) ||
    b.published_at.localeCompare(a.published_at) ||
    a.id - b.id
  );
}

/** The generated morning brief's id of a date. */
export function generatedBriefId(date: string): number {
  return GENERATED_BRIEF_OFFSET + (Number(date.replaceAll('-', '')) % 100_000);
}

/** When the generated morning brief of a date was written (07:15 ET). */
export function generatedBriefMeta(date: string): BriefMetaWire {
  return {
    brief_id: generatedBriefId(date),
    feed_date: date,
    edition: 'morning',
    status: 'DONE',
    requested_by: 'cli',
    requested_at: `${date}T11:15:00Z`,
    started_at: `${date}T11:15:01Z`,
    finished_at: `${date}T11:16:10Z`,
    error: null,
  };
}

interface Watchlist {
  tickers: string[];
  sectors: string[];
}

/**
 * The brief of a day's items (as served, reviews applied) for `meta`, with
 * the caller's watchlist items. A refresh marks the items an analyst
 * reviewed as new (they were pending at 07:15).
 */
export function mockBrief(
  items: readonly NewsDetailWire[],
  meta: BriefMetaWire,
  watchlist: Watchlist,
): BriefWire {
  const unique = items.filter(item => item.verdict_source === 'ai');
  const final = unique.filter(item => item.verification?.status === 'DONE');
  const verified = final
    .filter(item => item.verdict === 'VERIFIED')
    .sort(byImpact);
  const watch = final
    .filter(
      item =>
        item.verdict === 'UNVERIFIED' && item.verification?.impact === 'high',
    )
    .sort(byImpact)
    .slice(0, WATCH_MAX);
  const refresh = meta.edition === 'refresh';
  const numbered = [...verified, ...watch].map((item, index) => {
    const filing = item.verification?.evidence.find(
      entry => entry.source === 'filing' && entry.url !== null,
    );
    const verdict: 'VERIFIED' | 'UNVERIFIED' =
      item.verdict === 'VERIFIED' ? 'VERIFIED' : 'UNVERIFIED';
    const section: 'top' | 'sector' | 'watch' =
      index >= verified.length ? 'watch' : index < TOP_MAX ? 'top' : 'sector';
    return {
      n: index + 1,
      news_id: item.id,
      vendor_item_id: item.vendor_item_id,
      headline: item.headline,
      summary: item.summary,
      sentiment: item.sentiment,
      tickers: item.tickers,
      sector: sectorOf(item),
      source_domain: item.source_domain,
      published_at: item.published_at,
      verdict,
      confidence: item.confidence,
      review_status: item.review_status,
      impact: item.verification?.impact ?? null,
      impact_score: item.verification?.impact_score ?? 0,
      filing_url: filing?.url ?? null,
      filing_title: filing?.title ?? null,
      section,
      new:
        refresh &&
        (item.review_status === 'APPROVED' ||
          item.review_status === 'OVERRIDDEN'),
    };
  });
  const sectors: Array<{name: string; items: number[]}> = [];
  for (const item of numbered) {
    if (item.section === 'watch') {
      continue;
    }
    const group = sectors.find(entry => entry.name === item.sector);
    if (group === undefined) {
      sectors.push({name: item.sector, items: [item.n]});
    } else {
      group.items.push(item.n);
    }
  }
  const count = (verdict: string) =>
    final.filter(item => item.verdict === verdict).length;
  const tickers = new Set(watchlist.tickers);
  const followed = new Set(watchlist.sectors);
  const top = numbered.filter(item => item.section === 'top');
  const lead = top
    .slice(0, 2)
    .map(item => `${item.summary ?? item.headline} [${item.n}]`)
    .join(' ');
  const overview =
    verified.length === 0
      ? `No story is verified for ${meta.feed_date} yet.`
      : `${verified.length} stories are verified this morning, the most ` +
        `important first. ${lead}`;
  return {
    ...meta,
    overview,
    overview_source: 'llm',
    citations: top.slice(0, 2).map(item => item.n),
    model: BRIEF_MODEL,
    cloud: true,
    prompt_version: BRIEF_PROMPT_VERSION,
    counts: {
      verified: verified.length,
      unconfirmed: watch.length,
      unverified: count('UNVERIFIED'),
      pending_review: unique.filter(
        item => item.verification?.status === 'PENDING_REVIEW',
      ).length,
      misleading: count('MISLEADING'),
      fake: count('FAKE'),
      failed: unique.filter(item => item.verification?.status === 'FAILED')
        .length,
      new: numbered.filter(item => item.new).length,
    },
    items: numbered,
    top: top.map(item => item.n),
    sectors,
    watch: numbered
      .filter(item => item.section === 'watch')
      .map(item => item.n),
    watchlist: {
      tickers: watchlist.tickers,
      sectors: watchlist.sectors,
      items: numbered
        .filter(
          item =>
            item.tickers.some(ticker => tickers.has(ticker)) ||
            followed.has(item.sector),
        )
        .map(item => item.n),
    },
  };
}
