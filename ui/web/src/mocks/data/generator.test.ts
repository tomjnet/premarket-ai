import {describe, expect, it} from 'vitest';

import {ingestRunWireSchema, newsDetailWireSchema} from '@/api/schemas/news';
import {addDays, isWeekend, previousTradingDate} from '@/lib/time';

import {
  DUPLICATES_PER_DAY,
  FOOTER,
  HEADLINE_PREFIX,
  ITEMS_PER_DAY,
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
        "headline": "[SYNTHETIC] Umbrix to be acquired by Quantavex for $40B in all-cash deal",
        "id": 2458087,
        "publishedAt": "2026-09-24T08:58:00Z",
        "vendorItemId": "VND-20260924-087",
      }
    `);
  });

  it('changes with the seed', () => {
    expect(generateDay(THURSDAY, 1).items).not.toEqual(
      generateDay(THURSDAY, 2).items,
    );
  });

  it('has no run and no items on a weekend', () => {
    expect(generateDay(SATURDAY)).toEqual({
      date: SATURDAY,
      run: null,
      items: [],
    });
  });

  it('gives a weekday 100 items, 9 of them duplicates, newest first', () => {
    const day = generateDay(THURSDAY);
    expect(day.items).toHaveLength(ITEMS_PER_DAY);
    expect(day.items.filter(item => item.is_dup)).toHaveLength(
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
