import type {
  DupType,
  NewsDetailWire,
  RuleEvidenceWire,
  RuleRunWire,
  RunStatus,
} from '@/api/schemas/news';
import {addDays} from '@/lib/time';

import {FAKE_COMPANIES, REAL_COMPANIES} from './companies';

/**
 * The mock's stand-in for the backend's deterministic rule engine
 * (increment 2): entity, source, dedup and stale checks. The results are
 * made up from what the generator knows, with the same codes and the same
 * kind of plain-text evidence as the real engine.
 */

/** The legacy exact-hash flags, served while the rules haven't run. */
export interface LegacyDup {
  is_dup: boolean;
  dup_of: string | null;
}

export const NOT_A_DUPLICATE: LegacyDup = {is_dup: false, dup_of: null};

/** What the rules add to an item they haven't checked. */
export const UNCHECKED = {
  reason_codes: [],
  dup_type: null,
  copies: 0,
  rules_checked: false,
  rule_evidence: [],
  // The AI run only enriches checked items.
  summary: null,
  sentiment: null,
  ai: null,
} as const satisfies Partial<NewsDetailWire>;

const REGISTRY_TICKERS = 10_381;
const KNOWN_TICKERS = new Set(REAL_COMPANIES.map(company => company.ticker));
// Lookalike domain → the outlet it imitates and that outlet's real domain.
const IMITATED_OUTLETS: ReadonlyMap<string, [string, string]> = new Map([
  ['reuters-news.test', ['reuters', 'reuters.com']],
  ['bloomberg-markets.test', ['bloomberg', 'bloomberg.com']],
  ['cnbc-alerts.test', ['cnbc', 'cnbc.com']],
  ['wsj-finance.test', ['wsj', 'wsj.com']],
]);
const CHECK_ORDER: readonly string[] = ['entity', 'source', 'dedup', 'stale'];

/** Entity check: tickers and company names missing from the SEC registry. */
export function entityEvidence(
  item: Pick<NewsDetailWire, 'tickers' | 'headline' | 'body' | 'feed_date'>,
): RuleEvidenceWire[] {
  const refreshed = addDays(item.feed_date, -1);
  const evidence: RuleEvidenceWire[] = [];
  for (const company of FAKE_COMPANIES) {
    if (`${item.headline}\n${item.body}`.includes(company.short)) {
      evidence.push({
        check: 'entity',
        code: 'FAKE_COMPANY',
        message: `No company named ${company.short} is in the SEC company registry (refreshed ${refreshed}).`,
      });
    }
  }
  for (const ticker of item.tickers) {
    if (!KNOWN_TICKERS.has(ticker)) {
      evidence.push({
        check: 'entity',
        code: 'FAKE_TICKER',
        message: `Ticker ${ticker} is not in the SEC ticker registry (${REGISTRY_TICKERS.toLocaleString('en-US')} tickers, refreshed ${refreshed}).`,
      });
    }
  }
  return evidence;
}

/** Source check: domains that imitate a known outlet. */
export function sourceEvidence(domain: string): RuleEvidenceWire[] {
  const imitated = IMITATED_OUTLETS.get(domain);
  if (imitated === undefined) {
    return [];
  }
  const [outlet, official] = imitated;
  return [
    {
      check: 'source',
      code: 'SPOOFED_SOURCE',
      message: `${domain} imitates ${outlet} (official domain: ${official}).`,
    },
  ];
}

/** How the dedup check matched a copy to its original. */
export interface DedupMatch {
  type: DupType;
  original: Pick<NewsDetailWire, 'vendor_item_id' | 'feed_date'>;
  /** Hamming distance of the SimHashes, for a `near` match. */
  distance?: number;
}

/** Dedup evidence, plus the stale evidence for a copy of an earlier day. */
export function dedupEvidence(
  match: DedupMatch,
  feedDate: string,
): RuleEvidenceWire[] {
  const id = match.original.vendor_item_id;
  const from = match.original.feed_date;
  const where = from === feedDate ? 'earlier in this feed' : `from ${from}`;
  let how = `Same canonical URL (L0) as ${id}`;
  if (match.type === 'exact') {
    how = `Exact copy (L1) of ${id}`;
  } else if (match.type === 'near') {
    how = `Near copy (L2, SimHash distance ${match.distance ?? 1}) of ${id}`;
  } else if (match.type === 'paraphrase') {
    how = `Paraphrase (L3) of ${id}`;
  }
  const evidence: RuleEvidenceWire[] = [
    {check: 'dedup', code: null, message: `${how}, ${where}.`},
  ];
  if (from < feedDate) {
    evidence.push({
      check: 'stale',
      code: 'STALE',
      message: `First published for ${from}, before this feed's session: re-served old news.`,
    });
  }
  return evidence;
}

/** The checked fields of an item with this evidence. */
export function checkedFields(
  evidence: readonly RuleEvidenceWire[],
  match: DedupMatch | undefined,
): Pick<
  NewsDetailWire,
  | 'reason_codes'
  | 'dup_type'
  | 'rules_checked'
  | 'rule_evidence'
  | 'is_dup'
  | 'dup_of'
> {
  const sorted = [...evidence].sort(
    (a, b) => CHECK_ORDER.indexOf(a.check) - CHECK_ORDER.indexOf(b.check),
  );
  const codes = new Set<string>();
  for (const entry of sorted) {
    if (entry.code !== null) {
      codes.add(entry.code);
    }
  }
  return {
    reason_codes: [...codes].sort(),
    dup_type: match?.type ?? null,
    rules_checked: true,
    rule_evidence: sorted,
    is_dup: match !== undefined,
    dup_of: match?.original.vendor_item_id ?? null,
  };
}

/**
 * The items as served when only `isChecked` items have been through the
 * rules: the others keep the legacy flags. `copies` counts the checked
 * items that the rules linked to each item.
 */
export function withRuleProgress(
  items: readonly NewsDetailWire[],
  legacy: ReadonlyMap<number, LegacyDup>,
  isChecked: (item: NewsDetailWire) => boolean,
): NewsDetailWire[] {
  const copies = new Map<string, number>();
  for (const item of items) {
    if (isChecked(item) && item.dup_type !== null && item.dup_of !== null) {
      copies.set(item.dup_of, (copies.get(item.dup_of) ?? 0) + 1);
    }
  }
  return items.map(item =>
    isChecked(item)
      ? {...item, copies: copies.get(item.vendor_item_id) ?? 0}
      : {...item, ...UNCHECKED, ...(legacy.get(item.id) ?? NOT_A_DUPLICATE)},
  );
}

/** The rule run's counts over the items it has checked. */
export function ruleRunOf(
  items: readonly NewsDetailWire[],
  status: RunStatus,
  finishedAt: string | null,
): RuleRunWire {
  const checked = items.filter(item => item.rules_checked);
  return {
    status,
    finished_at: finishedAt,
    items: checked.length,
    duplicates: checked.filter(item => item.is_dup).length,
    flagged: checked.filter(item => item.reason_codes.length > 0).length,
  };
}
