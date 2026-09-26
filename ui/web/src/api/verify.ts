import type {z} from 'zod';

import {apiClient} from './client';
import type {CallOptions} from './client';
import {ContractError, NetworkError} from './errors';
import type {VerifyRun} from './schemas/news';
import {
  reviewListSchema,
  reviewTaskSchema,
  runDoneWireSchema,
  runFailedWireSchema,
  runItemWireSchema,
  runReviewWireSchema,
  runStartedWireSchema,
  verifyRunListSchema,
  verifyRunSchema,
} from './schemas/verify';
import type {ReviewDecision, ReviewTask, RunEvent} from './schemas/verify';
import {readSse} from './sse';

/**
 * The AI verification's API (increment 4, ANALYST and ADMIN): start a
 * verify run and follow it, and the human review queue.
 */

/** `POST /runs`: queues the verification of one feed date. */
export function startRun(
  date: string,
  {client = apiClient, signal}: CallOptions = {},
): Promise<VerifyRun> {
  return client.request({
    method: 'POST',
    path: '/runs',
    json: {date},
    schema: verifyRunSchema,
    signal,
  });
}

/** `GET /runs`: the latest runs of a date, newest first. */
export function getRuns(
  date: string | undefined,
  {client = apiClient, signal}: CallOptions = {},
): Promise<VerifyRun[]> {
  return client.request({
    path: '/runs',
    query: {date, limit: '5'},
    schema: verifyRunListSchema,
    signal,
  });
}

/** `GET /review`: the tasks of one date in one state, by market impact. */
export function getReviewQueue(
  filters: {date?: string; status?: ReviewTask['status']},
  {client = apiClient, signal}: CallOptions = {},
): Promise<ReviewTask[]> {
  return client.request({
    path: '/review',
    query: {date: filters.date, status: filters.status ?? 'PENDING'},
    schema: reviewListSchema,
    signal,
  });
}

/** `POST /review/{id}`: approve or override. `HttpError` 409 if decided. */
export function decideReview(
  id: number,
  decision: ReviewDecision,
  {client = apiClient, signal}: CallOptions = {},
): Promise<ReviewTask> {
  return client.request({
    method: 'POST',
    path: `/review/${id}`,
    json: decision,
    schema: reviewTaskSchema,
    signal,
  });
}

/**
 * `GET /runs/{id}/events`: the run's progress as it happens (the backend
 * replays what already happened first). Ends after `done` or `failed`.
 * Throws like `askNews`: `HttpError` before the first event,
 * `ContractError` for a malformed event, `NetworkError` if the stream
 * breaks; aborting `signal` rejects with the abort error.
 */
export async function* runEvents(
  runId: number,
  {client = apiClient, signal}: CallOptions = {},
): AsyncGenerator<RunEvent, void, undefined> {
  const endpoint = `GET /runs/${runId}/events`;
  const body = await client.stream({path: `/runs/${runId}/events`, signal});
  const events = readSse(body);
  try {
    for (;;) {
      let next: IteratorResult<{event: string; data: string}, void>;
      try {
        next = await events.next();
      } catch (error: unknown) {
        if (signal?.aborted === true) {
          throw error;
        }
        throw new NetworkError(endpoint, 'offline');
      }
      signal?.throwIfAborted();
      if (next.done === true) {
        return;
      }
      const event = toRunEvent(endpoint, next.value.event, next.value.data);
      if (event === undefined) {
        continue;
      }
      yield event;
      if (event.type === 'done' || event.type === 'failed') {
        return;
      }
    }
  } finally {
    await events.return(undefined);
  }
}

function toRunEvent(
  endpoint: string,
  name: string,
  data: string,
): RunEvent | undefined {
  switch (name) {
    case 'run.started': {
      const started = parseEvent(endpoint, name, data, runStartedWireSchema);
      return {type: 'started', total: started.total};
    }
    case 'item': {
      const item = parseEvent(endpoint, name, data, runItemWireSchema);
      return {
        type: 'item',
        newsId: item.news_id,
        vendorItemId: item.vendor_item_id,
        verdict: item.verdict,
        review: item.review ?? false,
        failed: item.failed ?? false,
        done: item.done,
        total: item.total,
      };
    }
    case 'review': {
      const review = parseEvent(endpoint, name, data, runReviewWireSchema);
      return {type: 'review', newsId: review.news_id};
    }
    case 'run.done': {
      const done = parseEvent(endpoint, name, data, runDoneWireSchema);
      return {type: 'done', pendingReview: done.pending_review};
    }
    case 'run.failed': {
      const failed = parseEvent(endpoint, name, data, runFailedWireSchema);
      return {type: 'failed', error: failed.error ?? 'The run failed.'};
    }
    default:
      // A later version may add events; this one doesn't know them.
      return undefined;
  }
}

/** One event's JSON `data`, checked against its schema. */
function parseEvent<T>(
  endpoint: string,
  event: string,
  data: string,
  schema: z.ZodType<T>,
): T {
  let json: unknown;
  try {
    json = JSON.parse(data) as unknown;
  } catch {
    console.error(`Unexpected ${event} event from ${endpoint}: not JSON`);
    throw new ContractError(endpoint, event, 'not JSON');
  }
  const result = schema.safeParse(json);
  if (result.success) {
    return result.data;
  }
  const issue = result.error.issues[0];
  const path = [event, ...(issue?.path ?? [])].join('.');
  const problem = issue?.message ?? 'invalid event';
  console.error(
    `Unexpected response from ${endpoint} at "${path}": ${problem}`,
    result.error.issues,
  );
  throw new ContractError(endpoint, path, problem);
}
