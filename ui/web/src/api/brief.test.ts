import {beforeEach, describe, expect, it} from 'vitest';

import {db} from '@/mocks/data/db';
import {setScenario} from '@/mocks/scenarios';

import {login} from './auth';
import {getWatchlist, saveWatchlist, todayBrief, writeBrief} from './brief';
import {ApiClient} from './client';
import {HttpError} from './errors';
import type {BriefEvent} from './schemas/brief';

async function loggedIn(username = 'trader1'): Promise<ApiClient> {
  const client = new ApiClient({baseUrl: '/api'});
  await login(username, 'demo', {client});
  return client;
}

async function collect(date: string, client: ApiClient) {
  const events: BriefEvent[] = [];
  for await (const event of todayBrief(date, {client})) {
    events.push(event);
  }
  return events;
}

beforeEach(() => {
  db.today = () => '2026-09-25';
  db.briefStepMs = 0;
});

describe('todayBrief', () => {
  it('streams a written brief at once: only VERIFIED and watch items', async () => {
    const events = await collect('2026-09-24', await loggedIn());
    expect(events.map(event => event.type)).toEqual(['brief', 'done']);
    const done = events[1];
    if (done?.type !== 'done') {
      throw new Error('no brief');
    }
    const brief = done.data;
    expect(brief.status).toBe('DONE');
    expect(brief.edition).toBe('morning');
    expect(brief.items.length).toBeGreaterThan(10);
    for (const item of brief.items) {
      expect(item.verdict).toBe(
        item.section === 'watch' ? 'UNVERIFIED' : 'VERIFIED',
      );
    }
    expect(brief.counts.fake).toBeGreaterThan(0);
    expect(brief.counts.pendingReview).toBeGreaterThan(0);
    expect(brief.citations.every(n => brief.top.includes(n))).toBe(true);
    expect(brief.watchlist.items).toEqual([]);
  });

  it('is a 404 before the day is verified', async () => {
    const client = await loggedIn();
    await expect(collect('2026-09-23', client)).rejects.toMatchObject({
      status: 404,
      detail: 'No brief for 2026-09-23 yet',
    });
  });

  it('streams the progress of a brief being written', async () => {
    setScenario('brief-writing');
    const events = await collect('2026-09-24', await loggedIn());
    expect(events.map(event => event.type)).toEqual([
      'brief',
      'status',
      'sections',
      'status',
      'done',
    ]);
    const first = events[0];
    expect(first?.type === 'brief' && first.data.status).toBe('RUNNING');
  });

  it('ends with the error of a failed brief', async () => {
    setScenario('brief-failed');
    const events = await collect('2026-09-24', await loggedIn());
    expect(events.at(-1)).toEqual({
      type: 'error',
      detail: 'The brief failed. An analyst can write it again.',
    });
  });

  it('lists the watchlist items of the caller', async () => {
    const client = await loggedIn();
    await saveWatchlist({tickers: [], sectors: ['Energy']}, {client});
    const events = await collect('2026-09-24', client);
    const done = events.at(-1);
    if (done?.type !== 'done') {
      throw new Error('no brief');
    }
    const energy = done.data.items.filter(item => item.sector === 'Energy');
    expect(done.data.watchlist.items).toEqual(energy.map(item => item.n));
  });
});

describe('writeBrief', () => {
  it('is for analysts, after the verification, one at a time', async () => {
    const trader = await loggedIn();
    await expect(
      writeBrief('2026-09-24', 'refresh', {client: trader}),
    ).rejects.toMatchObject({status: 403});
    const analyst = await loggedIn('analyst1');
    db.briefStepMs = 60_000;
    const queued = await writeBrief('2026-09-24', 'refresh', {client: analyst});
    expect(queued.status).toBe('QUEUED');
    expect(queued.edition).toBe('refresh');
    await expect(
      writeBrief('2026-09-24', 'morning', {client: analyst}),
    ).rejects.toMatchObject({status: 409});
    await expect(
      writeBrief('2026-09-23', 'morning', {client: analyst}),
    ).rejects.toMatchObject({
      status: 409,
      detail: 'The AI verification of 2026-09-23 is missing',
    });
  });
});

describe('watchlist', () => {
  it('saves tickers and sectors per user and names a bad value', async () => {
    const client = await loggedIn();
    const empty = await getWatchlist({client});
    expect(empty.tickers).toEqual([]);
    expect(empty.availableSectors).toContain('Energy');
    const saved = await saveWatchlist(
      {tickers: ['aapl', 'MSFT', 'AAPL'], sectors: ['Financials']},
      {client},
    );
    expect(saved.tickers).toEqual(['AAPL', 'MSFT']);
    expect((await getWatchlist({client})).sectors).toEqual(['Financials']);
    const other = await loggedIn('analyst1');
    expect((await getWatchlist({client: other})).tickers).toEqual([]);
    const error = await saveWatchlist(
      {tickers: ['QVXH'], sectors: []},
      {client},
    ).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(HttpError);
    expect((error as HttpError).detail).toBe(
      'Not in the SEC ticker registry: QVXH',
    );
  });
});
