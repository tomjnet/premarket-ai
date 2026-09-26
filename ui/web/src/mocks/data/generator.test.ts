import {describe, expect, it} from 'vitest';

import {ingestRunWireSchema, newsDetailWireSchema} from '@/api/schemas/news';
import {addDays, isWeekend, previousTradingDate} from '@/lib/time';

import {AI_MODEL, AI_START_DATE} from './ai';
import {
  DUPLICATES_PER_DAY,
  FOOTER,
  HEADLINE_PREFIX,
  ITEMS_PER_DAY,
  NEAR_COPIES_PER_DAY,
  PARAPHRASES_PER_DAY,
  RULES_START_DATE,
  generateDay,
  parseItemId,
} from './generator';

const THURSDAY = '2026-09-24';
const SATURDAY = '2026-09-26';
const MONDAY = '2026-09-28';

describe('generateDay', () => {
  it('is deterministic: same date, same feed', () => {
    expect(generateDay(THURSDAY)).toEqual(generateDay(THURSDAY));
    expect(generateDay(THURSDAY).items[0]).not.toEqual(
      generateDay(addDays(THURSDAY, -1)).items[0],
    );
  });

  it('gives the same newest item as always (golden value)', () => {
    // Catches a changed seed, algorithm or hidden time/locale dependence.
    const [newest] = generateDay(THURSDAY).items;
    expect({
      id: newest?.id,
      vendorItemId: newest?.vendor_item_id,
      headline: newest?.headline,
      publishedAt: newest?.published_at,
    }).toMatchInlineSnapshot(`
      {
        "headline": "[SYNTHETIC] Meta reaffirms full-year outlook of about 6% revenue growth (update)",
        "id": 2458096,
        "publishedAt": "2026-09-24T09:14:00Z",
        "vendorItemId": "VND-20260924-096",
      }
    `);
  });

  it('changes with the seed', () => {
    expect(generateDay(THURSDAY, 1).items).not.toEqual(
      generateDay(THURSDAY, 2).items,
    );
  });

  it('has no run and no items on a weekend', () => {
    expect(generateDay(SATURDAY)).toMatchObject({
      date: SATURDAY,
      run: null,
      ruleRun: null,
      items: [],
    });
  });

  it('gives a weekday 100 items, 9 legacy, 14 rule and 2 AI duplicates, newest first', () => {
    const day = generateDay(THURSDAY);
    expect(day.items).toHaveLength(ITEMS_PER_DAY);
    expect(day.items.filter(item => item.is_dup)).toHaveLength(
      DUPLICATES_PER_DAY + NEAR_COPIES_PER_DAY + PARAPHRASES_PER_DAY,
    );
    expect([...day.legacy.values()].filter(flags => flags.is_dup)).toHaveLength(
      DUPLICATES_PER_DAY,
    );
    const times = day.items.map(item => item.published_at);
    expect([...times].sort().reverse()).toEqual(times);
    expect(day.run).toMatchObject({
      status: 'DONE',
      rows_received: ITEMS_PER_DAY,
      dups: DUPLICATES_PER_DAY,
    });
    expect(ingestRunWireSchema.safeParse(day.run).success).toBe(true);
  });

  it('points each duplicate at a first copy from this or the previous trading day', () => {
    const day = generateDay(MONDAY);
    const today = new Set(
      day.items.filter(item => !item.is_dup).map(item => item.vendor_item_id),
    );
    const previous = new Set(
      generateDay(previousTradingDate(MONDAY)).items.map(
        item => item.vendor_item_id,
      ),
    );
    const duplicates = day.items.filter(item => item.is_dup);
    for (const item of duplicates) {
      const dupOf = item.dup_of ?? '';
      expect(today.has(dupOf) || previous.has(dupOf)).toBe(true);
    }
    // Stale copies come from Friday.
    expect(duplicates.some(item => previous.has(item.dup_of ?? ''))).toBe(true);
  });

  it('marks everything as synthetic and uses reserved domains only', () => {
    for (const item of generateDay(THURSDAY).items) {
      expect(item.headline.startsWith(HEADLINE_PREFIX)).toBe(true);
      expect(item.synthetic).toBe(true);
      expect(item.body.startsWith('NEW YORK, September')).toBe(true);
      expect(item.body.endsWith(FOOTER)).toBe(true);
      expect(item.source_domain).toMatch(/\.(example|test)$/);
    }
  });

  it('includes the awkward items the UI must render safely', () => {
    const items = generateDay(THURSDAY).items;
    const has = (test: (text: string) => boolean) =>
      items.some(item => test(item.headline + item.body));
    expect(has(text => text.includes('<script>'))).toBe(true);
    expect(has(text => text.includes('Ignore previous instructions'))).toBe(
      true,
    );
    expect(has(text => text.includes('東京'))).toBe(true);
    expect(items.some(item => item.headline.length > 200)).toBe(true);
    expect(items.some(item => item.source_url.startsWith('javascript:'))).toBe(
      true,
    );
    expect(items.some(item => item.tickers.length === 0)).toBe(true);
    expect(
      items.some(
        item =>
          item.source_url.startsWith('https://') &&
          new URL(item.source_url).hostname !== item.source_domain,
      ),
    ).toBe(true);
  });

  it('matches the contract for a month of dates', () => {
    for (let offset = 0; offset < 31; offset++) {
      const date = addDays('2026-08-01', offset);
      for (const item of generateDay(date).items) {
        const result = newsDetailWireSchema.safeParse(item);
        expect(result.error?.issues ?? []).toEqual([]);
      }
      expect(generateDay(date).run === null).toBe(isWeekend(date));
    }
  });
});

describe('generateDay: rule results', () => {
  const day = generateDay(THURSDAY);
  const withCode = (code: string) =>
    day.items.filter(item => item.reason_codes.includes(code));

  it('checks every item and counts the run', () => {
    expect(day.items.every(item => item.rules_checked)).toBe(true);
    expect(day.ruleRun).toEqual({
      status: 'DONE',
      finished_at: '2026-09-24T09:30:45Z',
      items: ITEMS_PER_DAY,
      duplicates: DUPLICATES_PER_DAY + NEAR_COPIES_PER_DAY,
      // The rule run counts its own codes, not the AI run's.
      flagged: day.items.filter(item =>
        item.rule_evidence.some(entry => entry.code !== null),
      ).length,
    });
  });

  it('flags fake companies and tickers, spoofed sources and stale copies', () => {
    expect(withCode('FAKE_COMPANY').length).toBeGreaterThan(3);
    expect(withCode('FAKE_TICKER').length).toBeGreaterThan(3);
    for (const item of withCode('SPOOFED_SOURCE')) {
      expect(item.source_domain).toMatch(/\.test$/);
    }
    expect(withCode('SPOOFED_SOURCE').length).toBeGreaterThan(0);
    const stale = withCode('STALE');
    expect(stale).toHaveLength(3);
    for (const item of stale) {
      expect(item).toMatchObject({is_dup: true, dup_type: 'exact'});
      expect(item.dup_of?.startsWith('VND-20260923-')).toBe(true);
    }
    // Real companies from trusted outlets are not flagged.
    const clean = day.items.filter(
      item => item.reason_codes.length === 0 && !item.is_dup,
    );
    expect(clean.length).toBeGreaterThan(40);
  });

  it('explains each code in the evidence: rule codes sorted, then AI codes', () => {
    const codesOf = (evidence: ReadonlyArray<{code: string | null}>) => [
      ...new Set(
        evidence.flatMap(entry => (entry.code === null ? [] : [entry.code])),
      ),
    ];
    for (const item of day.items) {
      const ruleCodes = codesOf(item.rule_evidence).sort();
      const aiCodes = codesOf(item.ai?.evidence ?? []).filter(
        code => !ruleCodes.includes(code),
      );
      expect(item.reason_codes).toEqual([...ruleCodes, ...aiCodes]);
    }
    const [fake] = withCode('FAKE_TICKER');
    expect(
      fake?.rule_evidence.some(entry =>
        /^Ticker [A-Z]+ is not in the SEC ticker registry \(10,381 tickers, refreshed 2026-09-23\)\.$/.test(
          entry.message,
        ),
      ),
    ).toBe(true);
  });

  it('finds the near copies the legacy exact hash misses', () => {
    const near = day.items.filter(item => item.dup_type === 'near');
    expect(near).toHaveLength(NEAR_COPIES_PER_DAY);
    for (const item of near) {
      expect(item.is_dup).toBe(true);
      expect(day.legacy.get(item.id)).toEqual({is_dup: false, dup_of: null});
    }
    expect(new Set(day.items.map(item => item.dup_type))).toEqual(
      new Set([null, 'exact', 'url', 'near', 'paraphrase']),
    );
  });

  it('counts on each original the copies the rules linked to it', () => {
    for (const item of day.items) {
      const copies = day.items.filter(
        other => other.dup_of === item.vendor_item_id,
      ).length;
      expect(item.copies).toBe(copies);
    }
    expect(day.items.some(item => item.copies > 0)).toBe(true);
  });

  it(`has no rule run before ${RULES_START_DATE}: legacy flags only`, () => {
    const early = generateDay('2026-09-18');
    expect(early.ruleRun).toBeNull();
    expect(early.items.every(item => !item.rules_checked)).toBe(true);
    expect(early.items.every(item => item.reason_codes.length === 0)).toBe(
      true,
    );
    expect(early.items.filter(item => item.is_dup)).toHaveLength(
      DUPLICATES_PER_DAY,
    );
    expect(early.items.every(item => item.copies === 0)).toBe(true);
  });
});

describe('generateDay: AI run', () => {
  const day = generateDay(THURSDAY);
  const unique = day.items.filter(item => item.ai !== null);
  const withStatus = (status: string) =>
    unique.filter(item => item.ai?.status === status);
  const withCode = (code: string) =>
    day.items.filter(item => item.reason_codes.includes(code));

  it('enriches only the unique checked items, and counts the run', () => {
    for (const item of day.items) {
      const ruleDuplicate = item.is_dup && item.dup_type !== 'paraphrase';
      expect(item.ai === null).toBe(ruleDuplicate);
    }
    expect(day.aiRun).toEqual({
      status: 'DONE',
      finished_at: '2026-09-24T09:36:45Z',
      items: ITEMS_PER_DAY - DUPLICATES_PER_DAY - NEAR_COPIES_PER_DAY,
      paraphrases: PARAPHRASES_PER_DAY,
      conflicts: 1,
      summarized: unique.filter(item => item.summary !== null).length,
      fallbacks: unique.filter(item => item.ai?.summary_source === 'fallback')
        .length,
      failed: 1,
      model: AI_MODEL,
    });
    expect(day.aiRun?.fallbacks).toBeGreaterThan(0);
  });

  it('links the paraphrases to their originals (L3)', () => {
    const paraphrases = withStatus('DUPLICATE');
    expect(paraphrases).toHaveLength(PARAPHRASES_PER_DAY);
    for (const item of paraphrases) {
      expect(item).toMatchObject({
        is_dup: true,
        dup_type: 'paraphrase',
        summary: null,
        sentiment: null,
      });
      expect(item.ai?.evidence[0]?.message).toMatch(/^Paraphrase \(L3/);
      const original = day.items.find(
        other => other.vendor_item_id === item.dup_of,
      );
      expect(original?.is_dup).toBe(false);
      expect(original?.copies).toBeGreaterThan(0);
    }
  });

  it('flags injection attempts and other languages; explains a conflicting version', () => {
    const [injection] = withCode('INJECTION_ATTEMPT');
    expect(injection?.body).toContain('Ignore previous instructions');
    expect(injection?.ai?.evidence[0]?.check).toBe('guard');
    expect(injection?.ai?.claims.join(' ')).not.toContain('Ignore');
    const [foreign] = withCode('UNSUPPORTED_LANGUAGE');
    expect(foreign).toMatchObject({summary: null, sentiment: null});
    expect(foreign?.ai?.status).toBe('SKIPPED');
    // A conflicting version is evidence only: no reason code (backend).
    expect(withCode('CONFLICTING_VERSION')).toEqual([]);
    const conflicts = unique.filter(item =>
      item.ai?.evidence.some(entry => /key facts differ/.test(entry.message)),
    );
    expect(conflicts).toHaveLength(1);
    const [conflict] = conflicts;
    expect(conflict?.is_dup).toBe(false);
    expect(conflict?.summary).not.toBeNull();
    expect(conflict?.ai?.evidence.at(-1)).toMatchObject({
      check: 'dedup',
      code: null,
    });
  });

  it('writes one-line summaries with a sentiment, and lead sentences as fallbacks', () => {
    for (const item of withStatus('DONE')) {
      expect(item.summary).not.toBeNull();
      expect(item.sentiment).not.toBeNull();
      expect([...(item.summary ?? '')].length).toBeLessThanOrEqual(280);
      expect(item.summary).not.toMatch(/[\n<]/);
    }
    const fallbacks = unique.filter(
      item => item.ai?.summary_source === 'fallback',
    );
    for (const item of fallbacks) {
      expect(item.sentiment).toBe('neutral');
      expect(item.body).toContain(item.summary?.slice(0, 20));
    }
    expect(new Set(unique.map(item => item.sentiment))).toContain('bullish');
  });

  it(`has no AI run before ${AI_START_DATE}`, () => {
    const early = generateDay(addDays(AI_START_DATE, -1));
    expect(early.ruleRun).not.toBeNull();
    expect(early.aiRun).toBeNull();
    expect(early.items.every(item => item.ai === null)).toBe(true);
    expect(early.items.every(item => item.summary === null)).toBe(true);
  });
});

describe('parseItemId', () => {
  it('finds the date and number an id came from', () => {
    for (const item of generateDay(THURSDAY).items) {
      expect(parseItemId(item.id)?.date).toBe(THURSDAY);
    }
  });

  it('rejects ids that no generated item can have', () => {
    expect(parseItemId(1_000)).toBeUndefined();
    expect(parseItemId(1_101)).toBeUndefined();
    expect(parseItemId(-5)).toBeUndefined();
    expect(parseItemId(1.5)).toBeUndefined();
  });
});
