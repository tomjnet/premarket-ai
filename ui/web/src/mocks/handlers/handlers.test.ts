import {beforeEach, describe, expect, it} from 'vitest';

import {tokenResponseWireSchema} from '@/api/schemas/auth';
import {errorBodySchema} from '@/api/schemas/errors';
import {healthSchema} from '@/api/schemas/health';
import {newsDetailWireSchema, newsListWireSchema} from '@/api/schemas/news';
import type {NewsListWire} from '@/api/schemas/news';

import {db} from '../data/db';
import {DUPLICATES_PER_DAY, ITEMS_PER_DAY} from '../data/generator';
import {setScenario} from '../scenarios';

import {FAILED_ITEMS, RUNNING_ITEMS_PER_STEP, RUNNING_STEP_MS} from './news';

// Contract tests: raw fetch, so the wire format itself is checked.
const THURSDAY = '2026-09-24';
const SATURDAY = '2026-09-26';

async function login(username = 'trader1', password = 'demo') {
  return fetch('/api/auth/login', {
    method: 'POST',
    body: new URLSearchParams({username, password}),
  });
}

async function token(): Promise<string> {
  const response = await login();
  return tokenResponseWireSchema.parse(await response.json()).access_token;
}

async function get(path: string, accessToken?: string) {
  const headers: Record<string, string> = {};
  if (accessToken !== undefined) {
    headers.Authorization = `Bearer ${accessToken}`;
  }
  const response = await fetch(`/api${path}`, {headers});
  const text = await response.text();
  let body: unknown = text;
  try {
    body = JSON.parse(text) as unknown;
  } catch {
    // Plain-text body (the 500 scenario).
  }
  return {status: response.status, headers: response.headers, body};
}

async function news(query: string, accessToken: string) {
  const {status, body} = await get(`/news?${query}`, accessToken);
  expect(status).toBe(200);
  return newsListWireSchema.parse(body);
}

beforeEach(() => {
  db.today = () => '2026-09-25';
});

describe('auth handlers', () => {
  it('logs in a seeded user', async () => {
    const response = await login();
    expect(response.status).toBe(200);
    const body = tokenResponseWireSchema.parse(await response.json());
    expect(body.user).toEqual({username: 'trader1', role: 'TRADER'});
    expect(body.expires_in).toBe(900);
  });

  it('answers 401 with FastAPI detail on a wrong password', async () => {
    const response = await login('trader1', 'wrong');
    expect(response.status).toBe(401);
    expect(response.headers.get('WWW-Authenticate')).toBe('Bearer');
    expect(errorBodySchema.parse(await response.json()).detail).toBe(
      'Incorrect username or password',
    );
  });

  it('answers 422 when a form field is missing', async () => {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      body: new URLSearchParams({username: 'trader1'}),
    });
    expect(response.status).toBe(422);
    expect(errorBodySchema.parse(await response.json()).detail).toEqual([
      {loc: ['body', 'password'], msg: 'Field required', type: 'missing'},
    ]);
  });

  it('refreshes only with a session, and logout ends it', async () => {
    const refresh = () => fetch('/api/auth/refresh', {method: 'POST'});
    expect((await refresh()).status).toBe(401);
    await login('admin1');
    const refreshed = await refresh();
    expect(
      tokenResponseWireSchema.parse(await refreshed.json()).user.role,
    ).toBe('ADMIN');
    expect((await fetch('/api/auth/logout', {method: 'POST'})).status).toBe(
      204,
    );
    expect((await refresh()).status).toBe(401);
  });
});

describe('news handlers', () => {
  it('needs a valid bearer token', async () => {
    const response = await get(`/news?date=${THURSDAY}`);
    expect(response.status).toBe(401);
    expect(response.body).toEqual({detail: 'Not authenticated'});
    expect((await get(`/news?date=${THURSDAY}`, 'forged')).status).toBe(401);
  });

  it('rejects an expired token', async () => {
    const accessToken = await token();
    db.now = () => Date.now() + 901 * 1000;
    expect((await get(`/news?date=${THURSDAY}`, accessToken)).status).toBe(401);
  });

  it('hides duplicates by default and includes them on request', async () => {
    const accessToken = await token();
    const list = await news(`date=${THURSDAY}`, accessToken);
    expect(list.count).toBe(ITEMS_PER_DAY - DUPLICATES_PER_DAY);
    expect(list.items.every(item => !item.is_dup)).toBe(true);
    expect(list.run?.dups).toBe(DUPLICATES_PER_DAY);
    const all = await news(
      `date=${THURSDAY}&include_duplicates=true`,
      accessToken,
    );
    expect(all.count).toBe(ITEMS_PER_DAY);
  });

  it('filters by ticker and by text, case-insensitively', async () => {
    const accessToken = await token();
    const aapl = await news(`date=${THURSDAY}&ticker=aapl`, accessToken);
    expect(aapl.items.every(item => item.tickers.includes('AAPL'))).toBe(true);
    const text = await news(`date=${THURSDAY}&q=ZENTRALITY`, accessToken);
    expect(text.count).toBeGreaterThan(0);
    const none = await news(`date=${THURSDAY}&q=no-such-words`, accessToken);
    expect(none).toMatchObject({count: 0, items: []});
  });

  it('has no run on weekends or future dates', async () => {
    const accessToken = await token();
    expect(await news(`date=${SATURDAY}`, accessToken)).toEqual({
      date: SATURDAY,
      run: null,
      count: 0,
      items: [],
    });
    expect((await news('date=2026-09-28', accessToken)).run).toBeNull();
  });

  it('answers 422 for a missing or invalid parameter', async () => {
    const accessToken = await token();
    for (const query of [
      '',
      'date=24-09-2026',
      `date=${THURSDAY}&include_duplicates=maybe`,
    ]) {
      const {status, body} = await get(`/news?${query}`, accessToken);
      expect(status).toBe(422);
      expect(errorBodySchema.safeParse(body).success).toBe(true);
    }
  });

  it('serves the detail with its body, 404 and 422', async () => {
    const accessToken = await token();
    const [first] = (await news(`date=${THURSDAY}`, accessToken)).items;
    const detail = await get(`/news/${first?.id}`, accessToken);
    expect(detail.status).toBe(200);
    const parsed = newsDetailWireSchema.parse(detail.body);
    expect(parsed.id).toBe(first?.id);
    expect(parsed.body.length).toBeGreaterThan(0);

    const missing = await get('/news/999', accessToken);
    expect(missing).toMatchObject({status: 404, body: {detail: 'Not found'}});
    const invalid = await get('/news/abc', accessToken);
    expect(invalid.status).toBe(422);
    expect(errorBodySchema.safeParse(invalid.body).success).toBe(true);
  });
});

describe('health handler', () => {
  it('is public and ok', async () => {
    const {status, body} = await get('/health');
    expect(status).toBe(200);
    expect(healthSchema.parse(body)).toEqual({status: 'ok'});
  });
});

describe('scenarios', () => {
  const all = `date=${THURSDAY}&include_duplicates=true`;

  it('empty: no run, no items', async () => {
    const accessToken = await token();
    setScenario('empty');
    expect(await news(all, accessToken)).toMatchObject({run: null, count: 0});
  });

  it('running: items arrive every 30 s, then DONE', async () => {
    const accessToken = await token();
    setScenario('running');
    let clock = Date.now();
    db.now = () => clock;
    const counts: number[] = [];
    let list: NewsListWire | undefined;
    do {
      list = await news(all, accessToken);
      // Another call in the same 30 s (a filter change) changes nothing.
      expect((await news(all, accessToken)).count).toBe(list.count);
      counts.push(list.count);
      if (list.count < ITEMS_PER_DAY) {
        expect(list.run).toMatchObject({status: 'RUNNING', finished_at: null});
      }
      clock += RUNNING_STEP_MS;
    } while (list.run?.status === 'RUNNING');
    expect(counts).toEqual([
      RUNNING_ITEMS_PER_STEP,
      2 * RUNNING_ITEMS_PER_STEP,
      3 * RUNNING_ITEMS_PER_STEP,
      ITEMS_PER_DAY,
    ]);
    expect(list.run?.status).toBe('DONE');
  });

  it('running and failed: items that have not arrived answer 404', async () => {
    const accessToken = await token();
    // The newest item arrives last.
    const newest = db.day(THURSDAY).items[0]?.id;
    setScenario('failed');
    expect((await get(`/news/${newest}`, accessToken)).status).toBe(404);
    setScenario('running');
    expect((await get(`/news/${newest}`, accessToken)).status).toBe(404);
  });

  it('failed: FAILED with the items that arrived', async () => {
    const accessToken = await token();
    setScenario('failed');
    const list = await news(all, accessToken);
    expect(list.run).toMatchObject({
      status: 'FAILED',
      rows_received: FAILED_ITEMS,
    });
    expect(list.count).toBe(FAILED_ITEMS);
  });

  it('slow: every call takes 2–3 s', async () => {
    setScenario('slow');
    const started = Date.now();
    expect((await get('/health')).status).toBe(200);
    expect(Date.now() - started).toBeGreaterThanOrEqual(1900);
  });

  it('server-error: /news answers 500 with a plain-text body', async () => {
    const accessToken = await token();
    setScenario('server-error');
    const list = await get(`/news?date=${THURSDAY}`, accessToken);
    expect(list).toMatchObject({status: 500, body: 'Internal Server Error'});
    expect((await get('/news/1', accessToken)).status).toBe(500);
    expect((await get('/health')).status).toBe(200);
  });

  it('expired-session: one 401, then refresh works', async () => {
    const accessToken = await token();
    setScenario('expired-session');
    expect((await get(`/news?date=${THURSDAY}`, accessToken)).status).toBe(401);
    const refreshed = await fetch('/api/auth/refresh', {method: 'POST'});
    const fresh = tokenResponseWireSchema.parse(await refreshed.json());
    expect(
      (await get(`/news?date=${THURSDAY}`, fresh.access_token)).status,
    ).toBe(200);
  });

  it('logged-out: refresh answers 401, login still works', async () => {
    await login();
    setScenario('logged-out');
    const refreshed = await fetch('/api/auth/refresh', {method: 'POST'});
    expect(refreshed.status).toBe(401);
    expect((await login()).status).toBe(200);
  });

  it('contract-drift: the list fails its schema at "count"', async () => {
    const accessToken = await token();
    setScenario('contract-drift');
    const {status, body} = await get(`/news?date=${THURSDAY}`, accessToken);
    expect(status).toBe(200);
    const result = newsListWireSchema.safeParse(body);
    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.path).toEqual(['count']);
  });
});
