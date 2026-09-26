import {describe, expect, it} from 'vitest';

import {newsDetailSchema} from './news';
import {
  reviewDecisionSchema,
  reviewListSchema,
  verifyRunListSchema,
  verifyRunSchema,
} from './verify';

// Increment 4 wire examples, as ai-api serves them.
const wireRun = {
  run_id: 7,
  feed_date: '2026-09-24',
  status: 'RUNNING',
  requested_by: 'analyst1',
  requested_at: '2026-09-24T10:10:00Z',
  started_at: '2026-09-24T10:10:01Z',
  finished_at: null,
  total: 88,
  done: 37,
  failed: 0,
  verified: 25,
  unverified: 2,
  misleading: 3,
  fake: 7,
  pending_review: 3,
  escalated: 0,
  model: 'main-gpu4gb',
  error: null,
};

const wireTask = {
  id: 31,
  item_id: 2001,
  vendor_item_id: 'VND-20260924-001',
  feed_date: '2026-09-24',
  headline: '[SYNTHETIC] Apple raises dividend',
  source_domain: 'wire.vendornews.example',
  tickers: ['AAPL'],
  status: 'PENDING',
  reasons: ['low_confidence', 'judge_disagrees'],
  ai_verdict: 'VERIFIED',
  ai_confidence: 0.39,
  final_verdict: null,
  rule_verdict: 'VERIFIED',
  judge_verdict: 'UNVERIFIED',
  reason_codes: [],
  rationale: 'Trusted wire [E1].',
  impact: 'high',
  impact_score: 0.98,
  reviewer: null,
  comment: null,
  created_at: '2026-09-24T10:15:00Z',
  decided_at: null,
};

describe('verify schemas', () => {
  it('maps a verify run to the UI model', () => {
    expect(verifyRunSchema.parse(wireRun)).toMatchObject({
      runId: 7,
      feedDate: '2026-09-24',
      status: 'RUNNING',
      finishedAt: null,
      pendingReview: 3,
    });
    expect(
      verifyRunListSchema.parse({count: 1, items: [wireRun]})[0]?.done,
    ).toBe(37);
  });

  it('rejects drift in runs', () => {
    expect(
      verifyRunSchema.safeParse({...wireRun, status: 'PAUSED'}).success,
    ).toBe(false);
    expect(
      verifyRunListSchema.safeParse({count: 2, items: [wireRun]}).success,
    ).toBe(false);
  });

  it('maps review tasks, and checks verdicts and scores', () => {
    const [task] = reviewListSchema.parse({count: 1, items: [wireTask]});
    expect(task).toMatchObject({
      id: 31,
      itemId: 2001,
      aiVerdict: 'VERIFIED',
      judgeVerdict: 'UNVERIFIED',
      impactScore: 0.98,
    });
    for (const changes of [
      {ai_verdict: 'TRUE'},
      {ai_confidence: 1.5},
      {status: 'DONE'},
    ]) {
      expect(
        reviewListSchema.safeParse({
          count: 1,
          items: [{...wireTask, ...changes}],
        }).success,
      ).toBe(false);
    }
  });

  it('checks a decision like the backend', () => {
    expect(reviewDecisionSchema.safeParse({action: 'approve'}).success).toBe(
      true,
    );
    expect(
      reviewDecisionSchema.safeParse({
        action: 'override',
        verdict: 'FAKE',
        comment: 'Made up.',
      }).success,
    ).toBe(true);
    for (const bad of [
      {action: 'override', verdict: 'FAKE', comment: '  '},
      {action: 'override', comment: 'Made up.'},
      {action: 'delete'},
    ]) {
      expect(reviewDecisionSchema.safeParse(bad).success).toBe(false);
    }
  });

  it('maps a verification with its evidence and review', () => {
    const detail = newsDetailSchema.parse({
      id: 2001,
      vendor_item_id: 'VND-20260924-001',
      feed_date: '2026-09-24',
      headline: '[SYNTHETIC] Apple raises dividend',
      excerpt: 'Apple raised it.',
      source_url: 'https://wire.vendornews.example/a',
      source_domain: 'wire.vendornews.example',
      published_at: '2026-09-24T08:12:00Z',
      tickers: ['AAPL'],
      synthetic: true,
      is_dup: false,
      dup_of: null,
      reason_codes: [],
      dup_type: null,
      copies: 0,
      rules_checked: true,
      summary: null,
      sentiment: null,
      verdict: 'VERIFIED',
      confidence: 0.39,
      review_status: 'PENDING',
      verdict_source: 'ai',
      body: 'Body.',
      rule_evidence: [],
      ai: null,
      verification: {
        status: 'PENDING_REVIEW',
        verdict: 'VERIFIED',
        confidence: 0.39,
        reason_codes: [],
        rationale: 'Trusted wire [E1].',
        rule_verdict: 'VERIFIED',
        rule_confidence: 0.75,
        judge_verdict: 'UNVERIFIED',
        judge_confidence: 0.9,
        judge_model: 'main-gpu4gb',
        escalated: false,
        review_status: 'PENDING',
        review_reasons: ['low_confidence'],
        impact: 'high',
        impact_score: 0.98,
        prompt_version: 'verify-v1',
        verified_at: '2026-09-24T10:15:00Z',
        evidence: [
          {
            seq: 1,
            check: 'corroboration',
            code: null,
            message: 'A primary source reports it.',
            source: 'filing',
            url: 'https://www.sec.gov/x',
            title: '8-K',
          },
        ],
        review: {
          id: 31,
          status: 'PENDING',
          reasons: ['low_confidence'],
          ai_verdict: 'VERIFIED',
          final_verdict: null,
          reviewer: null,
          comment: null,
          created_at: '2026-09-24T10:15:00Z',
          decided_at: null,
        },
      },
    });
    expect(detail).toMatchObject({
      verdict: 'VERIFIED',
      reviewStatus: 'PENDING',
      verdictSource: 'ai',
    });
    expect(detail.verification).toMatchObject({
      ruleVerdict: 'VERIFIED',
      judgeVerdict: 'UNVERIFIED',
      reviewReasons: ['low_confidence'],
      review: {id: 31, aiVerdict: 'VERIFIED'},
    });
    expect(detail.verification?.evidence[0]?.url).toBe('https://www.sec.gov/x');
  });
});
