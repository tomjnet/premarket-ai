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

/** The AI summary's tone about the story (not advice about the security). */
export const sentimentSchema = z.enum(['bullish', 'neutral', 'bearish']);

/** Which AI-run step wrote a piece of evidence. */
export const aiCheckSchema = z.enum(['guard', 'language', 'dedup']);

/** What the AI run did with an item. */
export const aiStatusSchema = z.enum([
  'DONE',
  'SKIPPED',
  'DUPLICATE',
  'FAILED',
]);

/** The four verdicts of the AI verification (increment 4). */
export const verdictSchema = z.enum([
  'VERIFIED',
  'UNVERIFIED',
  'MISLEADING',
  'FAKE',
]);

/** Where an analyst's review of a verdict stands. */
export const reviewStatusSchema = z.enum([
  'PENDING',
  'APPROVED',
  'OVERRIDDEN',
  'EXPIRED',
]);

/** A verify run's state; `QUEUED` until a worker starts it. */
export const verifyRunStatusSchema = z.enum([
  'QUEUED',
  'RUNNING',
  'DONE',
  'FAILED',
]);

/** Market impact of an item: relevance of the news kind x company size. */
export const impactSchema = z.enum(['low', 'medium', 'high']);

/** A probability-like score from 0 to 1. */
const scoreSchema = z.number().min(0).max(1);

/** One line of at most 280 characters (the backend counts code points). */
const oneLineSummarySchema = z
  .string()
  .refine(
    text => [...text].length <= EXCERPT_MAX_CHARS,
    `At most ${EXCERPT_MAX_CHARS} characters`,
  )
  .refine(text => !/[\r\n]/.test(text), 'One line only');

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
  // Null until the AI run summarized the item (increment 3).
  summary: oneLineSummarySchema.nullable(),
  sentiment: sentimentSchema.nullable(),
  // Null until verified (increment 4); a duplicate shows its original's
  // verdict (`inherited`), a stale copy MISLEADING.
  verdict: verdictSchema.nullable(),
  confidence: scoreSchema.nullable(),
  review_status: reviewStatusSchema.nullable(),
  verdict_source: z.enum(['ai', 'inherited']).nullable(),
});

/** Wire format of one rule check's explanation (plain text). */
export const ruleEvidenceWireSchema = z.object({
  check: ruleCheckSchema,
  code: reasonCodeSchema.nullable(),
  message: z.string(),
});

/** Wire format of one AI-run finding (plain text). */
export const aiEvidenceWireSchema = z.object({
  check: aiCheckSchema,
  code: reasonCodeSchema.nullable(),
  message: z.string(),
});

/** A company the model found in the item. */
export const aiCompanyWireSchema = z.object({
  name: z.string(),
  ticker: z.string().nullable(),
});

/** Wire format of what the AI run did with one item. */
export const aiDetailWireSchema = z.object({
  status: aiStatusSchema,
  model: z.string(),
  prompt_version: z.string(),
  enriched_at: utcDateTimeSchema,
  // `fallback`: the model couldn't summarize; the lead sentence is shown.
  summary_source: z.enum(['llm', 'fallback']).nullable(),
  companies: z.array(aiCompanyWireSchema),
  claims: z.array(z.string()),
  evidence: z.array(aiEvidenceWireSchema),
});

/**
 * Wire format of one finding of the verification, numbered like the LLM
 * judge saw it (E1, E2...). `check` is open (the verify graph adds checks);
 * `url`/`title` link a filing or a web result. Plain text only.
 */
export const verifyEvidenceWireSchema = z.object({
  seq: z.number().int().positive(),
  check: z.string().regex(/^[a-z][a-z_]{1,30}$/),
  code: reasonCodeSchema.nullable(),
  message: z.string(),
  source: z.string(),
  url: z.string().nullable(),
  title: z.string().nullable(),
});

/** Wire format of an item's latest review task. */
export const reviewWireSchema = z.object({
  id: z.number().int(),
  status: reviewStatusSchema,
  reasons: z.array(z.string()),
  ai_verdict: verdictSchema,
  final_verdict: verdictSchema.nullable(),
  reviewer: z.string().nullable(),
  comment: z.string().nullable(),
  created_at: utcDateTimeSchema,
  decided_at: utcDateTimeSchema.nullable(),
});

/** Wire format of how the AI reached an item's verdict. */
export const verificationWireSchema = z.object({
  status: z.enum(['PENDING_REVIEW', 'DONE', 'FAILED']),
  verdict: verdictSchema.nullable(),
  confidence: scoreSchema.nullable(),
  reason_codes: z.array(reasonCodeSchema),
  rationale: z.string(),
  // The deterministic checks' verdict, then the LLM judge's (null when a
  // hard rule decided or the judge wasn't asked).
  rule_verdict: verdictSchema.nullable(),
  rule_confidence: scoreSchema.nullable(),
  judge_verdict: verdictSchema.nullable(),
  judge_confidence: scoreSchema.nullable(),
  judge_model: z.string().nullable(),
  // The cloud model judged (an uncertain item).
  escalated: z.boolean(),
  review_status: reviewStatusSchema.nullable(),
  review_reasons: z.array(z.string()),
  impact: impactSchema.nullable(),
  impact_score: scoreSchema.nullable(),
  prompt_version: z.string(),
  verified_at: utcDateTimeSchema,
  evidence: z.array(verifyEvidenceWireSchema),
  review: reviewWireSchema.nullable(),
});

/** Wire format of `GET /news/{id}`: the item plus its full body. */
export const newsDetailWireSchema = newsItemWireSchema.extend({
  body: z.string(),
  rule_evidence: z.array(ruleEvidenceWireSchema),
  ai: aiDetailWireSchema.nullable(),
  verification: verificationWireSchema.nullable(),
});

/** Wire format of the latest rule-check run of a date. */
export const ruleRunWireSchema = z.object({
  status: runStatusSchema,
  finished_at: utcDateTimeSchema.nullable(),
  items: z.number().int().nonnegative(),
  duplicates: z.number().int().nonnegative(),
  flagged: z.number().int().nonnegative(),
});

/** Wire format of the latest AI run (summaries, paraphrases) of a date. */
export const aiRunWireSchema = z.object({
  status: runStatusSchema,
  finished_at: utcDateTimeSchema.nullable(),
  items: z.number().int().nonnegative(),
  paraphrases: z.number().int().nonnegative(),
  conflicts: z.number().int().nonnegative(),
  summarized: z.number().int().nonnegative(),
  fallbacks: z.number().int().nonnegative(),
  failed: z.number().int().nonnegative(),
  model: z.string(),
});

/** Wire format of a verification run (`POST /runs`, `GET /news`). */
export const verifyRunWireSchema = z.object({
  run_id: z.number().int(),
  feed_date: isoDateSchema,
  status: verifyRunStatusSchema,
  requested_by: z.string().nullable(),
  requested_at: utcDateTimeSchema,
  started_at: utcDateTimeSchema.nullable(),
  finished_at: utcDateTimeSchema.nullable(),
  total: z.number().int().nonnegative(),
  done: z.number().int().nonnegative(),
  failed: z.number().int().nonnegative(),
  verified: z.number().int().nonnegative(),
  unverified: z.number().int().nonnegative(),
  misleading: z.number().int().nonnegative(),
  fake: z.number().int().nonnegative(),
  pending_review: z.number().int().nonnegative(),
  escalated: z.number().int().nonnegative(),
  model: z.string().nullable(),
  error: z.string().nullable(),
});

/** Wire format of `GET /news`. */
export const newsListWireSchema = z
  .object({
    date: isoDateSchema,
    run: ingestRunWireSchema.nullable(),
    rule_run: ruleRunWireSchema.nullable(),
    ai_run: aiRunWireSchema.nullable(),
    verify_run: verifyRunWireSchema.nullable(),
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
export type AiRunWire = z.infer<typeof aiRunWireSchema>;
export type AiDetailWire = z.infer<typeof aiDetailWireSchema>;
export type AiEvidenceWire = z.infer<typeof aiEvidenceWireSchema>;
export type VerifyRunWire = z.infer<typeof verifyRunWireSchema>;
export type VerificationWire = z.infer<typeof verificationWireSchema>;
export type VerifyEvidenceWire = z.infer<typeof verifyEvidenceWireSchema>;
export type ReviewWire = z.infer<typeof reviewWireSchema>;

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
    summary: wire.summary,
    sentiment: wire.sentiment,
    verdict: wire.verdict,
    confidence: wire.confidence,
    reviewStatus: wire.review_status,
    verdictSource: wire.verdict_source,
  };
}

/** A verify run as the UI uses it (also `POST /runs` and `GET /runs`). */
export function toVerifyRun(wire: VerifyRunWire) {
  return {
    runId: wire.run_id,
    feedDate: wire.feed_date,
    status: wire.status,
    requestedBy: wire.requested_by,
    requestedAt: wire.requested_at,
    startedAt: wire.started_at,
    finishedAt: wire.finished_at,
    total: wire.total,
    done: wire.done,
    failed: wire.failed,
    verified: wire.verified,
    unverified: wire.unverified,
    misleading: wire.misleading,
    fake: wire.fake,
    pendingReview: wire.pending_review,
    escalated: wire.escalated,
    model: wire.model,
    error: wire.error,
  };
}

function toReview(wire: ReviewWire) {
  return {
    id: wire.id,
    status: wire.status,
    reasons: wire.reasons,
    aiVerdict: wire.ai_verdict,
    finalVerdict: wire.final_verdict,
    reviewer: wire.reviewer,
    comment: wire.comment,
    createdAt: wire.created_at,
    decidedAt: wire.decided_at,
  };
}

function toVerification(wire: VerificationWire) {
  return {
    status: wire.status,
    verdict: wire.verdict,
    confidence: wire.confidence,
    reasonCodes: wire.reason_codes,
    rationale: wire.rationale,
    ruleVerdict: wire.rule_verdict,
    ruleConfidence: wire.rule_confidence,
    judgeVerdict: wire.judge_verdict,
    judgeConfidence: wire.judge_confidence,
    judgeModel: wire.judge_model,
    escalated: wire.escalated,
    reviewStatus: wire.review_status,
    reviewReasons: wire.review_reasons,
    impact: wire.impact,
    impactScore: wire.impact_score,
    promptVersion: wire.prompt_version,
    verifiedAt: wire.verified_at,
    // Same shape and names in the UI model.
    evidence: wire.evidence,
    review: wire.review === null ? null : toReview(wire.review),
  };
}

function toAiRun(wire: AiRunWire) {
  return {
    status: wire.status,
    finishedAt: wire.finished_at,
    items: wire.items,
    paraphrases: wire.paraphrases,
    conflicts: wire.conflicts,
    summarized: wire.summarized,
    fallbacks: wire.fallbacks,
    failed: wire.failed,
    model: wire.model,
  };
}

function toAiDetail(wire: AiDetailWire) {
  return {
    status: wire.status,
    model: wire.model,
    promptVersion: wire.prompt_version,
    enrichedAt: wire.enriched_at,
    summarySource: wire.summary_source,
    // Same shapes and names in the UI model.
    companies: wire.companies,
    claims: wire.claims,
    evidence: wire.evidence,
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
  aiRun: wire.ai_run === null ? null : toAiRun(wire.ai_run),
  verifyRun: wire.verify_run === null ? null : toVerifyRun(wire.verify_run),
  count: wire.count,
  items: wire.items.map(toNewsItem),
}));

/** `GET /news/{id}` as the UI uses it. */
export const newsDetailSchema = newsDetailWireSchema.transform(wire => ({
  ...toNewsItem(wire),
  body: wire.body,
  // Same shape and names in the UI model.
  ruleEvidence: wire.rule_evidence,
  ai: wire.ai === null ? null : toAiDetail(wire.ai),
  verification:
    wire.verification === null ? null : toVerification(wire.verification),
}));

export type RunStatus = z.infer<typeof runStatusSchema>;
export type NewsList = z.output<typeof newsListSchema>;
export type NewsItem = NewsList['items'][number];
export type IngestRun = NonNullable<NewsList['run']>;
export type RuleRun = NonNullable<NewsList['ruleRun']>;
export type AiRun = NonNullable<NewsList['aiRun']>;
export type Sentiment = z.infer<typeof sentimentSchema>;
export type AiDetail = NonNullable<NewsDetail['ai']>;
export type AiEvidence = z.infer<typeof aiEvidenceWireSchema>;
export type DupType = z.infer<typeof dupTypeSchema>;
export type RuleEvidence = z.infer<typeof ruleEvidenceWireSchema>;
export type NewsDetail = z.output<typeof newsDetailSchema>;
export type NewsListWire = z.infer<typeof newsListWireSchema>;
export type Verdict = z.infer<typeof verdictSchema>;
export type ReviewStatus = z.infer<typeof reviewStatusSchema>;
export type VerifyRunStatus = z.infer<typeof verifyRunStatusSchema>;
export type Impact = z.infer<typeof impactSchema>;
export type VerifyRun = ReturnType<typeof toVerifyRun>;
export type Verification = NonNullable<NewsDetail['verification']>;
export type VerifyEvidence = VerifyEvidenceWire;
export type Review = NonNullable<Verification['review']>;
export type NewsDetailWire = z.infer<typeof newsDetailWireSchema>;
