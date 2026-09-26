import type {z} from 'zod';

import {apiClient} from './client';
import type {CallOptions} from './client';
import {ContractError, NetworkError} from './errors';
import {
  chatDoneSchema,
  chatErrorWireSchema,
  chatSourcesSchema,
  chatTokenWireSchema,
} from './schemas/chat';
import type {ChatEvent} from './schemas/chat';
import {readSse} from './sse';

const ENDPOINT = 'POST /chat';

/** One question for "Ask the News". */
export interface ChatQuestion {
  /** 3 to 500 characters. */
  question: string;
  /** The feed date whose vendor items may be cited; default today. */
  date?: string;
}

/**
 * `POST /chat`: the answer's events as they arrive (`sources`, `token`s,
 * then `done` or `error`). Throws `HttpError` (401 after a failed refresh
 * becomes `SessionExpiredError`, 422, 429, 503) before the first event,
 * `ContractError` for an event that doesn't match the contract, and
 * `NetworkError` if the stream breaks. Aborting `signal` rejects with the
 * abort error. Unknown event names are skipped.
 */
export async function* askNews(
  question: ChatQuestion,
  {client = apiClient, signal}: CallOptions = {},
): AsyncGenerator<ChatEvent, void, undefined> {
  const body = await client.stream({
    method: 'POST',
    path: '/chat',
    json:
      question.date === undefined
        ? {question: question.question}
        : {question: question.question, date: question.date},
    signal,
  });
  const events = readSse(body);
  try {
    yield* chatEvents(events, signal);
  } finally {
    // Stops the download when the caller stops reading early.
    await events.return(undefined);
  }
}

async function* chatEvents(
  events: AsyncGenerator<{event: string; data: string}, void, undefined>,
  signal: AbortSignal | undefined,
): AsyncGenerator<ChatEvent, void, undefined> {
  for (;;) {
    let next: IteratorResult<{event: string; data: string}, void>;
    try {
      next = await events.next();
    } catch (error: unknown) {
      if (signal?.aborted === true) {
        throw error;
      }
      throw new NetworkError(ENDPOINT, 'offline');
    }
    // Not every fetch implementation errors the body on abort: stop here.
    signal?.throwIfAborted();
    if (next.done === true) {
      return;
    }
    const {event, data} = next.value;
    switch (event) {
      case 'sources':
        yield {
          type: 'sources',
          data: parseEvent(event, data, chatSourcesSchema),
        };
        break;
      case 'token':
        yield {
          type: 'token',
          text: parseEvent(event, data, chatTokenWireSchema).text,
        };
        break;
      case 'done':
        yield {type: 'done', data: parseEvent(event, data, chatDoneSchema)};
        break;
      case 'error':
        yield {
          type: 'error',
          detail: parseEvent(event, data, chatErrorWireSchema).detail,
        };
        break;
      default:
        // A later version may add events; this one doesn't know them.
        break;
    }
  }
}

/** One event's JSON `data`, checked against its schema. */
function parseEvent<T>(event: string, data: string, schema: z.ZodType<T>): T {
  let json: unknown;
  try {
    json = JSON.parse(data) as unknown;
  } catch {
    console.error(`Unexpected ${event} event from ${ENDPOINT}: not JSON`);
    throw new ContractError(ENDPOINT, event, 'not JSON');
  }
  const result = schema.safeParse(json);
  if (result.success) {
    return result.data;
  }
  const issue = result.error.issues[0];
  const path = [event, ...(issue?.path ?? [])].join('.');
  const problem = issue?.message ?? 'invalid event';
  console.error(
    `Unexpected response from ${ENDPOINT} at "${path}": ${problem}`,
    result.error.issues,
  );
  throw new ContractError(ENDPOINT, path, problem);
}
