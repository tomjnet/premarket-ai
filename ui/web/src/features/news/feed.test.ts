import {describe, expect, it} from 'vitest';

import type {NewsItem, NewsList} from '@/api/schemas/news';

import {
  duplicateCount,
  feedFallbackDate,
  feedSearch,
  feedSummary,
  newestFirst,
  normalizeTicker,
  parseFeedFilters,
  visibleItems,
} from './feed';

const TODAY = '2026-09-25';

function params(query: string): URLSearchParams {
  return new URLSearchParams(query);
}

describe('parseFeedFilters', () => {
  it('defaults to today, no ticker, no search, duplicates hidden', () => {
    expect(parseFeedFilters(params(''), TODAY)).toEqual({
      date: TODAY,
      ticker: undefined,
      q: undefined,
      dups: false,
      flagged: false,
    });
  });

  it('reads every filter from the URL', () => {
    expect(
      parseFeedFilters(
        params('date=2026-09-24&ticker=aapl&q=%20buyback%20&dups=1&flagged=1'),
        TODAY,
      ),
    ).toEqual({
      date: '2026-09-24',
      ticker: 'AAPL',
      q: 'buyback',
      dups: true,
      flagged: true,
    });
  });

  it('ignores invalid values instead of breaking', () => {
    expect(
      parseFeedFilters(
        params(
          'date=2026-02-30&ticker=%3Cscript%3E&q=%20%20&dups=yes&flagged=true',
        ),
        TODAY,
      ),
    ).toEqual({
      date: TODAY,
      ticker: undefined,
      q: undefined,
      dups: false,
      flagged: false,
    });
  });

  it('caps a very long search', () => {
    const q = 'x'.repeat(500);
    expect(parseFeedFilters(params(`q=${q}`), TODAY).q).toHaveLength(200);
  });

  it('round-trips through the URL', () => {
    const filters = {
      date: '2026-09-24',
      ticker: 'BRK.B',
      q: 'a & b',
      dups: true,
      flagged: true,
    };
    expect(
      parseFeedFilters(new URLSearchParams(feedSearch(filters)), TODAY),
    ).toEqual(filters);
    expect(feedSearch({date: TODAY, dups: false, flagged: false})).toBe(
      `?date=${TODAY}`,
    );
    expect(feedSearch({date: TODAY, dups: false, flagged: true})).toBe(
      `?date=${TODAY}&flagged=1`,
    );
  });
});

describe('normalizeTicker', () => {
  it('accepts tickers like AAPL, BRK.B and ZNTRA', () => {
    expect(normalizeTicker(' brk.b ')).toBe('BRK.B');
    expect(normalizeTicker('ZNTRA')).toBe('ZNTRA');
  });

  it('rejects anything else', () => {
    for (const value of ['', '1ABC', 'A B', 'TOOLONGTICKER', '$AAPL']) {
      expect(normalizeTicker(value)).toBeUndefined();
    }
  });
});

function item(
  id: number,
  publishedAt: string,
  reasonCodes: string[] = [],
): NewsItem {
  return {
    id,
    vendorItemId: `VND-${id}`,
    feedDate: '2026-09-24',
    headline: `[SYNTHETIC] ${id}`,
    excerpt: '',
    sourceUrl: 'https://wire.vendornews.example/x',
    sourceDomain: 'wire.vendornews.example',
    publishedAt,
    tickers: [],
    synthetic: true,
    isDup: false,
    dupOf: null,
    reasonCodes,
    dupType: null,
    copies: 0,
    rulesChecked: true,
  };
}

describe('newestFirst', () => {
  it('sorts by time, newest first, then by id', () => {
    const sorted = newestFirst([
      item(1, '2026-09-24T08:00:00Z'),
      item(3, '2026-09-24T09:00:00Z'),
      item(2, '2026-09-24T09:00:00Z'),
    ]);
    expect(sorted.map(entry => entry.id)).toEqual([3, 2, 1]);
  });
});

describe('visibleItems', () => {
  const items = [
    item(1, '2026-09-24T08:00:00Z', ['STALE']),
    item(2, '2026-09-24T09:00:00Z'),
  ];

  it('keeps every item, or only the flagged ones', () => {
    const filters = {date: '2026-09-24', dups: false, flagged: false};
    expect(visibleItems(items, filters)).toEqual(items);
    expect(
      visibleItems(items, {...filters, flagged: true}).map(entry => entry.id),
    ).toEqual([1]);
  });
});

describe('feedSummary', () => {
  const list: NewsList = {
    date: '2026-09-24',
    run: {
      runId: 1,
      status: 'DONE',
      startedAt: '2026-09-24T09:30:02Z',
      finishedAt: '2026-09-24T09:30:05Z',
      rowsReceived: 100,
      dups: 9,
    },
    ruleRun: null,
    count: 91,
    items: [],
  };
  const ruleRun = {
    status: 'DONE' as const,
    finishedAt: '2026-09-24T09:30:45Z',
    items: 100,
    duplicates: 14,
    flagged: 17,
  };
  const defaults = {date: '2026-09-24', dups: false, flagged: false};

  it('counts items, hidden duplicates and the update time (ET)', () => {
    expect(feedSummary(list, defaults)).toBe(
      '91 items · 9 duplicates hidden · updated 05:30 ET',
    );
  });

  it('says duplicates are shown when they are', () => {
    expect(feedSummary({...list, count: 100}, {...defaults, dups: true})).toBe(
      '100 items · 9 duplicates shown · updated 05:30 ET',
    );
  });

  it('talks about matches when filtered', () => {
    expect(
      feedSummary({...list, count: 1}, {...defaults, ticker: 'AAPL'}),
    ).toBe('1 matching item · updated 05:30 ET');
  });

  it("counts the rule engine's duplicates once it has checked the date", () => {
    expect(feedSummary({...list, count: 86, ruleRun}, defaults)).toBe(
      '86 items · 14 duplicates hidden · updated 05:30 ET',
    );
  });

  it('says how many items are flagged with "Flagged only"', () => {
    const flaggedList = {
      ...list,
      ruleRun,
      count: 2,
      items: [item(1, '2026-09-24T08:00:00Z', ['FAKE_TICKER'])],
    };
    expect(
      feedSummary({...flaggedList, count: 2}, {...defaults, flagged: true}),
    ).toBe('1 of 2 items flagged · 14 duplicates hidden · updated 05:30 ET');
  });
});

describe('duplicateCount', () => {
  const run = {
    runId: 1,
    status: 'DONE' as const,
    startedAt: '2026-09-24T09:30:02Z',
    finishedAt: '2026-09-24T09:30:05Z',
    rowsReceived: 100,
    dups: 9,
  };
  const ruleRun = {
    finishedAt: null,
    items: 60,
    duplicates: 11,
    flagged: 9,
  };
  const list = {date: '2026-09-24', count: 0, items: []};

  it('uses the legacy count until the rule run is DONE', () => {
    expect(duplicateCount({...list, run, ruleRun: null})).toBe(9);
    expect(
      duplicateCount({...list, run, ruleRun: {...ruleRun, status: 'RUNNING'}}),
    ).toBe(9);
    expect(
      duplicateCount({...list, run, ruleRun: {...ruleRun, status: 'DONE'}}),
    ).toBe(11);
    expect(duplicateCount({...list, run: null, ruleRun: null})).toBe(0);
  });
});

describe('feedFallbackDate', () => {
  it('goes to the trading date before a weekend or empty day', () => {
    expect(feedFallbackDate('2026-09-26', TODAY)).toBe('2026-09-25');
    expect(feedFallbackDate('2026-09-28', '2026-09-30')).toBe('2026-09-25');
  });

  it('goes to the latest trading date for a future date', () => {
    expect(feedFallbackDate('2026-10-05', TODAY)).toBe(TODAY);
    expect(feedFallbackDate('2026-10-05', '2026-09-27')).toBe('2026-09-25');
  });
});
