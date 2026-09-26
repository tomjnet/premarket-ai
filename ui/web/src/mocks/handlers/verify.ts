import {HttpResponse, delay, http} from 'msw';

import type {NewsDetailWire, VerifyRunWire} from '@/api/schemas/news';
import {COMMENT_MAX_CHARS, COMMENT_MIN_CHARS} from '@/api/schemas/verify';
import type {ReviewTaskWire} from '@/api/schemas/verify';
import {reviewStatusSchema, verdictSchema} from '@/api/schemas/news';
import type {ValidationIssue} from '@/api/schemas/errors';
import {apiUrl} from '@/lib/env';
import {isIsoDate} from '@/lib/time';

import {db} from '../data/db';
import type {StartedRun} from '../data/db';
import type {GeneratedDay} from '../data/generator';
import {MOCK_USERS} from '../data/users';
import {reviewTaskOf, withReview} from '../data/verify';
import {activeScenario} from '../scenarios';

import {
  notFound,
  rejectUnauthenticated,
  requestUser,
  scenarioLatency,
  validationError,
} from './common';

/**
 * The AI verification's endpoints (increment 4, ANALYST and ADMIN): verify
 * runs and their server-sent events, and the review queue.
 */

export const ALREADY_REVIEWED = 'This item was already reviewed';

/** `403` for a role that may not call the verification endpoints. */
function forbiddenFor(request: Request): Response | undefined {
  const username = requestUser(request);
  const role = MOCK_USERS.find(user => user.username === username)?.role;
  if (role === 'ANALYST' || role === 'ADMIN') {
    return undefined;
  }
  return HttpResponse.json({detail: 'Forbidden'}, {status: 403});
}

/** The scenarios that serve a partial day have no verify run. */
function verifiable(day: GeneratedDay): boolean {
  const scenario = activeScenario();
  return (
    day.verifyRun !== null &&
    scenario !== 'running' &&
    scenario !== 'failed' &&
    scenario !== 'rules-failed'
  );
}

/** The items the day's verify run verified itself (its `item` events). */
function verifiedItems(day: GeneratedDay): NewsDetailWire[] {
  return day.items
    .filter(item => item.verdict_source === 'ai')
    .sort((a, b) => a.vendor_item_id.localeCompare(b.vendor_item_id));
}

/** A started run as the API serves it, with its progress by time. */
function startedRunWire(run: StartedRun): VerifyRunWire {
  const day = db.day(run.date);
  const items = verifiedItems(day);
  const done =
    db.runItemMs <= 0
      ? items.length
      : Math.min(
          items.length,
          Math.floor((db.now() - run.startedAt) / db.runItemMs),
        );
  const finished = done >= items.length;
  const doneItems = items.slice(0, done);
  const count = (verdict: string) =>
    doneItems.filter(item => item.verdict === verdict).length;
  const startedAt = new Date(run.startedAt)
    .toISOString()
    .replace(/\.\d+Z$/, 'Z');
  return {
    run_id: run.runId,
    feed_date: run.date,
    status: finished ? 'DONE' : 'RUNNING',
    requested_by: run.requestedBy,
    requested_at: startedAt,
    started_at: startedAt,
    finished_at: finished
      ? new Date(run.startedAt + items.length * db.runItemMs)
          .toISOString()
          .replace(/\.\d+Z$/, 'Z')
      : null,
    total: items.length,
    done,
    failed: 0,
    verified: count('VERIFIED'),
    unverified: count('UNVERIFIED'),
    misleading: count('MISLEADING'),
    fake: count('FAKE'),
    pending_review: doneItems.filter(item => item.review_status === 'PENDING')
      .length,
    escalated: finished ? (day.verifyRun?.escalated ?? 0) : 0,
    model: day.verifyRun?.model ?? null,
    error: null,
  };
}

/** The latest verify run of a date: a started one, else the generated one. */
export function latestVerifyRun(day: GeneratedDay): VerifyRunWire | null {
  if (!verifiable(day)) {
    return null;
  }
  const started = db.runsOf(day.date)[0];
  return started === undefined ? day.verifyRun : startedRunWire(started);
}

/** Every run of a date, newest first. */
function runsOf(day: GeneratedDay): VerifyRunWire[] {
  if (!verifiable(day) || day.verifyRun === null) {
    return [];
  }
  return [...db.runsOf(day.date).map(startedRunWire), day.verifyRun];
}

/** A run by id: a started one, or a date's generated one. */
function findRun(
  runId: number,
): {run: VerifyRunWire; started?: StartedRun} | undefined {
  const started = db.startedRuns.find(run => run.runId === runId);
  if (started !== undefined) {
    return {run: startedRunWire(started), started};
  }
  for (const date of recentDates()) {
    const day = db.day(date);
    if (day.verifyRun?.run_id === runId && verifiable(day)) {
      return {run: day.verifyRun};
    }
  }
  return undefined;
}

/** The dates a generated run can belong to: the last two weeks. */
function recentDates(): string[] {
  const dates: string[] = [];
  const today = new Date(`${db.today()}T00:00:00Z`);
  for (let back = 0; back < 14; back += 1) {
    const date = new Date(today.getTime() - back * 86_400_000);
    dates.push(date.toISOString().slice(0, 10));
  }
  return dates;
}

/** An item as served after any review decision on it (or its original). */
export function reviewedItem(item: NewsDetailWire): NewsDetailWire {
  const reviewId = item.verification?.review?.id;
  return reviewId === undefined
    ? item
    : withReview(item, db.reviews.get(reviewId));
}

function reviewTasks(day: GeneratedDay): ReviewTaskWire[] {
  if (!verifiable(day)) {
    return [];
  }
  return day.items
    .map(reviewedItem)
    .map(reviewTaskOf)
    .filter((task): task is ReviewTaskWire => task !== undefined)
    .sort(
      (a, b) =>
        Number(b.status === 'PENDING') - Number(a.status === 'PENDING') ||
        b.impact_score - a.impact_score ||
        a.id - b.id,
    );
}

function sse(name: string, data: unknown, id: number): string {
  return `id: ${id}-0\nevent: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
}

/**
 * A run's events: `run.started`, one `item` per verified item, then
 * `run.done`. A started run's items come one every `db.runItemMs`, as it
 * progresses; a finished run replays at once.
 */
function runStream(
  run: VerifyRunWire,
  started?: StartedRun,
): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  const day = db.day(run.feed_date);
  const items = verifiedItems(day);
  let cancelled = false;
  return new ReadableStream<Uint8Array>({
    async start(controller) {
      let id = 1;
      controller.enqueue(
        encoder.encode(
          sse(
            'run.started',
            {total: items.length, feed_date: run.feed_date},
            id,
          ),
        ),
      );
      for (const [index, item] of items.entries()) {
        if (cancelled) {
          return;
        }
        if (started !== undefined && db.runItemMs > 0) {
          const due = started.startedAt + (index + 1) * db.runItemMs;
          const wait = due - db.now();
          if (wait > 0) {
            await delay(wait);
          }
        }
        id += 1;
        controller.enqueue(
          encoder.encode(
            sse(
              'item',
              {
                news_id: item.id,
                vendor_item_id: item.vendor_item_id,
                verdict: item.verdict,
                confidence: item.confidence ?? undefined,
                review: item.review_status === 'PENDING',
                done: index + 1,
                total: items.length,
              },
              id,
            ),
          ),
        );
      }
      if (cancelled) {
        return;
      }
      const final = started === undefined ? run : startedRunWire(started);
      controller.enqueue(
        encoder.encode(sse('run.done', {...final, status: 'DONE'}, id + 1)),
      );
      controller.close();
    },
    cancel() {
      cancelled = true;
    },
  });
}

async function readJson(request: Request): Promise<unknown> {
  try {
    return (await request.json()) as unknown;
  } catch {
    return undefined;
  }
}

function bodyIssue(msg: string, loc: Array<string | number>): ValidationIssue {
  return {loc: ['body', ...loc], msg, type: 'value_error'};
}

export const verifyHandlers = [
  http.post(apiUrl('/runs'), async ({request}) => {
    await scenarioLatency();
    const denied = rejectUnauthenticated(request) ?? forbiddenFor(request);
    if (denied !== undefined) {
      return denied;
    }
    const body = await readJson(request);
    const date =
      typeof body === 'object' && body !== null && 'date' in body
        ? (body as {date: unknown}).date
        : db.today();
    if (typeof date !== 'string' || !isIsoDate(date)) {
      return validationError(
        bodyIssue('Input should be a valid date', ['date']),
      );
    }
    const day = db.day(date);
    if (!verifiable(day)) {
      const detail =
        day.aiRun === null
          ? `The AI run of ${date} is missing`
          : `The rule run of ${date} is RUNNING`;
      return HttpResponse.json({detail}, {status: 409});
    }
    if (db.runsOf(date).some(run => startedRunWire(run).status !== 'DONE')) {
      return HttpResponse.json(
        {detail: `${date} is already being verified`},
        {status: 409},
      );
    }
    const run = db.startRun(date, requestUser(request) ?? 'analyst1');
    const wire = startedRunWire(run);
    return HttpResponse.json(
      {...wire, status: 'QUEUED', started_at: null, done: 0},
      {status: 202},
    );
  }),

  http.get(apiUrl('/runs'), async ({request}) => {
    await scenarioLatency();
    const denied = rejectUnauthenticated(request) ?? forbiddenFor(request);
    if (denied !== undefined) {
      return denied;
    }
    const date = new URL(request.url).searchParams.get('date') ?? db.today();
    if (!isIsoDate(date)) {
      return validationError({
        loc: ['query', 'date'],
        msg: 'Input should be a valid date in the format YYYY-MM-DD',
        type: 'date_from_datetime_parsing',
      });
    }
    const items = runsOf(db.day(date));
    return HttpResponse.json({count: items.length, items});
  }),

  http.get(apiUrl('/runs/:id/events'), async ({request, params}) => {
    await scenarioLatency();
    const denied = rejectUnauthenticated(request) ?? forbiddenFor(request);
    if (denied !== undefined) {
      return denied;
    }
    const found = findRun(Number(params.id));
    if (found === undefined) {
      return notFound();
    }
    return new HttpResponse(runStream(found.run, found.started), {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
      },
    });
  }),

  http.get(apiUrl('/runs/:id'), async ({request, params}) => {
    await scenarioLatency();
    const denied = rejectUnauthenticated(request) ?? forbiddenFor(request);
    if (denied !== undefined) {
      return denied;
    }
    const found = findRun(Number(params.id));
    return found === undefined ? notFound() : HttpResponse.json(found.run);
  }),

  http.get(apiUrl('/review'), async ({request}) => {
    await scenarioLatency();
    const denied = rejectUnauthenticated(request) ?? forbiddenFor(request);
    if (denied !== undefined) {
      return denied;
    }
    const params = new URL(request.url).searchParams;
    const date = params.get('date') ?? db.today();
    const status = params.get('status') ?? 'PENDING';
    if (!isIsoDate(date) || !reviewStatusSchema.safeParse(status).success) {
      return validationError({
        loc: ['query', isIsoDate(date) ? 'status' : 'date'],
        msg: 'Input should be a valid value',
        type: 'enum',
      });
    }
    const items = reviewTasks(db.day(date)).filter(
      task => task.status === status,
    );
    return HttpResponse.json({count: items.length, items});
  }),

  http.post(apiUrl('/review/:id'), async ({request, params}) => {
    await scenarioLatency();
    const denied = rejectUnauthenticated(request) ?? forbiddenFor(request);
    if (denied !== undefined) {
      return denied;
    }
    const body = await readJson(request);
    const decision = parseDecision(body);
    if ('issue' in decision) {
      return validationError(decision.issue);
    }
    const id = Number(params.id);
    const item = db.item(id);
    const task =
      item === undefined ? undefined : reviewTaskOf(reviewedItem(item));
    if (item === undefined || task === undefined) {
      return notFound();
    }
    if (task.status !== 'PENDING') {
      return HttpResponse.json({detail: ALREADY_REVIEWED}, {status: 409});
    }
    db.reviews.set(id, {
      ...decision,
      reviewer: requestUser(request) ?? 'analyst1',
      decidedAt: new Date(db.now()).toISOString().replace(/\.\d+Z$/, 'Z'),
    });
    const decided = reviewTaskOf(reviewedItem(item));
    return HttpResponse.json(decided);
  }),
];

type ParsedDecision =
  | {
      action: 'approve' | 'override';
      verdict: null | 'VERIFIED' | 'UNVERIFIED' | 'MISLEADING' | 'FAKE';
      comment: string;
    }
  | {issue: ValidationIssue};

/** The body, checked like FastAPI's `ReviewIn` model. */
function parseDecision(body: unknown): ParsedDecision {
  if (typeof body !== 'object' || body === null) {
    return {issue: bodyIssue('Field required', [])};
  }
  const {action, verdict, comment} = body as Record<string, unknown>;
  const text = typeof comment === 'string' ? comment.trim() : '';
  if (action !== 'approve' && action !== 'override') {
    return {
      issue: bodyIssue("Input should be 'approve' or 'override'", ['action']),
    };
  }
  if (typeof comment === 'string' && comment.length > COMMENT_MAX_CHARS) {
    return {issue: bodyIssue('String too long', ['comment'])};
  }
  if (action === 'approve') {
    if (verdict !== undefined && verdict !== null) {
      return {issue: bodyIssue('approve takes no verdict', [])};
    }
    return {action, verdict: null, comment: text};
  }
  const parsed = verdictSchema.safeParse(verdict);
  if (!parsed.success) {
    return {issue: bodyIssue('an override needs the new verdict', [])};
  }
  if (text.length < COMMENT_MIN_CHARS) {
    return {issue: bodyIssue('an override needs a comment', [])};
  }
  return {action, verdict: parsed.data, comment: text};
}
