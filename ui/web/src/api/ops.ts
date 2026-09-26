import {z} from 'zod';

import {apiClient} from './client';
import type {CallOptions} from './client';
import {ContractError, NetworkError} from './errors';
import {
  adminLlmSchema,
  adminSourceListSchema,
  adminSourceSchema,
  adminUserListSchema,
  adminUserSchema,
  alertListSchema,
  alertSnapshotWireSchema,
  alertWireSchema,
  budgetSchema,
  scheduleSchema,
  scorecardSchema,
  scorecardSummarySchema,
} from './schemas/ops';
import type {
  AdminLlm,
  AdminSource,
  AdminUser,
  Alert,
  Budget,
  CloudSwitches,
  Schedule,
  Scorecard,
  ScorecardSummary,
  Tier,
} from './schemas/ops';
import type {Role} from './schemas/auth';
import {readSse} from './sse';

/**
 * Production (increment 6): the banners, the scheduler's day, the vendor
 * scorecard and the ADMIN pages.
 */

/** `GET /llm/budget` (every role): the month's cloud spend. */
export function getBudget({
  client = apiClient,
  signal,
}: CallOptions = {}): Promise<Budget> {
  return client.request({path: '/llm/budget', schema: budgetSchema, signal});
}

/** `GET /alerts` (ANALYST, ADMIN): the alerts firing now. */
export function getAlerts({
  client = apiClient,
  signal,
}: CallOptions = {}): Promise<Alert[]> {
  return client.request({path: '/alerts', schema: alertListSchema, signal});
}

/** One event of the banner's stream. */
export type AlertEvent =
  {type: 'snapshot'; alerts: Alert[]} | {type: 'alert'; alert: Alert};

/**
 * `GET /alerts/stream` (ANALYST, ADMIN): a `snapshot` of the firing alerts,
 * then every new alert event. Ends when the server closes it (after an
 * hour); the caller reconnects. Throws `HttpError` before the first event,
 * `ContractError` for a malformed one, `NetworkError` if it breaks.
 */
export async function* alertStream({
  client = apiClient,
  signal,
}: CallOptions = {}): AsyncGenerator<AlertEvent, void, undefined> {
  const endpoint = 'GET /alerts/stream';
  const body = await client.stream({path: '/alerts/stream', signal});
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
      const {event, data} = next.value;
      if (event === 'snapshot') {
        const snapshot = parse(endpoint, event, data, alertSnapshotWireSchema);
        yield {type: 'snapshot', alerts: snapshot.items};
      } else if (event === 'alert') {
        yield {
          type: 'alert',
          alert: parse(endpoint, event, data, alertWireSchema),
        };
      }
      // Unknown events (a later version) are skipped.
    }
  } finally {
    await events.return(undefined);
  }
}

function parse<T>(
  endpoint: string,
  event: string,
  data: string,
  schema: z.ZodType<T>,
): T {
  let json: unknown;
  try {
    json = JSON.parse(data) as unknown;
  } catch {
    throw new ContractError(endpoint, event, 'not JSON');
  }
  const result = schema.safeParse(json);
  if (result.success) {
    return result.data;
  }
  const issue = result.error.issues[0];
  const path = [event, ...(issue?.path ?? [])].join('.');
  console.error(`Unexpected response from ${endpoint} at "${path}"`);
  throw new ContractError(endpoint, path, issue?.message ?? 'invalid event');
}

/** `GET /schedule?date=` (ANALYST, ADMIN): the day's jobs and SLA checks. */
export function getSchedule(
  date: string,
  {client = apiClient, signal}: CallOptions = {},
): Promise<Schedule> {
  return client.request({
    path: '/schedule',
    query: {date},
    schema: scheduleSchema,
    signal,
  });
}

/** `GET /vendor/scorecard` (ANALYST, ADMIN): days newest first. */
export function getScorecard(
  days: number,
  {client = apiClient, signal}: CallOptions = {},
): Promise<Scorecard> {
  return client.request({
    path: '/vendor/scorecard',
    query: {days: String(days)},
    schema: scorecardSchema,
    signal,
  });
}

/** `GET /vendor/scorecard.csv`: the same rows as CSV text. */
export function getScorecardCsv(
  days: number,
  {client = apiClient, signal}: CallOptions = {},
): Promise<string> {
  return client.request({
    path: '/vendor/scorecard.csv',
    query: {days: String(days)},
    schema: z.string(),
    signal,
  });
}

/** `GET /vendor/scorecard/summary`: the weekly summary. */
export function getScorecardSummary({
  client = apiClient,
  signal,
}: CallOptions = {}): Promise<ScorecardSummary> {
  return client.request({
    path: '/vendor/scorecard/summary',
    query: {days: '7'},
    schema: scorecardSummarySchema,
    signal,
  });
}

// --- admin -------------------------------------------------------------------

export function getUsers({
  client = apiClient,
  signal,
}: CallOptions = {}): Promise<AdminUser[]> {
  return client.request({
    path: '/admin/users',
    schema: adminUserListSchema,
    signal,
  });
}

/** `POST /admin/users`. `HttpError` 409 when the name is taken. */
export function createUser(
  user: {username: string; role: Role; password: string},
  {client = apiClient, signal}: CallOptions = {},
): Promise<AdminUser> {
  return client.request({
    method: 'POST',
    path: '/admin/users',
    json: user,
    schema: adminUserSchema,
    signal,
  });
}

/** `POST /admin/users/{username}`: only the fields given change. */
export function updateUser(
  username: string,
  change: {role?: Role; disabled?: boolean; password?: string},
  {client = apiClient, signal}: CallOptions = {},
): Promise<AdminUser> {
  return client.request({
    method: 'POST',
    path: `/admin/users/${encodeURIComponent(username)}`,
    json: change,
    schema: adminUserSchema,
    signal,
  });
}

export function getSources(
  query: string,
  {client = apiClient, signal}: CallOptions = {},
): Promise<AdminSource[]> {
  return client.request({
    path: '/admin/sources',
    query: {q: query === '' ? undefined : query},
    schema: adminSourceListSchema,
    signal,
  });
}

/** `POST /admin/sources`: adds a domain or changes it. */
export function saveSource(
  source: {domain: string; tier: Tier; reputation: number; note: string},
  {client = apiClient, signal}: CallOptions = {},
): Promise<AdminSource> {
  return client.request({
    method: 'POST',
    path: '/admin/sources',
    json: source,
    schema: adminSourceSchema,
    signal,
  });
}

export function getLlmSettings({
  client = apiClient,
  signal,
}: CallOptions = {}): Promise<AdminLlm> {
  return client.request({path: '/admin/llm', schema: adminLlmSchema, signal});
}

/** `POST /admin/llm`: sets the cloud switches given. */
export function saveCloudSwitches(
  switches: Partial<CloudSwitches>,
  {client = apiClient, signal}: CallOptions = {},
): Promise<AdminLlm> {
  return client.request({
    method: 'POST',
    path: '/admin/llm',
    json: switches,
    schema: adminLlmSchema,
    signal,
  });
}
