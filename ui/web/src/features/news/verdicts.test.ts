import {describe, expect, it} from 'vitest';

import type {VerifyRun} from '@/api/schemas/news';

import {
  confidenceText,
  reviewBadge,
  reviewReasonText,
  verdictBadge,
  verdictBadges,
  verifyRunSummary,
} from './verdicts';

const run: VerifyRun = {
  runId: 7,
  feedDate: '2026-09-24',
  status: 'DONE',
  requestedBy: 'analyst1',
  requestedAt: '2026-09-24T10:10:00Z',
  startedAt: '2026-09-24T10:10:01Z',
  finishedAt: '2026-09-24T10:20:00Z',
  total: 88,
  done: 88,
  failed: 0,
  verified: 58,
  unverified: 4,
  misleading: 9,
  fake: 17,
  pendingReview: 6,
  escalated: 1,
  model: 'main-gpu4gb',
  error: null,
};

describe('verdict badges', () => {
  it('gives each verdict its tone; the words carry the meaning', () => {
    const tones = (
      ['VERIFIED', 'UNVERIFIED', 'MISLEADING', 'FAKE'] as const
    ).map(verdict => verdictBadge({verdict, verdictSource: 'ai'})?.tone);
    expect(tones).toEqual(['success', 'neutral', 'warning', 'danger']);
    expect(verdictBadge({verdict: 'FAKE', verdictSource: 'ai'})).toMatchObject({
      text: 'FAKE',
      spokenText: 'Verdict: fake',
    });
  });

  it("says a duplicate's verdict is its original's", () => {
    expect(
      verdictBadge({verdict: 'MISLEADING', verdictSource: 'inherited'})
        ?.spokenText,
    ).toBe('Verdict of the original story: misleading');
  });

  it('has no badge before the verification', () => {
    expect(verdictBadge({verdict: null, verdictSource: null})).toBeUndefined();
    expect(
      verdictBadges({verdict: null, verdictSource: null, reviewStatus: null}),
    ).toEqual([]);
  });

  it('adds the review state after the verdict', () => {
    const badges = verdictBadges({
      verdict: 'VERIFIED',
      verdictSource: 'ai',
      reviewStatus: 'PENDING',
    });
    expect(badges.map(badge => [badge.text, badge.tone])).toEqual([
      ['VERIFIED', 'success'],
      ['PENDING REVIEW', 'warning'],
    ]);
    expect(reviewBadge('OVERRIDDEN')?.text).toBe('ANALYST VERDICT');
    expect(reviewBadge('EXPIRED')?.spokenText).toContain('market opened');
    expect(reviewBadge(null)).toBeUndefined();
  });
});

describe('verifyRunSummary', () => {
  it('counts the verdicts of a finished run', () => {
    expect(verifyRunSummary(run)).toBe(
      'Verdicts: 58 verified · 4 unverified · 9 misleading · 17 fake · 6 waiting for review',
    );
    expect(verifyRunSummary({...run, pendingReview: 0, failed: 2})).toBe(
      'Verdicts: 58 verified · 4 unverified · 9 misleading · 17 fake · 2 failed',
    );
  });

  it('describes every other state', () => {
    expect(verifyRunSummary(null)).toBe(
      "The AI verification hasn't run for this date yet.",
    );
    expect(verifyRunSummary({...run, status: 'QUEUED'})).toBe(
      'The AI verification is queued.',
    );
    expect(verifyRunSummary({...run, status: 'RUNNING', done: 37})).toBe(
      'The AI verification is running: 37 of 88 items done.',
    );
    expect(
      verifyRunSummary({
        ...run,
        status: 'FAILED',
        done: 1,
        error: 'AI run missing',
      }),
    ).toBe('The AI verification failed after 1 item. AI run missing');
  });
});

describe('texts', () => {
  it('shows confidences as whole percentages', () => {
    expect(confidenceText(0.905)).toBe('91%');
    expect(confidenceText(0)).toBe('0%');
  });

  it('names the review reasons, and unknown ones by their text', () => {
    expect(reviewReasonText('judge_disagrees')).toBe(
      'The LLM judge disagrees with the rules',
    );
    expect(reviewReasonText('some_new_reason')).toBe('some new reason');
  });
});
