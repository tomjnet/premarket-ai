import {HttpResponse, delay, http} from 'msw';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import {apiUrl} from '@/lib/env';
import {db} from '@/mocks/data/db';
import {server} from '@/mocks/node';
import {setScenario} from '@/mocks/scenarios';

import {login, logout, restoreSession} from './auth';
import {ApiClient} from './client';
import type {SessionChange} from './client';
import {
  ContractError,
  HttpError,
  NetworkError,
  SessionExpiredError,
} from './errors';
import {getHealth} from './health';
import {getNews, getNewsItem} from './news';

const THURSDAY = '2026-09-24';

/** Every request the mock backend saw, as `METHOD /path?query`. */
let requests: Array<{line: string; authorization: string | null}> = [];

function countRequests(path: string): number {
  return requests.filter(request => request.line.includes(` /api${path}`))
    .length;
}

function newClient(timeoutMs?: number): ApiClient {
  return new ApiClient({baseUrl: '/api', timeoutMs});
}

/** Moves the mock's clock past the lifetime of every token issued so far. */
function expireTokens(): void {
  const skew = (db.tokenTtlS + 1) * 1000;
  db.now = () => Date.now() + skew;
}

beforeEach(() => {
  db.today = () => '2026-09-25';
  requests = [];
  server.events.on('request:start', ({request}) => {
    const url = new URL(request.url);
    requests.push({
      line: `${request.method} ${url.pathname}${url.search}`,
      authorization: request.headers.get('Authorization'),
    });
  });
});

afterEach(() => {
  server.events.removeAllListeners();
});

describe('login and session', () => {
  it('stores the session in memory and tells listeners', async () => {
    const client = newClient();
    const changes: SessionChange[] = [];
    client.subscribe((_session, change) => changes.push(change));

    const session = await login('trader1', 'demo', {client});

    expect(session.user).toEqual({username: 'trader1', role: 'TRADER'});
    expect(session.expiresAt).toBeGreaterThan(Date.now());
    expect(client.getSession()).toBe(session);
    expect(changes).toEqual(['login']);
  });

  it('rejects a wrong password with HttpError 401 and no session', async () => {
    const client = newClient();
    const error = await login('trader1', 'nope', {client}).catch(
      (e: unknown) => e,
    );
    expect(error).toBeInstanceOf(HttpError);
    expect(error).toMatchObject({
      status: 401,
      detail: 'Incorrect username or password',
    });
    expect(client.getSession()).toBeUndefined();
    expect(countRequests('/auth/refresh')).toBe(0);
  });

  it('restores the session from the refresh cookie after a reload', async () => {
    expect(await restoreSession({client: newClient()})).toBeUndefined();
    await login('analyst1', 'demo', {client: newClient()});

    const reloaded = newClient();
    const session = await restoreSession({client: reloaded});
    expect(session?.user.role).toBe('ANALYST');
    expect(reloaded.getSession()).toBe(session);
  });

  it('logs out on the server and locally', async () => {
    const client = newClient();
    await login('trader1', 'demo', {client});
    await logout({client});
    expect(client.getSession()).toBeUndefined();
    expect(await restoreSession({client: newClient()})).toBeUndefined();
  });

  it('clears the local session even when logout fails', async () => {
    const client = newClient();
    await login('trader1', 'demo', {client});
    server.use(http.post(apiUrl('/auth/logout'), () => HttpResponse.error()));
    await expect(logout({client})).rejects.toBeInstanceOf(NetworkError);
    expect(client.getSession()).toBeUndefined();
  });
});

describe('requests', () => {
  it('sends the bearer token and the query, skipping unset filters', async () => {
    const client = newClient();
    const session = await login('trader1', 'demo', {client});

    await getNews({date: THURSDAY, ticker: 'AAPL'}, {client});
    await getNews(
      {date: THURSDAY, q: 'dividend', includeDuplicates: true},
      {client},
    );

    const newsRequests = requests.filter(request =>
      request.line.startsWith('GET /api/news'),
    );
    expect(newsRequests.map(request => request.line)).toEqual([
      `GET /api/news?date=${THURSDAY}&ticker=AAPL`,
      `GET /api/news?date=${THURSDAY}&q=dividend&include_duplicates=true`,
    ]);
    expect(newsRequests[0]?.authorization).toBe(
      `Bearer ${session.accessToken}`,
    );
  });

  it('returns the camelCase model', async () => {
    const client = newClient();
    await login('trader1', 'demo', {client});
    const list = await getNews({date: THURSDAY}, {client});
    const [first] = list.items;
    expect(list.run?.status).toBe('DONE');
    expect(first).toHaveProperty('vendorItemId');
    expect(first).not.toHaveProperty('vendor_item_id');
    const detail = await getNewsItem(first?.id ?? 0, {client});
    expect(detail.body.endsWith('Not real news.')).toBe(true);
  });

  it('keeps /health public: no token', async () => {
    const client = newClient();
    await login('trader1', 'demo', {client});
    expect(await getHealth({client})).toEqual({status: 'ok'});
    const health = requests.find(request => request.line === 'GET /api/health');
    expect(health?.authorization).toBeNull();
  });
});

describe('refresh on 401', () => {
  it('refreshes silently and retries (expired-session scenario)', async () => {
    const client = newClient();
    const first = await login('trader1', 'demo', {client});
    setScenario('expired-session');

    const list = await getNews({date: THURSDAY}, {client});

    expect(list.count).toBeGreaterThan(0);
    expect(countRequests('/auth/refresh')).toBe(1);
    const tokens = requests
      .filter(request => request.line.startsWith('GET /api/news'))
      .map(request => request.authorization);
    expect(tokens).toEqual([
      `Bearer ${first.accessToken}`,
      `Bearer ${client.getSession()?.accessToken}`,
    ]);
    expect(tokens[0]).not.toBe(tokens[1]);
  });

  it('reuses a token another call refreshed in the meantime', async () => {
    const client = newClient();
    const first = await login('trader1', 'demo', {client});
    expireTokens();
    // Holds call A (sent with the first token) until call B has refreshed.
    let releaseA = () => {};
    const gate = new Promise<void>(resolve => {
      releaseA = resolve;
    });
    server.use(
      http.get(apiUrl('/news'), async ({request}) => {
        const url = new URL(request.url);
        const bearer = request.headers.get('Authorization');
        if (
          url.searchParams.get('date') === '2026-09-23' &&
          bearer === `Bearer ${first.accessToken}`
        ) {
          await gate;
        }
        // Falls through to the real handler.
        return undefined;
      }),
    );

    const callA = getNews({date: '2026-09-23'}, {client});
    await getNews({date: THURSDAY}, {client});
    releaseA();
    await callA;

    expect(countRequests('/auth/refresh')).toBe(1);
  });

  it('shares one refresh between concurrent 401s', async () => {
    const client = newClient();
    await login('trader1', 'demo', {client});
    const itemId = db.day(THURSDAY).items[0]?.id ?? 0;
    expireTokens();

    const results = await Promise.all([
      getNews({date: THURSDAY}, {client}),
      getNews({date: '2026-09-23'}, {client}),
      getNewsItem(itemId, {client}),
    ]);

    expect(results).toHaveLength(3);
    expect(countRequests('/auth/refresh')).toBe(1);
  });

  it('retries only once, then gives up with SessionExpiredError', async () => {
    const client = newClient();
    await login('trader1', 'demo', {client});
    server.use(
      http.get(apiUrl('/news'), () =>
        HttpResponse.json({detail: 'Not authenticated'}, {status: 401}),
      ),
    );

    await expect(getNews({date: THURSDAY}, {client})).rejects.toBeInstanceOf(
      SessionExpiredError,
    );
    expect(countRequests('/news')).toBe(2);
    expect(countRequests('/auth/refresh')).toBe(1);
    expect(client.getSession()).toBeUndefined();
  });

  it('ends the session when refresh fails (logged-out scenario)', async () => {
    const client = newClient();
    await login('trader1', 'demo', {client});
    const changes: SessionChange[] = [];
    client.subscribe((_session, change) => changes.push(change));
    setScenario('logged-out');
    expireTokens();

    await expect(
      Promise.all([
        getNews({date: THURSDAY}, {client}),
        getNews({date: '2026-09-23'}, {client}),
      ]),
    ).rejects.toBeInstanceOf(SessionExpiredError);
    expect(client.getSession()).toBeUndefined();
    // Two failed calls, one notification.
    expect(changes).toEqual(['expired']);
  });

  it('ends the session when a direct refresh() gets 401', async () => {
    const client = newClient();
    await login('trader1', 'demo', {client});
    setScenario('logged-out');

    await expect(client.refresh()).rejects.toMatchObject({status: 401});
    expect(client.getSession()).toBeUndefined();
  });

  it('never reports "expired" for someone who was not logged in', async () => {
    const client = newClient();
    const changes: SessionChange[] = [];
    client.subscribe((_session, change) => changes.push(change));

    await expect(getNews({date: THURSDAY}, {client})).rejects.toBeInstanceOf(
      SessionExpiredError,
    );
    expect(await restoreSession({client})).toBeUndefined();
    expect(changes).toEqual([]);
  });

  it('drops a refresh that finishes after logout', async () => {
    const client = newClient();
    await login('trader1', 'demo', {client});
    let releaseRefresh = () => {};
    const gate = new Promise<void>(resolve => {
      releaseRefresh = resolve;
    });
    server.use(
      http.post(apiUrl('/auth/refresh'), async () => {
        await gate;
        return undefined;
      }),
    );

    const refresh = client.refresh();
    client.clearSession('logout');
    releaseRefresh();

    await expect(refresh).rejects.toBeInstanceOf(SessionExpiredError);
    expect(client.getSession()).toBeUndefined();
  });

  it('does not log out on a network failure during refresh', async () => {
    const client = newClient();
    await login('trader1', 'demo', {client});
    expireTokens();
    server.use(http.post(apiUrl('/auth/refresh'), () => HttpResponse.error()));

    await expect(getNews({date: THURSDAY}, {client})).rejects.toBeInstanceOf(
      NetworkError,
    );
    expect(client.getSession()).toBeDefined();
  });
});

describe('errors', () => {
  it('maps a 500 with a plain-text body to HttpError', async () => {
    const client = newClient();
    await login('trader1', 'demo', {client});
    setScenario('server-error');
    await expect(getNews({date: THURSDAY}, {client})).rejects.toMatchObject({
      name: 'HttpError',
      status: 500,
      detail: undefined,
    });
  });

  it('keeps FastAPI detail for 404 and 422', async () => {
    const client = newClient();
    await login('trader1', 'demo', {client});
    await expect(getNewsItem(999, {client})).rejects.toMatchObject({
      status: 404,
      detail: 'Not found',
    });
    await expect(getNews({date: 'yesterday'}, {client})).rejects.toMatchObject({
      status: 422,
      detail: [expect.objectContaining({loc: ['query', 'date']})],
    });
  });

  it('turns contract drift into ContractError and logs where', async () => {
    const consoleError = vi
      .spyOn(console, 'error')
      .mockImplementation(() => undefined);
    const client = newClient();
    await login('trader1', 'demo', {client});
    setScenario('contract-drift');

    const error = await getNews({date: THURSDAY}, {client}).catch(
      (e: unknown) => e,
    );

    expect(error).toBeInstanceOf(ContractError);
    expect(error).toMatchObject({
      message: 'Unexpected response from the server',
      endpoint: 'GET /news',
      path: 'count',
    });
    expect(consoleError).toHaveBeenCalledWith(
      expect.stringContaining('GET /news at "count"'),
      expect.anything(),
    );
    consoleError.mockRestore();
  });

  it('reports a network failure as NetworkError offline', async () => {
    server.use(http.get(apiUrl('/health'), () => HttpResponse.error()));
    await expect(getHealth({client: newClient()})).rejects.toMatchObject({
      name: 'NetworkError',
      reason: 'offline',
    });
  });

  it('lets the caller cancel: AbortError, not a network error', async () => {
    server.use(
      http.get(apiUrl('/health'), async () => {
        await delay('infinite');
        return HttpResponse.json({status: 'ok'});
      }),
    );
    const controller = new AbortController();
    const call = getHealth({client: newClient(), signal: controller.signal});
    controller.abort();
    await expect(call).rejects.toMatchObject({name: 'AbortError'});
  });

  it('times out a request that never answers', async () => {
    server.use(
      http.get(apiUrl('/health'), async () => {
        await delay('infinite');
        return HttpResponse.json({status: 'ok'});
      }),
    );
    await expect(getHealth({client: newClient(20)})).rejects.toMatchObject({
      name: 'NetworkError',
      reason: 'timeout',
    });
  });
});
