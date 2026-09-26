import {HttpResponse, http} from 'msw';
import {afterEach, beforeEach, describe, expect, it} from 'vitest';

import {apiUrl} from '@/lib/env';
import {db} from '@/mocks/data/db';
import {CHAT_BUSY, CHAT_OFF} from '@/mocks/handlers/chat';
import {server} from '@/mocks/node';
import {setScenario} from '@/mocks/scenarios';

import {login} from './auth';
import {askNews} from './chat';
import type {ChatQuestion} from './chat';
import {ApiClient} from './client';
import {ContractError, HttpError, SessionExpiredError} from './errors';
import type {ChatEvent} from './schemas/chat';

async function loggedIn(): Promise<ApiClient> {
  const client = new ApiClient({baseUrl: '/api'});
  await login('trader1', 'demo', {client});
  return client;
}

async function collect(
  question: ChatQuestion,
  client: ApiClient,
  signal?: AbortSignal,
): Promise<ChatEvent[]> {
  const events: ChatEvent[] = [];
  for await (const event of askNews(question, {client, signal})) {
    events.push(event);
  }
  return events;
}

/** A `POST /chat` answer made of these raw SSE chunks. */
function rawStream(...chunks: string[]) {
  return http.post(apiUrl('/chat'), () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) {
          controller.enqueue(encoder.encode(chunk));
        }
        controller.close();
      },
    });
    return new HttpResponse(body, {
      headers: {'Content-Type': 'text/event-stream; charset=utf-8'},
    });
  });
}

beforeEach(() => {
  db.today = () => '2026-09-25';
  db.chatTokenDelayMs = 0;
});

afterEach(() => {
  server.events.removeAllListeners();
});

describe('askNews', () => {
  it('streams sources, tokens, then the checked answer', async () => {
    const client = await loggedIn();
    let body: unknown;
    server.events.on('request:start', ({request}) => {
      if (request.url.endsWith('/api/chat')) {
        void request
          .clone()
          .json()
          .then(json => {
            body = json;
          });
      }
    });

    const events = await collect(
      {question: 'What did Apple file?', date: '2026-09-25'},
      client,
    );

    expect(body).toEqual({
      question: 'What did Apple file?',
      date: '2026-09-25',
    });
    expect(events[0]?.type).toBe('sources');
    const tokens = events.filter(event => event.type === 'token');
    expect(tokens.length).toBeGreaterThan(5);
    const streamed = tokens.map(event => event.text).join('');
    const last = events.at(-1);
    if (last?.type !== 'done') {
      throw new Error('The stream must end with done');
    }
    // The model cited a source that doesn't exist; done removed it.
    expect(last.data.answer).not.toBe(streamed.trim());
    expect(last.data).toMatchObject({
      citesTrusted: true,
      refused: false,
      injectionFlagged: false,
      model: 'main-gpu4gb',
      promptVersion: 'ask-v1',
    });
    expect(last.data.citations).toEqual([1, 2, 3, 4]);
  });

  it('refreshes once on 401 and retries', async () => {
    const client = await loggedIn();
    setScenario('expired-session');

    const events = await collect({question: 'What is new?'}, client);

    expect(events.at(-1)?.type).toBe('done');
  });

  it('ends the session when refresh fails too', async () => {
    const client = await loggedIn();
    db.logout();

    await expect(collect({question: 'What is new?'}, client)).rejects.toThrow(
      SessionExpiredError,
    );
    expect(client.getSession()).toBeUndefined();
  });

  it('throws HttpError with the detail for 429, 503 and 422', async () => {
    const client = await loggedIn();
    setScenario('chat-busy');
    await expect(collect({question: 'What is new?'}, client)).rejects.toEqual(
      new HttpError('POST /chat', 429, CHAT_BUSY),
    );
    setScenario('chat-unavailable');
    await expect(
      collect({question: 'What is new?'}, client),
    ).rejects.toMatchObject({status: 503, detail: CHAT_OFF});
    setScenario('default');
    await expect(collect({question: 'Hi'}, client)).rejects.toMatchObject({
      status: 422,
    });
  });

  it('allows one question at a time per user', async () => {
    const client = await loggedIn();
    db.chatTokenDelayMs = 20;
    const first = collect({question: 'What did Apple file?'}, client);
    // Let the first request reach the mock before the second one.
    await new Promise(resolve => setTimeout(resolve, 50));

    await expect(
      collect({question: 'And Microsoft?'}, client),
    ).rejects.toMatchObject({status: 429, detail: CHAT_BUSY});
    expect((await first).at(-1)?.type).toBe('done');
    // Once the first answer is done, the next question is answered.
    expect(
      (await collect({question: 'And Microsoft?'}, client)).at(-1)?.type,
    ).toBe('done');
  });

  it('passes an error event on', async () => {
    const client = await loggedIn();
    setScenario('chat-error');

    const events = await collect({question: 'What is new?'}, client);

    expect(events.at(-1)).toEqual({
      type: 'error',
      detail: 'The answer failed. Try again in a moment.',
    });
  });

  it('skips unknown events and rejects events that break the contract', async () => {
    const client = await loggedIn();
    server.use(
      rawStream(
        'event: heartbeat\ndata: {}\n\n',
        'event: tok',
        'en\ndata: {"text": "Hi"}\n',
        '\nevent: token\ndata: {"text": 42}\n\n',
      ),
    );

    const events: ChatEvent[] = [];
    await expect(async () => {
      for await (const event of askNews({question: 'Hi there'}, {client})) {
        events.push(event);
      }
    }).rejects.toThrow(ContractError);
    expect(events).toEqual([{type: 'token', text: 'Hi'}]);
  });

  it('rejects a 200 that is not an event stream', async () => {
    const client = await loggedIn();
    server.use(http.post(apiUrl('/chat'), () => HttpResponse.json({})));

    await expect(collect({question: 'Hi there'}, client)).rejects.toThrow(
      ContractError,
    );
  });

  it('stops with the abort error when cancelled', async () => {
    const client = await loggedIn();
    db.chatTokenDelayMs = 20;
    const controller = new AbortController();
    const events: ChatEvent[] = [];

    await expect(async () => {
      for await (const event of askNews(
        {question: 'What did Apple file?'},
        {client, signal: controller.signal},
      )) {
        events.push(event);
        if (event.type === 'token') {
          controller.abort();
        }
      }
    }).rejects.toMatchObject({name: 'AbortError'});
    expect(events.some(event => event.type === 'done')).toBe(false);
    // The mock frees the user's slot: a new question is answered.
    db.chatTokenDelayMs = 0;
    await new Promise(resolve => setTimeout(resolve, 50));
    expect((await collect({question: 'Next one'}, client)).at(-1)?.type).toBe(
      'done',
    );
  });
});
