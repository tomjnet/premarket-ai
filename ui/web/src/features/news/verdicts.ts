import type {
  Impact,
  NewsItem,
  ReviewStatus,
  Verdict,
  VerifyRun,
} from '@/api/schemas/news';

import type {RuleBadge} from './rules';

/**
 * What the AI verification (increment 4) adds: one of four verdicts per
 * item with a confidence, the evidence behind it, and an analyst's review
 * when the AI wasn't sure. A verdict describes the vendor item (is the
 * story real?), never the security.
 */

export const VERDICTS: readonly Verdict[] = [
  'VERIFIED',
  'UNVERIFIED',
  'MISLEADING',
  'FAKE',
];

const VERDICT_TEXT: Record<Verdict, string> = {
  VERIFIED: 'Verified',
  UNVERIFIED: 'Unverified',
  MISLEADING: 'Misleading',
  FAKE: 'Fake',
};

/** What each verdict means, for the detail page and the review queue. */
export const VERDICT_MEANING: Record<Verdict, string> = {
  VERIFIED:
    'A real company, and the story is confirmed by a primary source or trusted outlets.',
  UNVERIFIED:
    'Nothing contradicts the story, but nothing confirms it yet. It may be real breaking news.',
  MISLEADING:
    'A real company, but key facts are wrong: a number, old news shown as new, or a headline that exaggerates.',
  FAKE: 'The company or ticker doesn’t exist, a primary source contradicts it, or the source is spoofed.',
};

const REVIEW_BADGES: Record<ReviewStatus, Omit<RuleBadge, 'key'>> = {
  PENDING: {
    text: 'PENDING REVIEW',
    tone: 'warning',
    spokenText: 'Pending review: an analyst hasn’t checked this verdict yet',
  },
  APPROVED: {
    text: 'REVIEWED',
    tone: 'neutral',
    spokenText: 'Reviewed: an analyst approved the verdict',
  },
  OVERRIDDEN: {
    text: 'ANALYST VERDICT',
    tone: 'neutral',
    spokenText: 'Analyst verdict: an analyst changed the verdict',
  },
  EXPIRED: {
    text: 'UNREVIEWED',
    tone: 'neutral',
    spokenText: 'Unreviewed: nobody checked it before the market opened',
  },
};

const REASON_TEXT: Record<string, string> = {
  low_confidence: 'Low confidence',
  judge_disagrees: 'The LLM judge disagrees with the rules',
  guard_unsafe: 'Llama Guard flagged the text',
  unsupported_language: 'Not in English',
};

const IMPACT_TEXT: Record<Impact, string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
};

/** `FAKE` → `Fake`. */
export function verdictText(verdict: Verdict): string {
  return VERDICT_TEXT[verdict];
}

/** A 0–1 confidence as a whole percentage: `0.91` → `91%`. */
export function confidenceText(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}

/** Why an item went to review, in words (unknown reasons as their text). */
export function reviewReasonText(reason: string): string {
  return REASON_TEXT[reason] ?? reason.replaceAll('_', ' ');
}

/** `high` → `High`. */
export function impactText(impact: Impact): string {
  return IMPACT_TEXT[impact];
}

/**
 * The verdict badge of an item: red FAKE, amber MISLEADING, green VERIFIED,
 * neutral UNVERIFIED. The text is the signal; the colour only helps. A
 * duplicate's verdict is its original's, and says so.
 */
export function verdictBadge(
  item: Pick<NewsItem, 'verdict' | 'verdictSource'>,
): RuleBadge | undefined {
  if (item.verdict === null) {
    return undefined;
  }
  const tones = {
    VERIFIED: 'success',
    UNVERIFIED: 'neutral',
    MISLEADING: 'warning',
    FAKE: 'danger',
  } as const;
  const inherited = item.verdictSource === 'inherited';
  return {
    key: 'VERDICT',
    text: item.verdict,
    tone: tones[item.verdict],
    spokenText: `${inherited ? 'Verdict of the original story' : 'Verdict'}: ${verdictText(item.verdict).toLowerCase()}`,
  };
}

/** The review badge (PENDING REVIEW, REVIEWED...), if there is a review. */
export function reviewBadge(
  reviewStatus: ReviewStatus | null,
): RuleBadge | undefined {
  if (reviewStatus === null) {
    return undefined;
  }
  return {key: 'REVIEW', ...REVIEW_BADGES[reviewStatus]};
}

/** The verdict and review badges of an item, in display order. */
export function verdictBadges(
  item: Pick<NewsItem, 'verdict' | 'verdictSource' | 'reviewStatus'>,
): RuleBadge[] {
  return [verdictBadge(item), reviewBadge(item.reviewStatus)].filter(
    (badge): badge is RuleBadge => badge !== undefined,
  );
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? '' : 's'}`;
}

/**
 * The feed header's line about the date's verify run, for example
 * `Verdicts: 58 verified · 4 unverified · 9 misleading · 17 fake · 6
 * waiting for review`.
 */
export function verifyRunSummary(run: VerifyRun | null): string {
  if (run === null) {
    return "The AI verification hasn't run for this date yet.";
  }
  if (run.status === 'QUEUED') {
    return 'The AI verification is queued.';
  }
  if (run.status === 'RUNNING') {
    return `The AI verification is running: ${run.done} of ${plural(run.total, 'item')} done.`;
  }
  if (run.status === 'FAILED') {
    return `The AI verification failed after ${plural(run.done, 'item')}.${
      run.error === null ? '' : ` ${run.error}`
    }`;
  }
  const parts = [
    `Verdicts: ${run.verified} verified`,
    `${run.unverified} unverified`,
    `${run.misleading} misleading`,
    `${run.fake} fake`,
  ];
  if (run.pendingReview > 0) {
    parts.push(`${run.pendingReview} waiting for review`);
  }
  if (run.failed > 0) {
    parts.push(`${run.failed} failed`);
  }
  return parts.join(' · ');
}
