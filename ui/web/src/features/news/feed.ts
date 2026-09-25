import type {NewsItem, NewsList} from '@/api/schemas/news';
import {
  formatEtTime,
  isIsoDate,
  isWeekend,
  previousTradingDate,
} from '@/lib/time';

/** The feed's filters. They live in the URL: `/news?date=&ticker=&q=&dups=1`. */
export interface FeedFilters {
  /** Trading date, `YYYY-MM-DD`. */
  date: string;
  ticker?: string;
  q?: string;
  /** Show duplicates (hidden by default, like the PDF). */
  dups: boolean;
}

const TICKER = /^[A-Z][A-Z0-9.-]{0,9}$/;
/** The longest text search the URL keeps. */
export const MAX_QUERY_LENGTH = 200;

/** An upper-case ticker, or undefined when `value` can't be one. */
export function normalizeTicker(value: string): string | undefined {
  const ticker = value.trim().toUpperCase();
  return TICKER.test(ticker) ? ticker : undefined;
}

/**
 * Reads the filters from the URL. Anything missing or invalid falls back to
 * its default (today's date, no ticker, no search, duplicates hidden), so a
 * hand-edited or old link never breaks the page.
 */
export function parseFeedFilters(
  params: URLSearchParams,
  today: string,
): FeedFilters {
  const date = params.get('date');
  const q = params.get('q')?.trim().slice(0, MAX_QUERY_LENGTH) ?? '';
  return {
    date: date !== null && isIsoDate(date) ? date : today,
    ticker: normalizeTicker(params.get('ticker') ?? ''),
    q: q === '' ? undefined : q,
    dups: params.get('dups') === '1',
  };
}

/** The URL query for `filters`; defaults (no ticker, no search) left out. */
export function feedSearch(filters: FeedFilters): string {
  const params = new URLSearchParams({date: filters.date});
  if (filters.ticker !== undefined) {
    params.set('ticker', filters.ticker);
  }
  if (filters.q !== undefined) {
    params.set('q', filters.q);
  }
  if (filters.dups) {
    params.set('dups', '1');
  }
  return `?${params.toString()}`;
}

/** Newest first; the backend sorts too, this keeps the UI right regardless. */
export function newestFirst(items: readonly NewsItem[]): NewsItem[] {
  return [...items].sort(
    (a, b) =>
      Date.parse(b.publishedAt) - Date.parse(a.publishedAt) || b.id - a.id,
  );
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? '' : 's'}`;
}

/**
 * The summary line of a finished run, for example
 * `91 items · 9 duplicates hidden · updated 05:30 ET`.
 */
export function feedSummary(list: NewsList, filters: FeedFilters): string {
  const parts: string[] = [];
  const filtered = filters.ticker !== undefined || filters.q !== undefined;
  parts.push(plural(list.count, filtered ? 'matching item' : 'item'));
  if (list.run !== null && !filtered) {
    const state = filters.dups ? 'shown' : 'hidden';
    parts.push(`${plural(list.run.dups, 'duplicate')} ${state}`);
  }
  const finishedAt = list.run?.finishedAt;
  if (finishedAt !== null && finishedAt !== undefined) {
    parts.push(`updated ${formatEtTime(finishedAt)} ET`);
  }
  return parts.join(' · ');
}

/**
 * Where "No feed for <date>" links to: the trading date before `date`, or,
 * for a date after today, the latest trading date up to today.
 */
export function feedFallbackDate(date: string, today: string): string {
  if (date > today) {
    return isWeekend(today) ? previousTradingDate(today) : today;
  }
  return previousTradingDate(date);
}
