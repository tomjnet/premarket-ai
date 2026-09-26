import {describe, expect, it} from 'vitest';

import {tokenResponseWireSchema} from '@/api/schemas/auth';
import {
  adminLlmWireSchema,
  adminSourceWireSchema,
  adminUserWireSchema,
  alertListSchema,
  budgetWireSchema,
  scheduleWireSchema,
  scorecardSummaryWireSchema,
  scorecardWireSchema,
} from '@/api/schemas/ops';

import {db} from '../data/db';

import {pushAlert} from './ops';

// Contract tests: raw fetch, so the wire format itself is checked.

async function token(username: string): Promise<string> {
  const response = await fetch('/api/auth/login', {
    method: 'POST',
    body: new URLSearchParams({username, password: 'demo'}),
  });
  return tokenResponseWireSchema.parse(await response.json()).access_token;
}

async function call(
  path: string,
  username: string,
  init: RequestInit = {},
): Promise<{status: number; body: unknown; text: string}> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${await token(username)}`,
      'Content-Type': 'application/json',
    },
  });
  const text = await response.text();
  let body: unknown = text;
  try {
    body = JSON.parse(text) as unknown;
  } catch {
    // CSV or SSE.
  }
  return {status: response.status, body, text};
}

describe('ops handlers (increment 6)', () => {
  it('serves the budget to every role', async () => {
    db.cloudSpendUsd = 20;
    const {status, body} = await call('/llm/budget', 'trader1');
    expect(status).toBe(200);
    expect(budgetWireSchema.parse(body).reached).toBe(true);
  });

  it('serves alerts, the schedule and the scorecard to analysts only', async () => {
    pushAlert({
      key: 'k',
      title: 't',
      severity: 'warning',
      status: 'firing',
      detail: '',
      source: 'scheduler',
    });
    const alerts = await call('/alerts', 'analyst1');
    expect(alertListSchema.parse(alerts.body)).toHaveLength(1);
    const schedule = await call('/schedule?date=2026-09-24', 'analyst1');
    expect(scheduleWireSchema.parse(schedule.body).sla_green).toBe(true);
    const scorecard = await call('/vendor/scorecard?days=5', 'admin1');
    expect(scorecardWireSchema.parse(scorecard.body).items.length).toBe(5);
    const summary = await call('/vendor/scorecard/summary', 'admin1');
    expect(scorecardSummaryWireSchema.parse(summary.body).source).toBe('llm');
    const csv = await call('/vendor/scorecard.csv?days=3', 'admin1');
    expect(csv.text.split('\n')[0]).toBe(
      'feed_date,received,unique_items,duplicates,fake,misleading,billable,contracted',
    );
    const stream = await call('/alerts/stream', 'admin1');
    expect(stream.text).toContain('event: snapshot');
    for (const path of ['/alerts', '/schedule', '/vendor/scorecard']) {
      expect((await call(path, 'trader1')).status).toBe(403);
    }
    expect((await call('/vendor/scorecard?days=0', 'admin1')).status).toBe(422);
  });

  it('serves the admin endpoints to admins only', async () => {
    const created = await call('/admin/users', 'admin1', {
      method: 'POST',
      body: JSON.stringify({
        username: 'new.user',
        role: 'ANALYST',
        password: 'a-long-enough-password',
      }),
    });
    expect(created.status).toBe(201);
    adminUserWireSchema.parse(created.body);
    const self = await call('/admin/users/admin1', 'admin1', {
      method: 'POST',
      body: JSON.stringify({disabled: true}),
    });
    expect(self.status).toBe(409);
    const source = await call('/admin/sources', 'admin1', {
      method: 'POST',
      body: JSON.stringify({
        domain: 'news.example',
        tier: 'neutral',
        reputation: 0.5,
        note: '',
      }),
    });
    adminSourceWireSchema.parse(source.body);
    const llm = await call('/admin/llm', 'admin1', {
      method: 'POST',
      body: JSON.stringify({judge: false}),
    });
    expect(adminLlmWireSchema.parse(llm.body).cloud.judge).toBe(false);
    for (const path of ['/admin/users', '/admin/sources', '/admin/llm']) {
      expect((await call(path, 'analyst1')).status).toBe(403);
    }
  });
});
