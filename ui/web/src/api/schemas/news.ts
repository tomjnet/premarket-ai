import {z} from 'zod';

import {isIsoDate} from '@/lib/time';

/** The backend counts characters (Python `len`), not UTF-16 units. */
export const EXCERPT_MAX_CHARS = 280;

const isoDateSchema = z.string().refine(isIsoDate, 'Expected YYYY-MM-DD');
// UTC with a `Z`, as the contract says (no offsets).
const utcDateTimeSchema = z.iso.datetime();

export const runStatusSchema = z.enum(['RUNNING', 'DONE', 'FAILED']);

/** Wire format of the ingest run of a date. */
export const ingestRunWireSchema = z.object({
  run_id: z.number().int(),
  status: runStatusSchema,
  started_at: utcDateTimeSchema,
  // null while the run is RUNNING (legacy.ingest_run.finished_at).
  finished_at: utcDateTimeSchema.nullable(),
  rows_received: z.number().int().nonnegative(),
  dups: z.number().int().nonnegative(),
});

/** Wire format of one item in `GET /news`. */
export const newsItemWireSchema = z.object({
  id: z.number().int(),
  vendor_item_id: z.string().min(1),
  feed_date: isoDateSchema,
  headline: z.string(),
  excerpt: z
    .string()
    .refine(
      text => [...text].length <= EXCERPT_MAX_CHARS,
      `At most ${EXCERPT_MAX_CHARS} characters`,
    ),
  source_url: z.string(),
  source_domain: z.string(),
  published_at: utcDateTimeSchema,
  tickers: z.array(z.string()),
  synthetic: z.boolean(),
  is_dup: z.boolean(),
  dup_of: z.string().nullable(),
});

/** Wire format of `GET /news/{id}`: the item plus its full body. */
export const newsDetailWireSchema = newsItemWireSchema.extend({
  body: z.string(),
});

/** Wire format of `GET /news`. */
export const newsListWireSchema = z
  .object({
    date: isoDateSchema,
    run: ingestRunWireSchema.nullable(),
    count: z.number().int().nonnegative(),
    items: z.array(newsItemWireSchema),
  })
  .refine(list => list.count === list.items.length, {
    message: 'count must equal the number of items',
    path: ['count'],
  });

export type NewsItemWire = z.infer<typeof newsItemWireSchema>;
export type IngestRunWire = z.infer<typeof ingestRunWireSchema>;

function toNewsItem(wire: NewsItemWire) {
  return {
    id: wire.id,
    vendorItemId: wire.vendor_item_id,
    feedDate: wire.feed_date,
    headline: wire.headline,
    excerpt: wire.excerpt,
    sourceUrl: wire.source_url,
    sourceDomain: wire.source_domain,
    publishedAt: wire.published_at,
    tickers: wire.tickers,
    synthetic: wire.synthetic,
    isDup: wire.is_dup,
    dupOf: wire.dup_of,
  };
}

function toIngestRun(wire: IngestRunWire) {
  return {
    runId: wire.run_id,
    status: wire.status,
    startedAt: wire.started_at,
    finishedAt: wire.finished_at,
    rowsReceived: wire.rows_received,
    dups: wire.dups,
  };
}

/** `GET /news` as the UI uses it. */
export const newsListSchema = newsListWireSchema.transform(wire => ({
  date: wire.date,
  run: wire.run === null ? null : toIngestRun(wire.run),
  count: wire.count,
  items: wire.items.map(toNewsItem),
}));

/** `GET /news/{id}` as the UI uses it. */
export const newsDetailSchema = newsDetailWireSchema.transform(wire => ({
  ...toNewsItem(wire),
  body: wire.body,
}));

export type RunStatus = z.infer<typeof runStatusSchema>;
export type NewsList = z.output<typeof newsListSchema>;
export type NewsItem = NewsList['items'][number];
export type IngestRun = NonNullable<NewsList['run']>;
export type NewsDetail = z.output<typeof newsDetailSchema>;
export type NewsListWire = z.infer<typeof newsListWireSchema>;
export type NewsDetailWire = z.infer<typeof newsDetailWireSchema>;
