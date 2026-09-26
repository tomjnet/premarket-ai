import {HttpResponse, delay, http} from 'msw';

import {QUESTION_MAX_CHARS, QUESTION_MIN_CHARS} from '@/api/schemas/chat';
import type {ValidationIssue} from '@/api/schemas/errors';
import {apiUrl} from '@/lib/env';
import {isIsoDate} from '@/lib/time';

import {mockAnswer} from '../data/chat';
import {db} from '../data/db';
import {activeScenario} from '../scenarios';

import {
  rejectUnauthenticated,
  requestUser,
  scenarioLatency,
  validationError,
} from './common';

export const CHAT_BUSY = 'Another question of yours is still being answered';
export const CHAT_OFF = 'Ask the News is not configured';
export const CHAT_FAILED = 'The answer failed. Try again in a moment.';
/** `chat-error`: tokens streamed before the answer fails. */
export const CHAT_ERROR_AFTER_TOKENS = 5;

/** `POST /chat`: "Ask the News", streamed as server-sent events. */
export const chatHandlers = [
  http.post(apiUrl('/chat'), async ({request}) => {
    await scenarioLatency();
    const denied = rejectUnauthenticated(request);
    if (denied !== undefined) {
      return denied;
    }
    const username = requestUser(request) ?? '';
    // FastAPI validates the body before the route runs.
    const parsed = await readQuestion(request);
    if ('issue' in parsed) {
      return validationError(parsed.issue);
    }
    const scenario = activeScenario();
    if (scenario === 'chat-unavailable') {
      return HttpResponse.json({detail: CHAT_OFF}, {status: 503});
    }
    if (scenario === 'chat-busy' || db.chatsInFlight.has(username)) {
      return HttpResponse.json({detail: CHAT_BUSY}, {status: 429});
    }
    const date = parsed.date ?? db.today();
    const answer = mockAnswer(parsed.question, db.day(date).items, date);
    const events: Array<[string, unknown]> = [['sources', answer.sources]];
    const tokens =
      scenario === 'chat-error'
        ? answer.tokens.slice(0, CHAT_ERROR_AFTER_TOKENS)
        : answer.tokens;
    for (const text of tokens) {
      events.push(['token', {text}]);
    }
    events.push(
      scenario === 'chat-error'
        ? ['error', {detail: CHAT_FAILED}]
        : ['done', answer.done],
    );
    db.chatsInFlight.add(username);
    return new HttpResponse(eventStream(events, username), {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
      },
    });
  }),
];

/**
 * The events as a byte stream, one token every `db.chatTokenDelayMs`.
 * Each event is sent in two chunks split mid-line, like a network may
 * split it, so the client's parser must join them. The user's slot is
 * freed when the stream ends or the client cancels it.
 */
function eventStream(
  events: ReadonlyArray<[string, unknown]>,
  username: string,
): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let cancelled = false;
  return new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        for (const [name, data] of events) {
          if (cancelled) {
            return;
          }
          if (name === 'token' && db.chatTokenDelayMs > 0) {
            await delay(db.chatTokenDelayMs);
          }
          const text = `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
          const middle = Math.floor(text.length / 2);
          controller.enqueue(encoder.encode(text.slice(0, middle)));
          controller.enqueue(encoder.encode(text.slice(middle)));
        }
        controller.close();
      } finally {
        db.chatsInFlight.delete(username);
      }
    },
    cancel() {
      cancelled = true;
      db.chatsInFlight.delete(username);
    },
  });
}

type ParsedQuestion =
  {question: string; date?: string} | {issue: ValidationIssue};

/** The JSON body, checked like FastAPI's `ChatIn` model. */
async function readQuestion(request: Request): Promise<ParsedQuestion> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return {
      issue: {loc: ['body'], msg: 'JSON decode error', type: 'json_invalid'},
    };
  }
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    return {
      issue: {
        loc: ['body'],
        msg: 'Input should be a valid dictionary',
        type: 'model_attributes_type',
      },
    };
  }
  const fields: Record<string, unknown> = {...body};
  const extra = Object.keys(fields).find(
    key => key !== 'question' && key !== 'date',
  );
  if (extra !== undefined) {
    return {
      issue: {
        loc: ['body', extra],
        msg: 'Extra inputs are not permitted',
        type: 'extra_forbidden',
      },
    };
  }
  const question = fields.question;
  if (question === undefined) {
    return {
      issue: {
        loc: ['body', 'question'],
        msg: 'Field required',
        type: 'missing',
      },
    };
  }
  if (typeof question !== 'string') {
    return {
      issue: {
        loc: ['body', 'question'],
        msg: 'Input should be a valid string',
        type: 'string_type',
      },
    };
  }
  // Pydantic counts characters (code points).
  const length = [...question].length;
  if (length < QUESTION_MIN_CHARS) {
    return {
      issue: {
        loc: ['body', 'question'],
        msg: `String should have at least ${QUESTION_MIN_CHARS} characters`,
        type: 'string_too_short',
      },
    };
  }
  if (length > QUESTION_MAX_CHARS) {
    return {
      issue: {
        loc: ['body', 'question'],
        msg: `String should have at most ${QUESTION_MAX_CHARS} characters`,
        type: 'string_too_long',
      },
    };
  }
  const date = fields.date;
  if (date === undefined || date === null) {
    return {question};
  }
  if (typeof date !== 'string' || !isIsoDate(date)) {
    return {
      issue: {
        loc: ['body', 'date'],
        msg: 'Input should be a valid date in the format YYYY-MM-DD',
        type: 'date_from_datetime_parsing',
      },
    };
  }
  return {question, date};
}
