import {z} from 'zod';

import {isIsoDate} from '@/lib/time';

/** The backend counts characters (Python `len`), not UTF-16 units. */
export const EXCERPT_MAX_CHARS = 280;

const isoDateSchema = z.string().refine(isIsoDate, 'Expected YYYY-MM-DD');
// UTC with a `Z`, as the contract says (no offsets).
const utcDateTimeSchema = z.iso.datetime();

export const runStatusSchema = z.enum(['RUNNING', 'DONE', 'FAILED']);

/**
 * A rule engine reason code. Later increments add codes, so any code of this
 * shape is accepted; the UI shows an unknown one as a neutral badge.
 */
export const REASON_CODE_PATTERN = /^[A-Z][A-Z_]{1,40}$/;
export const reasonCodeSchema = z.string().regex(REASON_CODE_PATTERN);

/** How the rules matched a duplicate to the story it copies. */
export const dupTypeSchema = z.enum(['url', 'exact', 'near', 'paraphrase']);

/** Which rule check wrote a piece of evidence. */
export const ruleCheckSchema = z.enum(['entity', 'source', 'dedup', 'stale']);

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
  // From the rule engine when `rules_checked`, else the legacy exact hash.
  is_dup: z.boolean(),
  dup_of: z.string().nullable(),
  // Sorted by the backend; the UI orders the badges itself.
  reason_codes: z.array(reasonCodeSchema),
  dup_type: dupTypeSchema.nullable(),
  copies: z.number().int().nonnegative(),
  rules_checked: z.boolean(),
});

/** Wire format of one rule check's explanation (plain text). */
export const ruleEvidenceWireSchema = z.object({
  check: ruleCheckSchema,
  code: reasonCodeSchema.nullable(),
  message: z.string(),
});

/** Wire format of `GET /news/{id}`: the item plus its full body. */
export const newsDetailWireSchema = newsItemWireSchema.extend({
  body: z.string(),
  rule_evidence: z.array(ruleEvidenceWireSchema),
});

/** Wire format of the latest rule-check run of a date. */
export const ruleRunWireSchema = z.object({
  status: runStatusSchema,
  finished_at: utcDateTimeSchema.nullable(),
  items: z.number().int().nonnegative(),
  duplicates: z.number().int().nonnegative(),
  flagged: z.number().int().nonnegative(),
});

/** Wire format of `GET /news`. */
export const newsListWireSchema = z
  .object({
    date: isoDateSchema,
    run: ingestRunWireSchema.nullable(),
    rule_run: ruleRunWireSchema.nullable(),
    count: z.number().int().nonnegative(),
    items: z.array(newsItemWireSchema),
  })
  .refine(list => list.count === list.items.length, {
    message: 'count must equal the number of items',
    path: ['count'],
  });

export type NewsItemWire = z.infer<typeof newsItemWireSchema>;
export type IngestRunWire = z.infer<typeof ingestRunWireSchema>;
export type RuleRunWire = z.infer<typeof ruleRunWireSchema>;
export type RuleEvidenceWire = z.infer<typeof ruleEvidenceWireSchema>;

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
    reasonCodes: wire.reason_codes,
    dupType: wire.dup_type,
    copies: wire.copies,
    rulesChecked: wire.rules_checked,
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

function toRuleRun(wire: RuleRunWire) {
  return {
    status: wire.status,
    finishedAt: wire.finished_at,
    items: wire.items,
    duplicates: wire.duplicates,
    flagged: wire.flagged,
  };
}

/** `GET /news` as the UI uses it. */
export const newsListSchema = newsListWireSchema.transform(wire => ({
  date: wire.date,
  run: wire.run === null ? null : toIngestRun(wire.run),
  ruleRun: wire.rule_run === null ? null : toRuleRun(wire.rule_run),
  count: wire.count,
  items: wire.items.map(toNewsItem),
}));

/** `GET /news/{id}` as the UI uses it. */
export const newsDetailSchema = newsDetailWireSchema.transform(wire => ({
  ...toNewsItem(wire),
  body: wire.body,
  // Same shape and names in the UI model.
  ruleEvidence: wire.rule_evidence,
}));

export type RunStatus = z.infer<typeof runStatusSchema>;
export type NewsList = z.output<typeof newsListSchema>;
export type NewsItem = NewsList['items'][number];
export type IngestRun = NonNullable<NewsList['run']>;
export type RuleRun = NonNullable<NewsList['ruleRun']>;
export type DupType = z.infer<typeof dupTypeSchema>;
export type RuleEvidence = z.infer<typeof ruleEvidenceWireSchema>;
export type NewsDetail = z.output<typeof newsDetailSchema>;
export type NewsListWire = z.infer<typeof newsListWireSchema>;
export type NewsDetailWire = z.infer<typeof newsDetailWireSchema>;
