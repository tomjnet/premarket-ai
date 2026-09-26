import type {
  AiDetailWire,
  AiEvidenceWire,
  AiRunWire,
  NewsDetailWire,
  Sentiment,
} from '@/api/schemas/news';
import {EXCERPT_MAX_CHARS} from '@/api/schemas/news';
import {addSeconds} from '@/lib/time';

import {FAKE_COMPANIES, REAL_COMPANIES} from './companies';

/**
 * The mock's stand-in for the backend's first AI run (increment 3): the
 * guard (injection attempts), the language check, dedup L3 (paraphrases
 * and conflicting versions), then extraction and a one-line summary with
 * a sentiment per unique item. The generator plants the cases L3 and the
 * language check find (see `PlantedCase`); the rest follows from the text.
 */

/** The first feed date the AI run enriched. */
export const AI_START_DATE = '2026-09-24';
export const AI_MODEL = 'main-gpu4gb';
export const ENRICH_PROMPT_VERSION = 'enrich-v1';
/** The AI run ends this long after the rule run. */
export const AI_RUN_SECONDS = 6 * 60;
/** Every unique item whose number is a multiple of this gets the lead
 * sentence (the model "couldn't summarize" it). */
export const FALLBACK_EVERY = 23;
/** The item number whose model calls "failed". */
export const AI_FAILED_NUMBER = 13;

/** A case the generator planted for the AI run to find. */
export type PlantedCase =
  | {kind: 'paraphrase'; original: NewsDetailWire; cosine: number}
  | {kind: 'conflict'; original: NewsDetailWire; detail: string}
  | {kind: 'foreign'};

const INJECTION =
  /ignore (?:all |any )?(?:previous|prior) instructions[^.\n]*\.?/i;
const DATELINE = /^NEW YORK, [A-Za-z]+ \d+ \([^)]*\) -- /;
const BULLISH =
  /\b(?:raises|record|repurchase|approval|wins|partnership|expands|up \d+%|supply contract|buyback)\b/i;
const BEARISH =
  /\b(?:halted|cuts|falls|down \d+%|recall|probe|lawsuit|delays|misses)\b/i;
const COMPANIES = [...REAL_COMPANIES, ...FAKE_COMPANIES];

/** The story's text: no dateline, no vendor-sim footer. */
function storyText(body: string): string {
  const end = body.lastIndexOf('\n\n');
  const story = end === -1 ? body : body.slice(0, end);
  return story.replace(DATELINE, '').trim();
}

/** The story's sentences, one line each. */
function sentences(text: string): string[] {
  return text
    .replace(/\s+/g, ' ')
    .split(/(?<=[.!?])\s+(?=[A-Z«"])/)
    .map(sentence => sentence.trim())
    .filter(sentence => sentence !== '');
}

/** One line, at most 280 characters, no HTML-looking tags. */
function oneLine(text: string): string {
  const chars = [
    ...text
      .replace(/<[^>]*>/g, '')
      .replace(/\s+/g, ' ')
      .trim(),
  ];
  if (chars.length <= EXCERPT_MAX_CHARS) {
    return chars.join('');
  }
  return `${chars
    .slice(0, EXCERPT_MAX_CHARS - 1)
    .join('')
    .trimEnd()}…`;
}

function headlineText(headline: string): string {
  return headline.replace(/^\[SYNTHETIC\] /, '');
}

/** The model's summary: the story in the vendor's words, attributed. */
function llmSummary(item: NewsDetailWire): string {
  return oneLine(
    `The vendor reports: ${headlineText(item.headline).replace(/\.$/, '')}.`,
  );
}

/** The fallback: the story's lead sentence. */
function leadSentence(item: NewsDetailWire): string {
  const clean = storyText(item.body).replace(INJECTION, '');
  return oneLine(sentences(clean)[0] ?? headlineText(item.headline));
}

function sentimentOf(item: NewsDetailWire): Sentiment {
  const text = headlineText(item.headline);
  if (BEARISH.test(text)) {
    return 'bearish';
  }
  return BULLISH.test(text) ? 'bullish' : 'neutral';
}

function companiesOf(item: NewsDetailWire): AiDetailWire['companies'] {
  return item.tickers.map(ticker => {
    const company = COMPANIES.find(candidate => candidate.ticker === ticker);
    return {name: company?.name ?? ticker, ticker};
  });
}

/** Up to three claims: the story's sentences, instructions removed. */
function claimsOf(item: NewsDetailWire): string[] {
  return sentences(storyText(item.body))
    .filter(sentence => !INJECTION.test(sentence))
    .map(oneLine)
    .slice(0, 3);
}

function itemNumber(item: NewsDetailWire): number {
  return item.id % 1000;
}

/** An item the AI run didn't enrich (unchecked, or a rule duplicate). */
function notEnriched(item: NewsDetailWire): NewsDetailWire {
  return {...item, summary: null, sentiment: null, ai: null};
}

/**
 * The items as served after the date's AI run, and the run's counts.
 *
 * @param items the day's items after the rule run (newest first).
 * @param planted the generator's planted cases, by item id.
 * @param ruleFinishedAt when the rule run ended.
 */
export function applyAiRun(
  items: readonly NewsDetailWire[],
  planted: ReadonlyMap<number, PlantedCase>,
  ruleFinishedAt: string,
): {items: NewsDetailWire[]; aiRun: AiRunWire} {
  const enrichedAt = addSeconds(ruleFinishedAt, AI_RUN_SECONDS);
  const base = {
    model: AI_MODEL,
    prompt_version: ENRICH_PROMPT_VERSION,
    enriched_at: enrichedAt,
  };
  const newCopies = new Map<string, number>();
  const enriched = items.map((item): NewsDetailWire => {
    if (!item.rules_checked || item.is_dup) {
      return notEnriched(item);
    }
    const evidence: AiEvidenceWire[] = [];
    const codes: string[] = [];
    const flag = (entry: AiEvidenceWire) => {
      evidence.push(entry);
      if (entry.code !== null && !codes.includes(entry.code)) {
        codes.push(entry.code);
      }
    };
    const injection = INJECTION.exec(storyText(item.body));
    if (injection !== null) {
      flag({
        check: 'guard',
        code: 'INJECTION_ATTEMPT',
        message: `Instruction-like text removed before any model saw the item: "${oneLine(injection[0]).slice(0, 120)}"`,
      });
    }
    const planned = planted.get(item.id);
    const reasonCodes = () => [
      ...item.reason_codes,
      ...codes.filter(code => !item.reason_codes.includes(code)),
    ];
    const skipped = (status: 'DUPLICATE' | 'SKIPPED' | 'FAILED') => ({
      ...item,
      reason_codes: reasonCodes(),
      summary: null,
      sentiment: null,
      ai: {
        ...base,
        status,
        summary_source: null,
        companies: [],
        claims: [],
        evidence,
      },
    });
    if (planned?.kind === 'paraphrase') {
      const original = planned.original;
      evidence.unshift({
        check: 'dedup',
        code: null,
        message: `Paraphrase (L3, cosine ${planned.cosine.toFixed(2)}, ${10 + (item.id % 7)} words differ, same tickers and key facts) of ${original.vendor_item_id} from ${original.feed_date}.`,
      });
      newCopies.set(
        original.vendor_item_id,
        (newCopies.get(original.vendor_item_id) ?? 0) + 1,
      );
      return {
        ...skipped('DUPLICATE'),
        is_dup: true,
        dup_of: original.vendor_item_id,
        dup_type: 'paraphrase',
      };
    }
    if (planned?.kind === 'conflict') {
      // Evidence only: the backend has no reason code for it.
      flag({
        check: 'dedup',
        code: null,
        message: `Very similar to ${planned.original.vendor_item_id} from ${planned.original.feed_date} (cosine 0.95), but ${planned.detail}: two versions of one story.`,
      });
    }
    if (planned?.kind === 'foreign') {
      flag({
        check: 'language',
        code: 'UNSUPPORTED_LANGUAGE',
        message: 'Not English: the model steps were skipped.',
      });
      return skipped('SKIPPED');
    }
    if (itemNumber(item) === AI_FAILED_NUMBER) {
      return skipped('FAILED');
    }
    const fallback = itemNumber(item) % FALLBACK_EVERY === 0;
    return {
      ...item,
      reason_codes: reasonCodes(),
      summary: fallback ? leadSentence(item) : llmSummary(item),
      sentiment: fallback ? 'neutral' : sentimentOf(item),
      ai: {
        ...base,
        status: 'DONE',
        summary_source: fallback ? 'fallback' : 'llm',
        companies: companiesOf(item),
        claims: claimsOf(item),
        evidence,
      },
    };
  });
  // The paraphrases are copies of their originals too.
  const withCopies = enriched.map(item => {
    const extra = newCopies.get(item.vendor_item_id) ?? 0;
    return extra === 0 ? item : {...item, copies: item.copies + extra};
  });
  const processed = withCopies.filter(item => item.ai !== null);
  return {
    items: withCopies,
    aiRun: {
      status: 'DONE',
      finished_at: enrichedAt,
      items: processed.length,
      paraphrases: processed.filter(item => item.ai?.status === 'DUPLICATE')
        .length,
      conflicts: processed.filter(
        item => planted.get(item.id)?.kind === 'conflict',
      ).length,
      summarized: processed.filter(item => item.summary !== null).length,
      fallbacks: processed.filter(
        item => item.ai?.summary_source === 'fallback',
      ).length,
      failed: processed.filter(item => item.ai?.status === 'FAILED').length,
      model: AI_MODEL,
    },
  };
}
