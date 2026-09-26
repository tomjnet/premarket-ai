import type {
  AiEvidence,
  DupType,
  NewsItem,
  RuleEvidence,
  RuleRun,
  VerifyEvidence,
} from '@/api/schemas/news';

/**
 * Check badges: data-quality flags from the backend's deterministic rules
 * (increment 2) and from the AI run's guard, language check and dedup L3
 * (increment 3). They describe the vendor item, never the security.
 */

/** How a badge looks. The text is the signal; the colour only helps. */
export type BadgeTone = 'danger' | 'warning' | 'neutral' | 'success';

export interface RuleBadge {
  key: string;
  /** Visible text, for example `FAKE TICKER` or `DUPLICATE ×3`. */
  text: string;
  tone: BadgeTone;
  /** What a screen reader says instead of `text`, when that reads badly. */
  spokenText?: string;
}

// Known codes in display order; any other code follows them, neutral.
const KNOWN_CODES: ReadonlyArray<[string, BadgeTone]> = [
  ['FAKE_COMPANY', 'danger'],
  ['FAKE_TICKER', 'danger'],
  ['SPOOFED_SOURCE', 'danger'],
  ['INJECTION_ATTEMPT', 'danger'],
  ['FABRICATED_CLAIM', 'danger'],
  ['CONTRADICTED_BY_FILING', 'danger'],
  ['NUMBER_MISMATCH', 'warning'],
  ['STALE', 'warning'],
  ['SENSATIONAL_HEADLINE', 'warning'],
  ['UNSUPPORTED_LANGUAGE', 'neutral'],
];

const KNOWN_CODE_SET = new Set(KNOWN_CODES.map(([code]) => code));

const DUP_TYPE_TEXT: Record<DupType, string> = {
  url: 'same URL',
  exact: 'exact copy',
  near: 'near copy',
  paraphrase: 'paraphrase',
};

/** A rule check's, an AI-run step's or the verification's explanation. */
export type CheckEvidence =
  RuleEvidence | AiEvidence | Pick<VerifyEvidence, 'check' | 'code'>;

// The verify graph's checks (increment 4) can grow; unknown ones show
// their name.
const CHECK_TEXT: Record<string, string> = {
  entity: 'ENTITY CHECK',
  source: 'SOURCE CHECK',
  dedup: 'DUPLICATE',
  stale: 'STALE CHECK',
  guard: 'GUARD',
  language: 'LANGUAGE CHECK',
  corroboration: 'CORROBORATION',
  claim: 'CLAIM CHECK',
  style: 'HEADLINE CHECK',
  ml: 'CLASSIC ML',
  judge: 'LLM JUDGE',
  review: 'ANALYST',
};

/** `FAKE_TICKER` → `FAKE TICKER`. */
export function reasonCodeText(code: string): string {
  return code.replaceAll('_', ' ');
}

/** Known codes have a tone; unknown (later increments') codes are neutral. */
export function reasonCodeTone(code: string): BadgeTone {
  return KNOWN_CODES.find(([known]) => known === code)?.[1] ?? 'neutral';
}

/** How the rules matched a duplicate, in words: `near copy`. */
export function dupTypeText(dupType: DupType): string {
  return DUP_TYPE_TEXT[dupType];
}

/** The badge of one piece of evidence: its code, else the check's name. */
export function evidenceBadge(evidence: CheckEvidence): RuleBadge {
  if (evidence.code === null) {
    return {
      key: evidence.check,
      text:
        CHECK_TEXT[evidence.check] ??
        reasonCodeText(evidence.check).toUpperCase(),
      tone: 'neutral',
    };
  }
  return {
    key: evidence.code,
    text: reasonCodeText(evidence.code),
    tone: reasonCodeTone(evidence.code),
  };
}

function copiesText(copies: number): string {
  return `${copies} ${copies === 1 ? 'copy' : 'copies'} of this story`;
}

/**
 * The badges of an item, in display order: FAKE COMPANY, FAKE TICKER,
 * SPOOFED SOURCE, INJECTION ATTEMPT, STALE, UNSUPPORTED LANGUAGE, unknown
 * codes, then the duplicate badge. None
 * until the rules have checked the item.
 *
 * @param copiesState whether the feed shows or hides duplicates, for the
 *     spoken text of `DUPLICATE ×N`; undefined outside the feed.
 */
export function ruleBadges(
  item: Pick<
    NewsItem,
    'rulesChecked' | 'reasonCodes' | 'isDup' | 'dupType' | 'copies'
  >,
  copiesState?: 'hidden' | 'shown',
): RuleBadge[] {
  if (!item.rulesChecked) {
    return [];
  }
  const codes = new Set(item.reasonCodes);
  const known = KNOWN_CODES.map(([code]) => code).filter(code =>
    codes.has(code),
  );
  const unknown = [...codes].filter(code => !KNOWN_CODE_SET.has(code));
  const badges: RuleBadge[] = [...known, ...unknown].map(code => ({
    key: code,
    text: reasonCodeText(code),
    tone: reasonCodeTone(code),
  }));
  if (item.isDup) {
    const how = item.dupType === null ? undefined : dupTypeText(item.dupType);
    badges.push({
      key: 'DUPLICATE',
      text: item.dupType === null ? 'DUPLICATE' : `DUPLICATE · ${item.dupType}`,
      tone: 'neutral',
      spokenText: how === undefined ? 'Duplicate' : `Duplicate (${how})`,
    });
  } else if (item.copies > 0) {
    const state = copiesState === undefined ? '' : ` ${copiesState}`;
    badges.push({
      key: 'COPIES',
      text: `DUPLICATE ×${item.copies}`,
      tone: 'neutral',
      spokenText: `${copiesText(item.copies)}${state}`,
    });
  }
  return badges;
}

/** Whether the rules flagged the item (at least one reason code). */
export function isFlagged(item: Pick<NewsItem, 'reasonCodes'>): boolean {
  return item.reasonCodes.length > 0;
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? '' : 's'}`;
}

/**
 * The feed header's line about the date's rule run, for example
 * `Rule checks: 100 items · 14 duplicates · 17 flagged`.
 */
export function ruleRunSummary(ruleRun: RuleRun | null): string {
  if (ruleRun === null) {
    return "Rule checks haven't run for this date yet.";
  }
  const items = plural(ruleRun.items, 'item');
  if (ruleRun.status === 'RUNNING') {
    return `Rule checks are running: ${items} checked so far.`;
  }
  if (ruleRun.status === 'FAILED') {
    return `Rule checks failed after ${items}. Items marked "Not checked yet" have no rule badges.`;
  }
  return `Rule checks: ${items} · ${plural(ruleRun.duplicates, 'duplicate')} · ${ruleRun.flagged} flagged`;
}
