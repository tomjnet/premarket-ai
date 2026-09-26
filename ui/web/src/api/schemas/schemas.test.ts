import {describe, expect, it} from 'vitest';

import {authSessionSchema} from './auth';
import {errorBodySchema} from './errors';
import {newsDetailSchema, newsListSchema} from './news';

// The `GET /news` example the UI and backend teams agreed on.
const wireList = {
  date: '2026-09-24',
  run: {
    run_id: 42,
    status: 'DONE',
    started_at: '2026-09-24T09:30:02Z',
    finished_at: '2026-09-24T09:30:05Z',
    rows_received: 100,
    dups: 9,
  },
  rule_run: {
    status: 'DONE',
    finished_at: '2026-09-24T09:30:45Z',
    items: 100,
    duplicates: 14,
    flagged: 17,
  },
  count: 1,
  items: [
    {
      id: 1234,
      vendor_item_id: 'acme-20260924-0007',
      feed_date: '2026-09-24',
      headline: '[SYNTHETIC] Apple expands buyback by $10 billion',
      excerpt:
        'NEW YORK, September 24 (Acme Market Wire) -- Apple Inc said on...',
      source_url: 'https://acme-market-wire.example/2026/09/24/apple-buyback',
      source_domain: 'acme-market-wire.example',
      published_at: '2026-09-24T08:12:00Z',
      tickers: ['AAPL'],
      synthetic: true,
      is_dup: false,
      dup_of: null,
      reason_codes: ['FAKE_TICKER', 'SPOOFED_SOURCE'],
      dup_type: null,
      copies: 2,
      rules_checked: true,
    },
  ],
};

const wireItem = wireList.items[0];

function listWithItem(changes: Record<string, unknown>) {
  return {...wireList, items: [{...wireItem, ...changes}]};
}

describe('news schemas', () => {
  it('maps the wire list to the camelCase UI model', () => {
    expect(newsListSchema.parse(wireList)).toEqual({
      date: '2026-09-24',
      run: {
        runId: 42,
        status: 'DONE',
        startedAt: '2026-09-24T09:30:02Z',
        finishedAt: '2026-09-24T09:30:05Z',
        rowsReceived: 100,
        dups: 9,
      },
      ruleRun: {
        status: 'DONE',
        finishedAt: '2026-09-24T09:30:45Z',
        items: 100,
        duplicates: 14,
        flagged: 17,
      },
      count: 1,
      items: [
        {
          id: 1234,
          vendorItemId: 'acme-20260924-0007',
          feedDate: '2026-09-24',
          headline: '[SYNTHETIC] Apple expands buyback by $10 billion',
          excerpt:
            'NEW YORK, September 24 (Acme Market Wire) -- Apple Inc said on...',
          sourceUrl:
            'https://acme-market-wire.example/2026/09/24/apple-buyback',
          sourceDomain: 'acme-market-wire.example',
          publishedAt: '2026-09-24T08:12:00Z',
          tickers: ['AAPL'],
          synthetic: true,
          isDup: false,
          dupOf: null,
          reasonCodes: ['FAKE_TICKER', 'SPOOFED_SOURCE'],
          dupType: null,
          copies: 2,
          rulesChecked: true,
        },
      ],
    });
  });

  it('accepts reason codes of later increments, and no rule run yet', () => {
    const parsed = newsListSchema.parse({
      ...listWithItem({
        reason_codes: ['FABRICATED_CLAIM', 'INJECTION_ATTEMPT'],
        rules_checked: true,
      }),
      rule_run: null,
    });
    expect(parsed.ruleRun).toBeNull();
    expect(parsed.items[0]?.reasonCodes).toEqual([
      'FABRICATED_CLAIM',
      'INJECTION_ATTEMPT',
    ]);
  });

  it('rejects reason codes that are not upper-case codes', () => {
    for (const code of ['fake_ticker', 'X', '_STALE', 'FAKE TICKER', '']) {
      expect(
        newsListSchema.safeParse(listWithItem({reason_codes: [code]})).success,
      ).toBe(false);
    }
    expect(
      newsListSchema.safeParse(
        listWithItem({reason_codes: [`A${'B'.repeat(41)}`]}),
      ).success,
    ).toBe(false);
  });

  it('reads every duplicate type and rejects others', () => {
    for (const dupType of ['url', 'exact', 'near', 'paraphrase']) {
      const parsed = newsListSchema.parse(
        listWithItem({is_dup: true, dup_of: 'VND-1', dup_type: dupType}),
      );
      expect(parsed.items[0]?.dupType).toBe(dupType);
    }
    expect(
      newsListSchema.safeParse(listWithItem({dup_type: 'fuzzy'})).success,
    ).toBe(false);
  });

  it('requires the rule fields (always present on the wire)', () => {
    for (const field of [
      'reason_codes',
      'dup_type',
      'copies',
      'rules_checked',
    ]) {
      const item: Record<string, unknown> = {...wireItem};
      delete item[field];
      expect(
        newsListSchema.safeParse({...wireList, items: [item]}).success,
      ).toBe(false);
    }
    const withoutRuleRun: Record<string, unknown> = {...wireList};
    delete withoutRuleRun.rule_run;
    expect(newsListSchema.safeParse(withoutRuleRun).success).toBe(false);
    expect(newsListSchema.safeParse(listWithItem({copies: -1})).success).toBe(
      false,
    );
  });

  it('reads RUNNING and FAILED rule runs', () => {
    const running = newsListSchema.parse({
      ...wireList,
      rule_run: {...wireList.rule_run, status: 'RUNNING', finished_at: null},
    });
    expect(running.ruleRun).toEqual({
      status: 'RUNNING',
      finishedAt: null,
      items: 100,
      duplicates: 14,
      flagged: 17,
    });
    expect(
      newsListSchema.safeParse({
        ...wireList,
        rule_run: {...wireList.rule_run, status: 'PAUSED'},
      }).success,
    ).toBe(false);
  });

  it('accepts a day without a run and a RUNNING run without finished_at', () => {
    expect(
      newsListSchema.parse({
        date: '2026-09-26',
        run: null,
        rule_run: null,
        count: 0,
        items: [],
      }).run,
    ).toBeNull();
    const running = {
      ...wireList,
      run: {...wireList.run, status: 'RUNNING', finished_at: null},
    };
    expect(newsListSchema.parse(running).run?.finishedAt).toBeNull();
  });

  it('rejects drift: wrong types, unknown status, count mismatch', () => {
    expect(newsListSchema.safeParse({...wireList, count: '1'}).success).toBe(
      false,
    );
    expect(
      newsListSchema.safeParse({
        ...wireList,
        run: {...wireList.run, status: 'PAUSED'},
      }).success,
    ).toBe(false);
    expect(newsListSchema.safeParse({...wireList, count: 2}).success).toBe(
      false,
    );
    const offset = {
      ...wireList,
      items: [
        {...wireList.items[0], published_at: '2026-09-24T04:12:00-04:00'},
      ],
    };
    expect(newsListSchema.safeParse(offset).success).toBe(false);
  });

  it('counts the excerpt limit in characters, like the backend', () => {
    const item = wireList.items[0];
    // 279 letters + one emoji: 280 characters, 281 UTF-16 units.
    const atLimit = `${'a'.repeat(279)}📈`;
    expect(
      newsListSchema.safeParse({
        ...wireList,
        items: [{...item, excerpt: atLimit}],
      }).success,
    ).toBe(true);
    expect(
      newsListSchema.safeParse({
        ...wireList,
        items: [{...item, excerpt: `${atLimit}b`}],
      }).success,
    ).toBe(false);
  });

  it('rejects an impossible date', () => {
    expect(
      newsListSchema.safeParse({...wireList, date: '2026-13-45'}).success,
    ).toBe(false);
  });

  it('adds the body on the detail and keeps it plain text', () => {
    const detail = newsDetailSchema.parse({
      ...wireList.items[0],
      body: 'Line one.\n<b>Line two.</b>',
      rule_evidence: [],
    });
    expect(detail.body).toBe('Line one.\n<b>Line two.</b>');
    expect(detail.vendorItemId).toBe('acme-20260924-0007');
    expect(detail.ruleEvidence).toEqual([]);
  });

  it('reads the rule evidence of the detail', () => {
    const evidence = [
      {
        check: 'entity',
        code: 'FAKE_TICKER',
        message:
          'Ticker AAPLQZ is not in the SEC ticker registry (10,381 tickers, refreshed 2026-09-24).',
      },
      {
        check: 'dedup',
        code: null,
        message: 'Exact copy (L1) of VND-20260921-014 from 2026-09-21.',
      },
    ];
    const detail = newsDetailSchema.parse({
      ...wireItem,
      body: 'Body.',
      rule_evidence: evidence,
    });
    expect(detail.ruleEvidence).toEqual(evidence);
    expect(
      newsDetailSchema.safeParse({...wireItem, body: 'Body.'}).success,
    ).toBe(false);
    expect(
      newsDetailSchema.safeParse({
        ...wireItem,
        body: 'Body.',
        rule_evidence: [{check: 'llm', code: null, message: 'x'}],
      }).success,
    ).toBe(false);
  });
});

describe('auth schema', () => {
  it('maps the token response', () => {
    expect(
      authSessionSchema.parse({
        access_token: 'eyJ.abc',
        token_type: 'bearer',
        expires_in: 900,
        user: {username: 'trader1', role: 'TRADER'},
      }),
    ).toEqual({
      accessToken: 'eyJ.abc',
      expiresInS: 900,
      user: {username: 'trader1', role: 'TRADER'},
    });
  });

  it('rejects an unknown role', () => {
    expect(
      authSessionSchema.safeParse({
        access_token: 'x',
        token_type: 'bearer',
        expires_in: 900,
        user: {username: 'root', role: 'ROOT'},
      }).success,
    ).toBe(false);
  });
});

describe('error schema', () => {
  it('reads a string detail and a 422 list', () => {
    expect(errorBodySchema.parse({detail: 'Not found'}).detail).toBe(
      'Not found',
    );
    expect(
      errorBodySchema.parse({
        detail: [
          {loc: ['query', 'date'], msg: 'Field required', type: 'missing'},
        ],
      }).detail,
    ).toHaveLength(1);
  });
});
