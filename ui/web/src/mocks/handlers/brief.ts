import {HttpResponse, delay, http} from 'msw';

import {WATCHLIST_MAX_TICKERS, briefEditionSchema} from '@/api/schemas/brief';
import type {BriefMetaWire} from '@/api/schemas/brief';
import {apiUrl} from '@/lib/env';
import {isIsoDate} from '@/lib/time';

import {MOCK_SECTORS, generatedBriefMeta, mockBrief} from '../data/brief';
import {REAL_COMPANIES} from '../data/companies';
import {db} from '../data/db';
import type {StartedBrief} from '../data/db';
import {MOCK_USERS} from '../data/users';
import {activeScenario} from '../scenarios';

import {
  rejectUnauthenticated,
  requestUser,
  scenarioLatency,
  validationError,
} from './common';
import {latestVerifyRun, reviewedItem} from './verify';

/**
 * The pre-market brief and the watchlist (increment 5): `GET
 * /briefs/today` (server-sent events), `POST /briefs` (ANALYST, ADMIN) and
 * `GET` / `PUT /me/watchlist`.
 */

export const BRIEF_FAILED = 'The brief failed. An analyst can write it again.';
const TICKER = /^[A-Z][A-Z0-9.-]{0,9}$/;
/** The mock's SEC registry: its companies (the invented ones aren't). */
const REGISTRY = new Set(REAL_COMPANIES.map(company => company.ticker));

function sse(name: string, data: unknown): string {
  return `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
}

function watchlistOf(username: string) {
  return db.watchlists.get(username) ?? {tickers: [], sectors: []};
}

function stamp(ms: number): string {
  return new Date(ms).toISOString().replace(/\.\d+Z$/, 'Z');
}

function startedMeta(brief: StartedBrief, done: boolean): BriefMetaWire {
  const steps = 4;
  return {
    brief_id: brief.briefId,
    feed_date: brief.date,
    edition: brief.edition,
    status: done ? 'DONE' : 'RUNNING',
    requested_by: brief.requestedBy,
    requested_at: stamp(brief.startedAt),
    started_at: stamp(brief.startedAt),
    finished_at: done ? stamp(brief.startedAt + steps * db.briefStepMs) : null,
    error: null,
  };
}

/**
 * The stream of a brief: `brief`, then (while it is written) its progress
 * paced by `db.briefStepMs` from `startedAt`, then `done` or `error`.
 */
function briefStream(
  meta: BriefMetaWire,
  username: string,
  startedAt: number | undefined,
  failed: boolean,
): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let cancelled = false;
  return new ReadableStream<Uint8Array>({
    async start(controller) {
      const send = (name: string, data: unknown) =>
        controller.enqueue(encoder.encode(sse(name, data)));
      send('brief', meta);
      if (failed) {
        send('error', {detail: BRIEF_FAILED});
        controller.close();
        return;
      }
      const brief = () =>
        mockBrief(
          db.day(meta.feed_date).items.map(reviewedItem),
          {
            ...meta,
            status: 'DONE',
            finished_at: meta.finished_at ?? stamp(db.now()),
          },
          watchlistOf(username),
        );
      if (meta.status !== 'DONE' && startedAt !== undefined) {
        const counts = brief().counts;
        const steps: Array<[string, unknown]> = [
          ['status', {detail: 'Collecting the verified items'}],
          ['sections', {counts}],
          ['status', {detail: 'Writing the overview (cloud-openai)'}],
        ];
        for (const [index, [name, data]] of steps.entries()) {
          const wait = startedAt + (index + 1) * db.briefStepMs - db.now();
          if (wait > 0) {
            await delay(wait);
          }
          if (cancelled) {
            return;
          }
          send(name, data);
        }
        const wait = startedAt + (steps.length + 1) * db.briefStepMs - db.now();
        if (wait > 0) {
          await delay(wait);
        }
        if (cancelled) {
          return;
        }
      }
      send('done', brief());
      controller.close();
    },
    cancel() {
      cancelled = true;
    },
  });
}

function forbiddenFor(request: Request): Response | undefined {
  const username = requestUser(request);
  const role = MOCK_USERS.find(user => user.username === username)?.role;
  if (role === 'ANALYST' || role === 'ADMIN') {
    return undefined;
  }
  return HttpResponse.json({detail: 'Forbidden'}, {status: 403});
}

async function readJson(request: Request): Promise<unknown> {
  try {
    return (await request.json()) as unknown;
  } catch {
    return undefined;
  }
}

function asRecord(body: unknown): Record<string, unknown> | undefined {
  return typeof body === 'object' && body !== null && !Array.isArray(body)
    ? {...body}
    : undefined;
}

function stringList(value: unknown): string[] | undefined {
  if (value === undefined) {
    return [];
  }
  if (!Array.isArray(value) || !value.every(v => typeof v === 'string')) {
    return undefined;
  }
  return value;
}

export const briefHandlers = [
  http.get(apiUrl('/briefs/today'), async ({request}) => {
    await scenarioLatency();
    const denied = rejectUnauthenticated(request);
    if (denied !== undefined) {
      return denied;
    }
    const username = requestUser(request) ?? '';
    const date = new URL(request.url).searchParams.get('date') ?? db.today();
    if (!isIsoDate(date)) {
      return validationError({
        loc: ['query', 'date'],
        msg: 'Input should be a valid date in the format YYYY-MM-DD',
        type: 'date_from_datetime_parsing',
      });
    }
    const day = db.day(date);
    const started = db.startedBriefs
      .filter(brief => brief.date === date)
      .at(-1);
    const verified = latestVerifyRun(day)?.status === 'DONE';
    if (!verified && started === undefined) {
      return HttpResponse.json(
        {detail: `No brief for ${date} yet`},
        {status: 404},
      );
    }
    const scenario = activeScenario();
    let meta = generatedBriefMeta(date);
    let startedAt: number | undefined;
    if (started !== undefined) {
      const done = db.now() >= started.startedAt + 4 * db.briefStepMs;
      meta = startedMeta(started, done);
      startedAt = done ? undefined : started.startedAt;
    } else if (scenario === 'brief-writing') {
      // As if the 07:15 brief were being written right now.
      startedAt = db.now();
      meta = {...meta, status: 'RUNNING', finished_at: null};
    }
    const failed = scenario === 'brief-failed';
    if (failed) {
      meta = {...meta, status: 'FAILED', error: 'The brief failed.'};
    }
    return new HttpResponse(briefStream(meta, username, startedAt, failed), {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
      },
    });
  }),

  http.post(apiUrl('/briefs'), async ({request}) => {
    await scenarioLatency();
    const denied = rejectUnauthenticated(request) ?? forbiddenFor(request);
    if (denied !== undefined) {
      return denied;
    }
    const body = asRecord(await readJson(request)) ?? {};
    const date = typeof body.date === 'string' ? body.date : db.today();
    const edition = briefEditionSchema.safeParse(body.edition ?? 'morning');
    if (!isIsoDate(date) || !edition.success) {
      return validationError({
        loc: ['body', edition.success ? 'date' : 'edition'],
        msg: 'Invalid value',
        type: 'value_error',
      });
    }
    const run = latestVerifyRun(db.day(date));
    if (run?.status !== 'DONE') {
      return HttpResponse.json(
        {
          detail: `The AI verification of ${date} is ${run?.status ?? 'missing'}`,
        },
        {status: 409},
      );
    }
    const writing = db.startedBriefs.some(
      brief =>
        brief.date === date && db.now() < brief.startedAt + 4 * db.briefStepMs,
    );
    if (writing) {
      return HttpResponse.json(
        {detail: `The brief of ${date} is being written`},
        {status: 409},
      );
    }
    const brief = db.startBrief(date, edition.data, requestUser(request) ?? '');
    return HttpResponse.json(
      {...startedMeta(brief, false), status: 'QUEUED', started_at: null},
      {status: 202},
    );
  }),

  http.get(apiUrl('/me/watchlist'), async ({request}) => {
    await scenarioLatency();
    const denied = rejectUnauthenticated(request);
    if (denied !== undefined) {
      return denied;
    }
    const saved = watchlistOf(requestUser(request) ?? '');
    return HttpResponse.json({...saved, available_sectors: MOCK_SECTORS});
  }),

  http.put(apiUrl('/me/watchlist'), async ({request}) => {
    await scenarioLatency();
    const denied = rejectUnauthenticated(request);
    if (denied !== undefined) {
      return denied;
    }
    const body = asRecord(await readJson(request));
    const rawTickers = stringList(body?.tickers);
    const rawSectors = stringList(body?.sectors);
    if (
      body === undefined ||
      rawTickers === undefined ||
      rawSectors === undefined
    ) {
      return validationError({
        loc: ['body'],
        msg: 'Input should be a list of strings',
        type: 'list_type',
      });
    }
    if (rawTickers.length > WATCHLIST_MAX_TICKERS) {
      return validationError({
        loc: ['body', 'tickers'],
        msg: `List should have at most ${WATCHLIST_MAX_TICKERS} items`,
        type: 'too_long',
      });
    }
    const tickers: string[] = [];
    for (const raw of rawTickers) {
      const ticker = raw.trim().toUpperCase();
      if (!TICKER.test(ticker)) {
        return HttpResponse.json(
          {detail: `Not a ticker: '${raw.slice(0, 20)}'`},
          {status: 422},
        );
      }
      if (!REGISTRY.has(ticker)) {
        return HttpResponse.json(
          {detail: `Not in the SEC ticker registry: ${ticker}`},
          {status: 422},
        );
      }
      if (!tickers.includes(ticker)) {
        tickers.push(ticker);
      }
    }
    const sectors: string[] = [];
    for (const raw of rawSectors) {
      const sector = raw.trim();
      if (!MOCK_SECTORS.includes(sector)) {
        return HttpResponse.json(
          {detail: `Unknown sector: '${sector.slice(0, 60)}'`},
          {status: 422},
        );
      }
      if (!sectors.includes(sector)) {
        sectors.push(sector);
      }
    }
    db.watchlists.set(requestUser(request) ?? '', {tickers, sectors});
    return HttpResponse.json({
      tickers,
      sectors,
      available_sectors: MOCK_SECTORS,
    });
  }),
];
