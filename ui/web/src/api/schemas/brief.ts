import {z} from 'zod';

import {isIsoDate} from '@/lib/time';

import {impactSchema, reviewStatusSchema, sentimentSchema} from './news';

/**
 * The pre-market brief (increment 5): `GET /briefs/today?date=` as
 * server-sent events, `POST /briefs` (ANALYST, ADMIN), and the caller's
 * watchlist (`GET` / `PUT /me/watchlist`).
 */

const isoDateSchema = z.string().refine(isIsoDate, 'Expected YYYY-MM-DD');
const utcDateTimeSchema = z.iso.datetime();

export const briefEditionSchema = z.enum(['morning', 'refresh']);
export const briefStatusSchema = z.enum([
  'QUEUED',
  'RUNNING',
  'DONE',
  'FAILED',
]);
export const briefSectionSchema = z.enum(['top', 'sector', 'watch']);

/** `event: brief` and `POST /briefs`: which brief, and its state. */
export const briefMetaWireSchema = z.object({
  brief_id: z.number().int().positive(),
  feed_date: isoDateSchema,
  edition: briefEditionSchema,
  status: briefStatusSchema,
  requested_by: z.string().nullable(),
  requested_at: utcDateTimeSchema,
  started_at: utcDateTimeSchema.nullable(),
  finished_at: utcDateTimeSchema.nullable(),
  error: z.string().nullable(),
});

/** One numbered item (the overview cites `[n]`). */
export const briefItemWireSchema = z.object({
  n: z.number().int().positive(),
  news_id: z.number().int().positive(),
  vendor_item_id: z.string().min(1),
  headline: z.string(),
  summary: z.string().nullable(),
  sentiment: sentimentSchema.nullable(),
  tickers: z.array(z.string()),
  sector: z.string(),
  source_domain: z.string(),
  published_at: utcDateTimeSchema,
  // Only these two ever go in: MISLEADING and FAKE are counted, never shown.
  verdict: z.enum(['VERIFIED', 'UNVERIFIED']),
  confidence: z.number().min(0).max(1).nullable(),
  review_status: reviewStatusSchema.nullable(),
  impact: impactSchema.nullable(),
  impact_score: z.number(),
  filing_url: z.string().nullable(),
  filing_title: z.string().nullable(),
  section: briefSectionSchema,
  new: z.boolean(),
});

const briefCountsWireSchema = z.object({
  verified: z.number().int().nonnegative(),
  unconfirmed: z.number().int().nonnegative(),
  unverified: z.number().int().nonnegative(),
  pending_review: z.number().int().nonnegative(),
  misleading: z.number().int().nonnegative(),
  fake: z.number().int().nonnegative(),
  failed: z.number().int().nonnegative(),
  new: z.number().int().nonnegative(),
});

/** `event: done`: the whole brief, with the caller's watchlist items. */
export const briefWireSchema = briefMetaWireSchema.extend({
  overview: z.string(),
  overview_source: z.enum(['llm', 'fallback']).nullable(),
  citations: z.array(z.number().int().positive()),
  model: z.string().nullable(),
  cloud: z.boolean(),
  prompt_version: z.string().nullable(),
  counts: briefCountsWireSchema,
  items: z.array(briefItemWireSchema),
  top: z.array(z.number().int().positive()),
  sectors: z.array(
    z.object({name: z.string(), items: z.array(z.number().int().positive())}),
  ),
  watch: z.array(z.number().int().positive()),
  watchlist: z.object({
    tickers: z.array(z.string()),
    sectors: z.array(z.string()),
    items: z.array(z.number().int().positive()),
  }),
});

/** `event: status`: what the brief writer is doing. */
export const briefStatusEventWireSchema = z.object({detail: z.string()});

/**
 * `event: sections`: the items are chosen (the overview comes next). Only
 * the counts are used; the whole brief comes with `done`.
 */
export const briefSectionsWireSchema = z.object({
  counts: z.object({
    verified: z.number().int().nonnegative(),
    unconfirmed: z.number().int().nonnegative(),
    pending_review: z.number().int().nonnegative(),
  }),
});

/** `event: error`. */
export const briefErrorWireSchema = z.object({detail: z.string()});

function metaFromWire(wire: z.infer<typeof briefMetaWireSchema>) {
  return {
    briefId: wire.brief_id,
    feedDate: wire.feed_date,
    edition: wire.edition,
    status: wire.status,
    requestedBy: wire.requested_by,
    requestedAt: wire.requested_at,
    startedAt: wire.started_at,
    finishedAt: wire.finished_at,
    error: wire.error,
  };
}

export const briefMetaSchema = briefMetaWireSchema.transform(metaFromWire);

export const briefSchema = briefWireSchema.transform(wire => ({
  ...metaFromWire(wire),
  overview: wire.overview,
  overviewSource: wire.overview_source,
  citations: wire.citations,
  model: wire.model,
  cloud: wire.cloud,
  promptVersion: wire.prompt_version,
  counts: {
    verified: wire.counts.verified,
    unconfirmed: wire.counts.unconfirmed,
    unverified: wire.counts.unverified,
    pendingReview: wire.counts.pending_review,
    misleading: wire.counts.misleading,
    fake: wire.counts.fake,
    failed: wire.counts.failed,
    new: wire.counts.new,
  },
  items: wire.items.map(item => ({
    n: item.n,
    newsId: item.news_id,
    vendorItemId: item.vendor_item_id,
    headline: item.headline,
    summary: item.summary,
    sentiment: item.sentiment,
    tickers: item.tickers,
    sector: item.sector,
    sourceDomain: item.source_domain,
    publishedAt: item.published_at,
    verdict: item.verdict,
    confidence: item.confidence,
    reviewStatus: item.review_status,
    impact: item.impact,
    impactScore: item.impact_score,
    filingUrl: item.filing_url,
    filingTitle: item.filing_title,
    section: item.section,
    isNew: item.new,
  })),
  top: wire.top,
  sectors: wire.sectors,
  watch: wire.watch,
  watchlist: wire.watchlist,
}));

/** `GET /me/watchlist` and the `PUT` answer. */
export const watchlistWireSchema = z.object({
  tickers: z.array(z.string()),
  sectors: z.array(z.string()),
  available_sectors: z.array(z.string()),
});

export const watchlistSchema = watchlistWireSchema.transform(wire => ({
  tickers: wire.tickers,
  sectors: wire.sectors,
  availableSectors: wire.available_sectors,
}));

export const WATCHLIST_MAX_TICKERS = 25;

export type BriefMeta = z.output<typeof briefMetaSchema>;
export type Brief = z.output<typeof briefSchema>;
export type BriefItem = Brief['items'][number];
export type BriefEdition = z.infer<typeof briefEditionSchema>;
export type BriefWire = z.input<typeof briefWireSchema>;
export type BriefMetaWire = z.input<typeof briefMetaWireSchema>;
export type Watchlist = z.output<typeof watchlistSchema>;
export type WatchlistWire = z.input<typeof watchlistWireSchema>;

/** One event of the brief stream, as the UI uses it. */
export type BriefEvent =
  | {type: 'brief'; data: BriefMeta}
  | {type: 'status'; detail: string}
  | {
      type: 'sections';
      verified: number;
      unconfirmed: number;
      pendingReview: number;
    }
  | {type: 'done'; data: Brief}
  | {type: 'error'; detail: string};
