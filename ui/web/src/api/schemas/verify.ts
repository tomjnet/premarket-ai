import {z} from 'zod';

import {isIsoDate} from '@/lib/time';

import {
  impactSchema,
  reasonCodeSchema,
  reviewStatusSchema,
  toVerifyRun,
  verdictSchema,
  verifyRunWireSchema,
} from './news';

/**
 * The AI verification (increment 4): verify runs (`POST /runs`, `GET
 * /runs`), their progress as server-sent events (`GET /runs/{id}/events`)
 * and the human review queue (`GET /review`, `POST /review/{id}`). Only
 * ANALYST and ADMIN may call them.
 */

const isoDateSchema = z.string().refine(isIsoDate, 'Expected YYYY-MM-DD');
const utcDateTimeSchema = z.iso.datetime();

/** A review comment: required (3+ characters) for an override. */
export const COMMENT_MIN_CHARS = 3;
export const COMMENT_MAX_CHARS = 1000;

/** `POST /runs` and `GET /runs/{id}`. */
export const verifyRunSchema = verifyRunWireSchema.transform(toVerifyRun);

/** `GET /runs`. */
export const verifyRunListWireSchema = z
  .object({
    count: z.number().int().nonnegative(),
    items: z.array(verifyRunWireSchema),
  })
  .refine(list => list.count === list.items.length, {
    message: 'count must equal the number of items',
    path: ['count'],
  });

export const verifyRunListSchema = verifyRunListWireSchema.transform(wire =>
  wire.items.map(toVerifyRun),
);

/** Wire format of one task of the review queue. */
export const reviewTaskWireSchema = z.object({
  id: z.number().int(),
  // The news item's id (`GET /news/{id}`).
  item_id: z.number().int(),
  vendor_item_id: z.string().min(1),
  feed_date: isoDateSchema,
  headline: z.string(),
  source_domain: z.string(),
  tickers: z.array(z.string()),
  status: reviewStatusSchema,
  // low_confidence, judge_disagrees, guard_unsafe, unsupported_language;
  // later ones are shown as their text.
  reasons: z.array(z.string()),
  ai_verdict: verdictSchema,
  ai_confidence: z.number().min(0).max(1),
  final_verdict: verdictSchema.nullable(),
  rule_verdict: verdictSchema.nullable(),
  judge_verdict: verdictSchema.nullable(),
  reason_codes: z.array(reasonCodeSchema),
  rationale: z.string(),
  impact: impactSchema.nullable(),
  impact_score: z.number().min(0).max(1),
  reviewer: z.string().nullable(),
  comment: z.string().nullable(),
  created_at: utcDateTimeSchema,
  decided_at: utcDateTimeSchema.nullable(),
});

export type ReviewTaskWire = z.infer<typeof reviewTaskWireSchema>;

function toReviewTask(wire: ReviewTaskWire) {
  return {
    id: wire.id,
    itemId: wire.item_id,
    vendorItemId: wire.vendor_item_id,
    feedDate: wire.feed_date,
    headline: wire.headline,
    sourceDomain: wire.source_domain,
    tickers: wire.tickers,
    status: wire.status,
    reasons: wire.reasons,
    aiVerdict: wire.ai_verdict,
    aiConfidence: wire.ai_confidence,
    finalVerdict: wire.final_verdict,
    ruleVerdict: wire.rule_verdict,
    judgeVerdict: wire.judge_verdict,
    reasonCodes: wire.reason_codes,
    rationale: wire.rationale,
    impact: wire.impact,
    impactScore: wire.impact_score,
    reviewer: wire.reviewer,
    comment: wire.comment,
    createdAt: wire.created_at,
    decidedAt: wire.decided_at,
  };
}

/** `POST /review/{id}`: the decided task. */
export const reviewTaskSchema = reviewTaskWireSchema.transform(toReviewTask);

/** `GET /review`. */
export const reviewListWireSchema = z
  .object({
    count: z.number().int().nonnegative(),
    items: z.array(reviewTaskWireSchema),
  })
  .refine(list => list.count === list.items.length, {
    message: 'count must equal the number of items',
    path: ['count'],
  });

export const reviewListSchema = reviewListWireSchema.transform(wire =>
  wire.items.map(toReviewTask),
);

/** `POST /review/{id}`'s body (the backend checks the same rules). */
export const reviewDecisionSchema = z.discriminatedUnion('action', [
  z.object({action: z.literal('approve')}),
  z.object({
    action: z.literal('override'),
    verdict: verdictSchema,
    comment: z.string().trim().min(COMMENT_MIN_CHARS).max(COMMENT_MAX_CHARS),
  }),
]);

// --- run events (server-sent events of `GET /runs/{id}/events`) -----------

/** `run.started`: the unique items queued. */
export const runStartedWireSchema = z.object({
  total: z.number().int().nonnegative(),
  feed_date: isoDateSchema,
});

/** `item`: one item has its verdict (or failed), and the run's progress. */
export const runItemWireSchema = z.object({
  news_id: z.number().int(),
  vendor_item_id: z.string().optional(),
  verdict: verdictSchema.nullable(),
  confidence: z.number().min(0).max(1).optional(),
  review: z.boolean().optional(),
  failed: z.boolean().optional(),
  done: z.number().int().nonnegative(),
  total: z.number().int().nonnegative(),
});

/** `review`: an analyst decided (or the market open expired it). */
export const runReviewWireSchema = z.object({
  news_id: z.number().int(),
  status: reviewStatusSchema,
  verdict: verdictSchema,
});

/** `run.done`: the finished run's counts (a replay may carry only the status). */
export const runDoneWireSchema = z.object({
  status: z.string(),
  total: z.number().int().nonnegative().optional(),
  done: z.number().int().nonnegative().optional(),
  failed: z.number().int().nonnegative().optional(),
  verified: z.number().int().nonnegative().optional(),
  unverified: z.number().int().nonnegative().optional(),
  misleading: z.number().int().nonnegative().optional(),
  fake: z.number().int().nonnegative().optional(),
  pending_review: z.number().int().nonnegative().optional(),
  escalated: z.number().int().nonnegative().optional(),
});

/** `run.failed`: why the run failed. */
export const runFailedWireSchema = z.object({
  error: z.string().optional(),
  status: z.string().optional(),
});

/** One run event as the UI uses it. */
export type RunEvent =
  | {type: 'started'; total: number}
  | {
      type: 'item';
      newsId: number;
      vendorItemId: string | undefined;
      verdict: z.infer<typeof verdictSchema> | null;
      review: boolean;
      failed: boolean;
      done: number;
      total: number;
    }
  | {type: 'review'; newsId: number}
  | {type: 'done'; pendingReview: number | undefined}
  | {type: 'failed'; error: string};

export type ReviewTask = z.output<typeof reviewTaskSchema>;
export type ReviewDecision = z.infer<typeof reviewDecisionSchema>;
export type VerifyRunListWire = z.infer<typeof verifyRunListWireSchema>;
export type ReviewListWire = z.infer<typeof reviewListWireSchema>;
