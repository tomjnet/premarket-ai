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
    },
  ],
};

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
        },
      ],
    });
  });

  it('accepts a day without a run and a RUNNING run without finished_at', () => {
    expect(
      newsListSchema.parse({date: '2026-09-26', run: null, count: 0, items: []})
        .run,
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
    });
    expect(detail.body).toBe('Line one.\n<b>Line two.</b>');
    expect(detail.vendorItemId).toBe('acme-20260924-0007');
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
