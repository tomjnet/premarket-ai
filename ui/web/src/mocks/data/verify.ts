import type {
  NewsDetailWire,
  Verdict,
  VerificationWire,
  VerifyEvidenceWire,
  VerifyRunWire,
} from '@/api/schemas/news';
import type {ReviewTaskWire} from '@/api/schemas/verify';
import {addSeconds} from '@/lib/time';

import {
  LOW_QUALITY_DOMAINS,
  REAL_COMPANIES,
  TRUSTED_DOMAINS,
} from './companies';

/**
 * The mock's stand-in for the backend's AI verification (increment 4): a
 * verdict with its evidence for every unique item the AI run processed,
 * the review queue, and the verify run's counts. The rules follow the
 * backend's policy on what the mock data has:
 *
 * - FAKE: FAKE_COMPANY, FAKE_TICKER or SPOOFED_SOURCE (hard rules, no judge).
 * - MISLEADING: STALE, or a planted sensational headline (every
 *   `SENSATIONAL_EVERY`th item).
 * - UNVERIFIED: not English, a failed AI run, or a low-quality outlet
 *   (NO_CORROBORATION).
 * - VERIFIED: a trusted-tier wire with every check clean (the lab rule).
 *
 * Review: every `DISAGREE_EVERY`th verified item (the judge disagrees),
 * low-quality outlets with an even item number, and every non-English
 * item wait for an analyst. The first disagreement is escalated to the
 * cloud model. Duplicates inherit their original's verdict (a stale copy
 * is MISLEADING).
 */

/** The first feed date the verify run covers (the AI run's first date). */
export const VERIFY_START_DATE = '2026-09-24';
export const JUDGE_MODEL = 'main-gpu4gb';
export const CLOUD_MODEL = 'cloud-openai';
export const VERIFY_PROMPT_VERSION = 'verify-v1';
/** The verify run ends this long after the AI run. */
export const VERIFY_RUN_SECONDS = 10 * 60;
export const SENSATIONAL_EVERY = 17;
export const DISAGREE_EVERY = 11;
/** The mock run id of a date's generated verify run. */
export const GENERATED_RUN_OFFSET = 900_000;

const HARD_CODES = ['FAKE_COMPANY', 'FAKE_TICKER', 'SPOOFED_SOURCE'];
const HIGH_RELEVANCE =
  /\b(?:revenue|earnings|guidance|outlook|acquir\w*|merger|resign\w*|ceo|halt\w*|recall|probe|approval)\b/i;
const MEDIUM_RELEVANCE =
  /\b(?:dividend|buyback|repurchase|partnership|contract|cfo|names|appoints)\b/i;

function itemNumber(item: NewsDetailWire): number {
  return item.id % 1000;
}

function round(value: number): number {
  return Math.round(value * 1000) / 1000;
}

/** Relevance of the news kind x company size (the review order). */
function impactOf(item: NewsDetailWire): {
  relevance: number;
  score: number;
  level: 'low' | 'medium' | 'high';
} {
  const headline = item.headline;
  let relevance = 0.3;
  if (HIGH_RELEVANCE.test(headline)) {
    relevance = 1;
  } else if (MEDIUM_RELEVANCE.test(headline)) {
    relevance = 0.6;
  }
  const rank = REAL_COMPANIES.findIndex(company =>
    item.tickers.includes(company.ticker),
  );
  const size =
    rank === -1 ? 0.4 : 1 - (0.5 * rank) / (REAL_COMPANIES.length - 1);
  const score = round(relevance * size);
  let level: 'low' | 'medium' | 'high' = 'low';
  if (score >= 0.66) {
    level = 'high';
  } else if (score >= 0.33) {
    level = 'medium';
  }
  return {relevance, score, level};
}

interface Decision {
  verdict: Verdict;
  confidence: number;
  codes: string[];
  rationale: string;
  ruleVerdict: Verdict;
  ruleConfidence: number;
  judge: {verdict: Verdict; confidence: number; model: string} | null;
  reasons: string[];
}

function decide(item: NewsDetailWire, escalate: boolean): Decision {
  const codes = new Set(item.reason_codes);
  const number = itemNumber(item);
  const hard = HARD_CODES.filter(code => codes.has(code));
  if (hard.length > 0) {
    return {
      verdict: 'FAKE',
      confidence: round(Math.min(0.99, 0.95 + 0.02 * (hard.length - 1))),
      codes: [...codes],
      rationale: `Hard rule: ${hard.join(', ')}. Deterministic evidence decides FAKE; the LLM judge can't override it.`,
      ruleVerdict: 'FAKE',
      ruleConfidence: 0.95,
      judge: null,
      reasons: [],
    };
  }
  if (codes.has('UNSUPPORTED_LANGUAGE')) {
    return {
      verdict: 'UNVERIFIED',
      confidence: 0.5,
      codes: [...codes],
      rationale:
        'Not English: the model steps were skipped and an analyst has to read it.',
      ruleVerdict: 'UNVERIFIED',
      ruleConfidence: 0.5,
      judge: null,
      reasons: ['low_confidence', 'unsupported_language'],
    };
  }
  if (codes.has('STALE')) {
    return {
      verdict: 'MISLEADING',
      confidence: 0.94,
      codes: [...codes],
      rationale: 'Old news presented as new [E3]: a real story, re-served.',
      ruleVerdict: 'MISLEADING',
      ruleConfidence: 0.85,
      judge: {verdict: 'MISLEADING', confidence: 0.9, model: JUDGE_MODEL},
      reasons: [],
    };
  }
  if (number % SENSATIONAL_EVERY === 0) {
    return {
      verdict: 'MISLEADING',
      confidence: 0.87,
      codes: [...codes, 'SENSATIONAL_HEADLINE'],
      rationale:
        'The headline exaggerates a routine story [E4]; the facts in the body are ordinary.',
      ruleVerdict: 'MISLEADING',
      ruleConfidence: 0.72,
      judge: {verdict: 'MISLEADING', confidence: 0.85, model: JUDGE_MODEL},
      reasons: [],
    };
  }
  if (item.ai?.status === 'FAILED') {
    return {
      verdict: 'UNVERIFIED',
      confidence: 0.6,
      codes: [...codes, 'NO_CORROBORATION'],
      rationale:
        'Nothing contradicts it, but no primary source or trusted outlet reports it yet.',
      ruleVerdict: 'UNVERIFIED',
      ruleConfidence: 0.6,
      judge: null,
      reasons: ['low_confidence'],
    };
  }
  if (LOW_QUALITY_DOMAINS.includes(item.source_domain)) {
    const disagree = number % 2 === 0;
    return {
      verdict: 'UNVERIFIED',
      confidence: disagree ? 0.52 : 0.78,
      codes: [...codes, 'NO_CORROBORATION'],
      rationale:
        'A low-reputation outlet, and no filing or other outlet reports it [E2].',
      ruleVerdict: 'UNVERIFIED',
      ruleConfidence: 0.6,
      judge: {
        verdict: disagree ? 'MISLEADING' : 'UNVERIFIED',
        confidence: 0.8,
        model: JUDGE_MODEL,
      },
      reasons: disagree ? ['low_confidence', 'judge_disagrees'] : [],
    };
  }
  const trusted = TRUSTED_DOMAINS.includes(item.source_domain);
  const disagree = number % DISAGREE_EVERY === 0;
  if (disagree) {
    return {
      verdict: 'VERIFIED',
      confidence: 0.39,
      codes: [...codes],
      rationale:
        "From a trusted-tier newswire with every check clean (lab rule: the synthetic story can't be found anywhere else).",
      ruleVerdict: 'VERIFIED',
      ruleConfidence: 0.75,
      judge: {
        verdict: 'UNVERIFIED',
        confidence: 0.9,
        model: escalate ? CLOUD_MODEL : JUDGE_MODEL,
      },
      reasons: ['low_confidence', 'judge_disagrees'],
    };
  }
  return {
    verdict: trusted ? 'VERIFIED' : 'UNVERIFIED',
    confidence: trusted ? 0.91 : 0.78,
    codes: trusted ? [...codes] : [...codes, 'NO_CORROBORATION'],
    rationale: trusted
      ? 'Trusted-tier wire, a registered company, and every check clean [E1][E2].'
      : 'Nothing contradicts it, but only one outlet reports it [E2].',
    ruleVerdict: trusted ? 'VERIFIED' : 'UNVERIFIED',
    ruleConfidence: trusted ? 0.75 : 0.6,
    judge: {
      verdict: trusted ? 'VERIFIED' : 'UNVERIFIED',
      confidence: 0.9,
      model: JUDGE_MODEL,
    },
    reasons: [],
  };
}

function evidenceOf(
  item: NewsDetailWire,
  decision: Decision,
): VerifyEvidenceWire[] {
  const found: Array<Omit<VerifyEvidenceWire, 'seq'>> = [];
  const ticker = item.tickers[0];
  const low = LOW_QUALITY_DOMAINS.includes(item.source_domain);
  const trusted = TRUSTED_DOMAINS.includes(item.source_domain);
  let tier = 'not in the source reputation list';
  if (trusted) {
    tier = 'trusted source, reputation 0.90';
  } else if (low) {
    tier = 'low source, reputation 0.15';
  }
  found.push({
    check: 'source',
    code: null,
    message: `${item.source_domain}: ${tier}.`,
    source: 'reputation',
    url: null,
    title: null,
  });
  found.push({
    check: 'corroboration',
    code: null,
    message: `No SEC filing of ${ticker ?? 'the company'}'s from the 7 days before ${item.feed_date} reports this story. Web search: no other outlet reports it.`,
    source: 'web',
    url: null,
    title: null,
  });
  for (const entry of item.rule_evidence) {
    found.push({...entry, source: 'rules', url: null, title: null});
  }
  found.push({
    check: 'style',
    code: decision.codes.includes('SENSATIONAL_HEADLINE')
      ? 'SENSATIONAL_HEADLINE'
      : null,
    message: decision.codes.includes('SENSATIONAL_HEADLINE')
      ? 'Sensational headline: its wording oversells a routine story.'
      : 'The headline is sober.',
    source: 'text',
    url: null,
    title: null,
  });
  if (itemNumber(item) % 5 === 0 && decision.verdict === 'VERIFIED') {
    // A linked primary source, so the drill-down shows a link.
    found.push({
      check: 'corroboration',
      code: null,
      message: 'A primary source reports it: 8-K current report.',
      source: 'filing',
      url: 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent',
      title: '8-K current report',
    });
  }
  if (decision.judge !== null) {
    found.push({
      check: 'judge',
      code: null,
      message: `${decision.judge.model}: ${decision.judge.verdict} (confidence ${decision.judge.confidence.toFixed(2)}). ${decision.rationale}`,
      source: 'model',
      url: null,
      title: null,
    });
  }
  return found.map((entry, index) => ({...entry, seq: index + 1}));
}

/** A verified item's verification, as `GET /news/{id}` serves it. */
function verificationOf(
  item: NewsDetailWire,
  decision: Decision,
  verifiedAt: string,
  escalated: boolean,
): VerificationWire {
  const impact = impactOf(item);
  const pending = decision.reasons.length > 0;
  return {
    status: pending ? 'PENDING_REVIEW' : 'DONE',
    verdict: decision.verdict,
    confidence: decision.confidence,
    reason_codes: decision.codes,
    rationale: decision.rationale,
    rule_verdict: decision.ruleVerdict,
    rule_confidence: decision.ruleConfidence,
    judge_verdict: decision.judge?.verdict ?? null,
    judge_confidence: decision.judge?.confidence ?? null,
    judge_model: decision.judge?.model ?? null,
    escalated,
    review_status: pending ? 'PENDING' : null,
    review_reasons: decision.reasons,
    impact: impact.level,
    impact_score: impact.score,
    prompt_version: VERIFY_PROMPT_VERSION,
    verified_at: verifiedAt,
    evidence: evidenceOf(item, decision),
    review: pending
      ? {
          id: item.id,
          status: 'PENDING',
          reasons: decision.reasons,
          ai_verdict: decision.verdict,
          final_verdict: null,
          reviewer: null,
          comment: null,
          created_at: verifiedAt,
          decided_at: null,
        }
      : null,
  };
}

/** Whether the verify run verified this item (not inherited). */
function verified(item: NewsDetailWire): boolean {
  return item.ai !== null && item.ai.status !== 'DUPLICATE' && !item.is_dup;
}

/**
 * The items as served after the date's verify run, and the run.
 *
 * @param items the day's items after the AI run (newest first).
 * @param date the feed date.
 * @param aiFinishedAt when the AI run ended.
 */
export function applyVerifyRun(
  items: readonly NewsDetailWire[],
  date: string,
  aiFinishedAt: string,
): {items: NewsDetailWire[]; verifyRun: VerifyRunWire} {
  const verifiedAt = addSeconds(aiFinishedAt, VERIFY_RUN_SECONDS);
  let escalations = 0;
  const own = new Map<string, NewsDetailWire>();
  const withOwn = items.map(item => {
    if (!verified(item)) {
      return item;
    }
    const firstDisagreement =
      escalations === 0 &&
      itemNumber(item) % DISAGREE_EVERY === 0 &&
      item.reason_codes.length === 0 &&
      TRUSTED_DOMAINS.includes(item.source_domain);
    const decision = decide(item, firstDisagreement);
    if (firstDisagreement) {
      escalations += 1;
    }
    const verification = verificationOf(
      item,
      decision,
      verifiedAt,
      firstDisagreement,
    );
    const next: NewsDetailWire = {
      ...item,
      reason_codes: [
        ...item.reason_codes,
        ...decision.codes.filter(code => !item.reason_codes.includes(code)),
      ],
      verdict: decision.verdict,
      confidence: decision.confidence,
      review_status: verification.review_status,
      verdict_source: 'ai',
      verification,
    };
    own.set(item.vendor_item_id, next);
    return next;
  });
  // Duplicates show their original's verdict; a stale copy is MISLEADING.
  const served = withOwn.map(item => {
    if (!item.is_dup || item.dup_of === null || !item.rules_checked) {
      return item;
    }
    const stale = item.reason_codes.includes('STALE');
    const original = own.get(item.dup_of);
    if (!stale && original === undefined) {
      return item;
    }
    return {
      ...item,
      verdict: stale ? 'MISLEADING' : (original?.verdict ?? null),
      confidence: stale ? 0.9 : (original?.confidence ?? null),
      review_status: stale ? null : (original?.review_status ?? null),
      verdict_source: 'inherited' as const,
      verification: stale ? null : (original?.verification ?? null),
    };
  });
  const mine = [...own.values()];
  const count = (verdict: Verdict) =>
    mine.filter(item => item.verdict === verdict).length;
  return {
    items: served,
    verifyRun: {
      run_id: GENERATED_RUN_OFFSET + dayNumber(date),
      feed_date: date,
      status: 'DONE',
      requested_by: 'analyst1',
      requested_at: aiFinishedAt,
      started_at: addSeconds(aiFinishedAt, 5),
      finished_at: verifiedAt,
      total: mine.length,
      done: mine.length,
      failed: 0,
      verified: count('VERIFIED'),
      unverified: count('UNVERIFIED'),
      misleading: count('MISLEADING'),
      fake: count('FAKE'),
      pending_review: mine.filter(item => item.review_status === 'PENDING')
        .length,
      escalated: escalations,
      model: JUDGE_MODEL,
      error: null,
    },
  };
}

/** A small, stable number for a date (the generated run's id). */
function dayNumber(date: string): number {
  return Number(date.replaceAll('-', '')) % 100_000;
}

/** An item's review task, as `GET /review` serves it. */
export function reviewTaskOf(item: NewsDetailWire): ReviewTaskWire | undefined {
  const verification = item.verification;
  const review = verification?.review;
  if (
    verification === null ||
    verification === undefined ||
    review === null ||
    review === undefined ||
    item.verdict_source !== 'ai'
  ) {
    return undefined;
  }
  return {
    id: review.id,
    item_id: item.id,
    vendor_item_id: item.vendor_item_id,
    feed_date: item.feed_date,
    headline: item.headline,
    source_domain: item.source_domain,
    tickers: item.tickers,
    status: review.status,
    reasons: review.reasons,
    ai_verdict: review.ai_verdict,
    ai_confidence: verification.confidence ?? 0,
    final_verdict: review.final_verdict,
    rule_verdict: verification.rule_verdict,
    judge_verdict: verification.judge_verdict,
    reason_codes: verification.reason_codes,
    rationale: verification.rationale,
    impact: verification.impact,
    impact_score: verification.impact_score ?? 0,
    reviewer: review.reviewer,
    comment: review.comment,
    created_at: review.created_at,
    decided_at: review.decided_at,
  };
}

/** What `POST /review/{id}` stored for a task (see `MockDb.reviews`). */
export interface StoredReview {
  action: 'approve' | 'override';
  verdict: Verdict | null;
  comment: string;
  reviewer: string;
  decidedAt: string;
}

/**
 * An item as served after an analyst decided its review (a duplicate
 * follows its original's review too). Unchanged without a decision.
 */
export function withReview(
  item: NewsDetailWire,
  decision: StoredReview | undefined,
): NewsDetailWire {
  const verification = item.verification;
  const review = verification?.review;
  if (
    decision === undefined ||
    verification === null ||
    verification === undefined ||
    review === null ||
    review === undefined
  ) {
    return item;
  }
  const status = decision.action === 'override' ? 'OVERRIDDEN' : 'APPROVED';
  const verdict = decision.verdict ?? review.ai_verdict;
  return {
    ...item,
    // A duplicate shows its original's verdict (stale copies have none).
    verdict,
    review_status: status,
    verification: {
      ...verification,
      status: 'DONE',
      verdict,
      review_status: status,
      review: {
        ...review,
        status,
        final_verdict: verdict,
        reviewer: decision.reviewer,
        comment: decision.comment === '' ? null : decision.comment,
        decided_at: decision.decidedAt,
      },
    },
  };
}
