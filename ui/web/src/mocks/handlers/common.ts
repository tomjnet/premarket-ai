import {HttpResponse, delay} from 'msw';

import type {ValidationIssue} from '@/api/schemas/errors';

import {db} from '../data/db';
import {scenarioLatencyMs, takeForcedExpiry} from '../scenarios';

/** Waits as long as the active scenario says (2–3 s in `slow`). */
export async function scenarioLatency(): Promise<void> {
  const ms = scenarioLatencyMs();
  if (ms > 0) {
    await delay(ms);
  }
}

/** FastAPI's `401`, with `WWW-Authenticate: Bearer`. */
export function unauthorized(detail = 'Not authenticated'): Response {
  return HttpResponse.json(
    {detail},
    {status: 401, headers: {'WWW-Authenticate': 'Bearer'}},
  );
}

/** FastAPI's `422` for one invalid parameter. */
export function validationError(issue: ValidationIssue): Response {
  return HttpResponse.json({detail: [issue]}, {status: 422});
}

export function notFound(): Response {
  return HttpResponse.json({detail: 'Not found'}, {status: 404});
}

/** Starlette's default `500`: plain text, not JSON. */
export function serverError(): Response {
  return new HttpResponse('Internal Server Error', {
    status: 500,
    headers: {'Content-Type': 'text/plain'},
  });
}

/**
 * A `401` response when the request has no valid bearer token (or the
 * `expired-session` scenario expires it), undefined when it may go on.
 */
export function rejectUnauthenticated(request: Request): Response | undefined {
  const header = request.headers.get('Authorization') ?? '';
  const token = header.startsWith('Bearer ') ? header.slice(7) : '';
  if (takeForcedExpiry() || db.userForToken(token) === undefined) {
    return unauthorized();
  }
  return undefined;
}
