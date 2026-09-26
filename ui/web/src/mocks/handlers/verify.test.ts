import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import {tokenResponseWireSchema} from '@/api/schemas/auth';
import {errorBodySchema} from '@/api/schemas/errors';
import {newsDetailWireSchema, newsListWireSchema} from '@/api/schemas/news';
import {
  reviewListWireSchema,
  reviewTaskWireSchema,
  verifyRunListWireSchema,
} from '@/api/schemas/verify';

import {db} from '../data/db';
import {setScenario} from '../scenarios';

// Contract tests of the increment 4 endpoints: raw fetch, wire format.
const THURSDAY = '2026-09-24';
const NOW = new Date('2026-09-25T13:00:00Z');

beforeEach(() => {
  vi.useFakeTimers({toFake: ['Date']});
  vi.setSystemTime(NOW);
  db.runItemMs = 0;
});

afterEach(() => {
  vi.useRealTimers();
});

async function token(username = 'analyst1'): Promise<string> {
  const response = await fetch('/api/auth/login', {
    method: 'POST',
    body: new URLSearchParams({username, password: 'demo'}),
  });
  return tokenResponseWireSchema.parse(await response.json()).access_token;
}

async function call(
  method: 'GET' | 'POST',
  path: string,
  accessToken: string,
  json?: unknown,
) {
  const response = await fetch(`/api${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      ...(json === undefined ? {} : {'Content-Type': 'application/json'}),
    },
    body: json === undefined ? undefined : JSON.stringify(json),
  });
  const text = await response.text();
  let body: unknown = text;
  try {
    body = JSON.parse(text) as unknown;
  } catch {
    // An event stream.
  }
  return {status: response.status, body, text, headers: response.headers};
}

describe('verify mock: roles', () => {
  it('refuses traders (403) on every verification endpoint', async () => {
    const trader = await token('trader1');
    for (const [method, path] of [
      ['GET', '/review'],
      ['GET', '/runs'],
      ['POST', '/runs'],
      ['POST', '/review/1'],
    ] as const) {
      const {status, body} = await call(method, path, trader, {});
      expect(status).toBe(403);
      expect(body).toEqual({detail: 'Forbidden'});
    }
  });
});

describe('verify mock: verdicts in the feed', () => {
  it('serves verdicts, the verify run, and the verdict filters', async () => {
    const analyst = await token();
    const {body} = await call('GET', `/news?date=${THURSDAY}`, analyst);
    const list = newsListWireSchema.parse(body);
    expect(list.verify_run?.status).toBe('DONE');
    expect(list.items.every(item => item.verdict !== null)).toBe(true);
    const verdicts = new Set(list.items.map(item => item.verdict));
    expect(verdicts).toEqual(
      new Set(['VERIFIED', 'UNVERIFIED', 'MISLEADING', 'FAKE']),
    );
    const fake = newsListWireSchema.parse(
      (await call('GET', `/news?date=${THURSDAY}&verdict=FAKE`, analyst)).body,
    );
    expect(fake.items.length).toBeGreaterThan(0);
    expect(fake.items.every(item => item.verdict === 'FAKE')).toBe(true);
    const pending = newsListWireSchema.parse(
      (await call('GET', `/news?date=${THURSDAY}&pending_review=true`, analyst))
        .body,
    );
    expect(pending.items.every(item => item.review_status === 'PENDING')).toBe(
      true,
    );
    expect(pending.count).toBe(list.verify_run?.pending_review);
    const bad = await call(
      'GET',
      `/news?date=${THURSDAY}&verdict=TRUE`,
      analyst,
    );
    expect(bad.status).toBe(422);
    expect(errorBodySchema.safeParse(bad.body).success).toBe(true);
  });

  it('has no verify run before the first verified date', async () => {
    const analyst = await token();
    const {body} = await call('GET', '/news?date=2026-09-23', analyst);
    const list = newsListWireSchema.parse(body);
    expect(list.verify_run).toBeNull();
    expect(list.items.every(item => item.verdict === null)).toBe(true);
  });

  it('serves the verification on the detail, inherited by duplicates', async () => {
    const analyst = await token();
    const item = db
      .day(THURSDAY)
      .items.find(
        entry =>
          entry.is_dup &&
          entry.verdict_source === 'inherited' &&
          entry.verification !== null,
      );
    expect(item).toBeDefined();
    const {body} = await call('GET', `/news/${item?.id}`, analyst);
    const detail = newsDetailWireSchema.parse(body);
    expect(detail.verification?.evidence.length).toBeGreaterThan(0);
    expect(detail.verdict).toBe(detail.verification?.verdict);
  });
});

describe('verify mock: review queue', () => {
  it('lists pending tasks by impact, and decides them once', async () => {
    const analyst = await token();
    const queue = reviewListWireSchema.parse(
      (await call('GET', `/review?date=${THURSDAY}`, analyst)).body,
    );
    expect(queue.count).toBeGreaterThan(1);
    const scores = queue.items.map(task => task.impact_score);
    expect([...scores].sort((a, b) => b - a)).toEqual(scores);
    const task = queue.items[0];
    if (task === undefined) {
      throw new Error('no task');
    }
    const approved = await call('POST', `/review/${task.id}`, analyst, {
      action: 'approve',
    });
    expect(approved.status).toBe(200);
    expect(reviewTaskWireSchema.parse(approved.body)).toMatchObject({
      status: 'APPROVED',
      reviewer: 'analyst1',
      final_verdict: task.ai_verdict,
    });
    const again = await call('POST', `/review/${task.id}`, analyst, {
      action: 'approve',
    });
    expect(again.status).toBe(409);
    const after = reviewListWireSchema.parse(
      (await call('GET', `/review?date=${THURSDAY}`, analyst)).body,
    );
    expect(after.count).toBe(queue.count - 1);
    const detail = newsDetailWireSchema.parse(
      (await call('GET', `/news/${task.item_id}`, analyst)).body,
    );
    expect(detail.review_status).toBe('APPROVED');
  });

  it('checks an override like the backend (422), then stores it', async () => {
    const analyst = await token();
    const queue = reviewListWireSchema.parse(
      (await call('GET', `/review?date=${THURSDAY}`, analyst)).body,
    );
    const task = queue.items[1];
    if (task === undefined) {
      throw new Error('no task');
    }
    for (const bad of [
      {action: 'override', comment: 'Made up.'},
      {action: 'override', verdict: 'FAKE', comment: ' '},
      {action: 'approve', verdict: 'FAKE'},
      {action: 'delete'},
    ]) {
      const {status} = await call('POST', `/review/${task.id}`, analyst, bad);
      expect(status).toBe(422);
    }
    const done = await call('POST', `/review/${task.id}`, analyst, {
      action: 'override',
      verdict: 'FAKE',
      comment: 'No such story.',
    });
    expect(reviewTaskWireSchema.parse(done.body)).toMatchObject({
      status: 'OVERRIDDEN',
      final_verdict: 'FAKE',
      comment: 'No such story.',
    });
    const detail = newsDetailWireSchema.parse(
      (await call('GET', `/news/${task.item_id}`, analyst)).body,
    );
    expect(detail.verdict).toBe('FAKE');
    expect(detail.verification?.review?.status).toBe('OVERRIDDEN');
    expect(
      (await call('POST', '/review/999999', analyst, {action: 'approve'}))
        .status,
    ).toBe(404);
  });
});

describe('verify mock: runs', () => {
  it('starts a run and streams it to run.done', async () => {
    const analyst = await token();
    const started = await call('POST', '/runs', analyst, {date: THURSDAY});
    expect(started.status).toBe(202);
    const run = started.body as {run_id: number; status: string};
    expect(run.status).toBe('QUEUED');
    const events = await call('GET', `/runs/${run.run_id}/events`, analyst);
    expect(events.headers.get('content-type')).toContain('text/event-stream');
    const names = events.text
      .split('\n')
      .filter(line => line.startsWith('event: '))
      .map(line => line.slice('event: '.length));
    expect(names[0]).toBe('run.started');
    expect(names.at(-1)).toBe('run.done');
    const runs = verifyRunListWireSchema.parse(
      (await call('GET', `/runs?date=${THURSDAY}`, analyst)).body,
    );
    expect(runs.items[0]).toMatchObject({run_id: run.run_id, status: 'DONE'});
  });

  it('refuses a date without an AI run, and a second run at once', async () => {
    const analyst = await token();
    const early = await call('POST', '/runs', analyst, {date: '2026-09-23'});
    expect(early.status).toBe(409);
    expect(early.body).toEqual({detail: 'The AI run of 2026-09-23 is missing'});
    db.runItemMs = 60_000;
    expect(
      (await call('POST', '/runs', analyst, {date: THURSDAY})).status,
    ).toBe(202);
    const second = await call('POST', '/runs', analyst, {date: THURSDAY});
    expect(second.status).toBe(409);
    setScenario('running');
    const partial = await call('POST', '/runs', analyst, {date: '2026-09-25'});
    expect(partial.status).toBe(409);
    setScenario('default');
  });
});
