import {describe, expect, it} from 'vitest';

import {ingestRunWireSchema, newsDetailWireSchema} from '@/api/schemas/news';
import {addDays, isWeekend, previousTradingDate} from '@/lib/time';

import {
  DUPLICATES_PER_DAY,
  FOOTER,
  HEADLINE_PREFIX,
  ITEMS_PER_DAY,
  NEAR_COPIES_PER_DAY,
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
        "headline": "[SYNTHETIC] <script>alert("headline")</script> Umbrix Robotics reports <b>record</b> orders (update)",
        "id": 2458095,
        "publishedAt": "2026-09-24T09:33:00Z",
        "vendorItemId": "VND-20260924-095",
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

  it('gives a weekday 100 items, 9 legacy and 14 rule duplicates, newest first', () => {
    const day = generateDay(THURSDAY);
    expect(day.items).toHaveLength(ITEMS_PER_DAY);
    expect(day.items.filter(item => item.is_dup)).toHaveLength(
      DUPLICATES_PER_DAY + NEAR_COPIES_PER_DAY,
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
      flagged: day.items.filter(item => item.reason_codes.length > 0).length,
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

  it('explains each code in the evidence, sorted and plain text', () => {
    for (const item of day.items) {
      const codes = new Set(
        item.rule_evidence.flatMap(entry =>
          entry.code === null ? [] : [entry.code],
        ),
      );
      expect([...codes].sort()).toEqual(item.reason_codes);
      expect([...item.reason_codes].sort()).toEqual(item.reason_codes);
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
      new Set([null, 'exact', 'url', 'near']),
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
