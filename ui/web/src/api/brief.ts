import type {z} from 'zod';

import {apiClient} from './client';
import type {CallOptions} from './client';
import {ContractError, NetworkError} from './errors';
import {
  briefErrorWireSchema,
  briefMetaSchema,
  briefSchema,
  briefSectionsWireSchema,
  briefStatusEventWireSchema,
  watchlistSchema,
} from './schemas/brief';
import type {
  BriefEdition,
  BriefEvent,
  BriefMeta,
  Watchlist,
} from './schemas/brief';
import {readSse} from './sse';

/**
 * The pre-market brief and the watchlist (increment 5).
 */

/**
 * `GET /briefs/today?date=`: the date's brief as it arrives (`brief`, then
 * `status` / `sections` while it is written, then `done` or `error`).
 * Throws like `askNews`: `HttpError` before the first event (404 when the
 * date has no brief yet), `ContractError` for a malformed event,
 * `NetworkError` if the stream breaks; aborting `signal` rejects with the
 * abort error. Unknown event names are skipped.
 */
export async function* todayBrief(
  date: string,
  {client = apiClient, signal}: CallOptions = {},
): AsyncGenerator<BriefEvent, void, undefined> {
  const endpoint = 'GET /briefs/today';
  const body = await client.stream({
    path: '/briefs/today',
    query: {date},
    signal,
  });
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
      const event = toBriefEvent(endpoint, next.value.event, next.value.data);
      if (event === undefined) {
        continue;
      }
      yield event;
      if (event.type === 'done' || event.type === 'error') {
        return;
      }
    }
  } finally {
    await events.return(undefined);
  }
}

function toBriefEvent(
  endpoint: string,
  name: string,
  data: string,
): BriefEvent | undefined {
  switch (name) {
    case 'brief':
      return {
        type: 'brief',
        data: parseEvent(endpoint, name, data, briefMetaSchema),
      };
    case 'status':
      return {
        type: 'status',
        detail: parseEvent(endpoint, name, data, briefStatusEventWireSchema)
          .detail,
      };
    case 'sections': {
      const {counts} = parseEvent(
        endpoint,
        name,
        data,
        briefSectionsWireSchema,
      );
      return {
        type: 'sections',
        verified: counts.verified,
        unconfirmed: counts.unconfirmed,
        pendingReview: counts.pending_review,
      };
    }
    case 'done':
      return {
        type: 'done',
        data: parseEvent(endpoint, name, data, briefSchema),
      };
    case 'error':
      return {
        type: 'error',
        detail: parseEvent(endpoint, name, data, briefErrorWireSchema).detail,
      };
    default:
      // A later version may add events; this one doesn't know them.
      return undefined;
  }
}

/** `POST /briefs` (ANALYST, ADMIN): write a date's brief now. */
export function writeBrief(
  date: string,
  edition: BriefEdition,
  {client = apiClient, signal}: CallOptions = {},
): Promise<BriefMeta> {
  return client.request({
    method: 'POST',
    path: '/briefs',
    json: {date, edition},
    schema: briefMetaSchema,
    signal,
  });
}

/** `GET /me/watchlist`: the caller's tickers and sectors. */
export function getWatchlist({
  client = apiClient,
  signal,
}: CallOptions = {}): Promise<Watchlist> {
  return client.request({
    path: '/me/watchlist',
    schema: watchlistSchema,
    signal,
  });
}

/** `PUT /me/watchlist`: replaces it. `HttpError` 422 names a bad value. */
export function saveWatchlist(
  watchlist: {tickers: string[]; sectors: string[]},
  {client = apiClient, signal}: CallOptions = {},
): Promise<Watchlist> {
  return client.request({
    method: 'PUT',
    path: '/me/watchlist',
    json: {tickers: watchlist.tickers, sectors: watchlist.sectors},
    schema: watchlistSchema,
    signal,
  });
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
