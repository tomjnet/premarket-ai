import {describe, expect, it} from 'vitest';

import {SseParser, readSse} from './sse';
import type {SseEvent} from './sse';

const STREAM =
  'event: sources\ndata: {"sources": [], "reranked": true}\n\n' +
  ': a comment\n' +
  'event: token\ndata: {"text": "Apple [1]"}\n\n' +
  'event: done\r\ndata: {"answer": "x",\r\ndata: "citations": []}\r\n\r\n';

const EXPECTED: SseEvent[] = [
  {event: 'sources', data: '{"sources": [], "reranked": true}'},
  {event: 'token', data: '{"text": "Apple [1]"}'},
  {event: 'done', data: '{"answer": "x",\n"citations": []}'},
];

function parseInPieces(text: string, sizes: number[]): SseEvent[] {
  const parser = new SseParser();
  const events: SseEvent[] = [];
  let start = 0;
  let i = 0;
  while (start < text.length) {
    const size = sizes[i % sizes.length] ?? 1;
    events.push(...parser.push(text.slice(start, start + size)));
    start += size;
    i += 1;
  }
  events.push(...parser.end());
  return events;
}

function streamOf(chunks: readonly Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(chunk);
      }
      controller.close();
    },
  });
}

async function collect(body: ReadableStream<Uint8Array>): Promise<SseEvent[]> {
  const events: SseEvent[] = [];
  for await (const event of readSse(body)) {
    events.push(event);
  }
  return events;
}

describe('SseParser', () => {
  it('parses events, joins data lines and skips comments', () => {
    expect(parseInPieces(STREAM, [STREAM.length])).toEqual(EXPECTED);
  });

  it('gives the same events whatever the chunk boundaries', () => {
    // Every split point, including inside "\r\n" and inside a field name.
    for (let size = 1; size <= 12; size++) {
      expect(parseInPieces(STREAM, [size])).toEqual(EXPECTED);
    }
    expect(parseInPieces(STREAM, [3, 1, 7, 2, 5])).toEqual(EXPECTED);
  });

  it('treats a lone CR as a line end, also at the very end', () => {
    expect(parseInPieces('data: a\r\rdata: b\r\r', [1])).toEqual([
      {event: 'message', data: 'a'},
      {event: 'message', data: 'b'},
    ]);
  });

  it('drops an event without its blank line, and data-less events', () => {
    expect(parseInPieces('event: token\n\ndata: cut', [4])).toEqual([]);
  });

  it('reads field values without a space, or with none at all', () => {
    expect(parseInPieces('event:done\ndata\ndata:x\n\n', [2])).toEqual([
      {event: 'done', data: '\nx'},
    ]);
  });
});

describe('readSse', () => {
  it('decodes UTF-8 split across chunks', async () => {
    const bytes = new TextEncoder().encode(
      'event: token\ndata: {"text": "東京 📈"}\n\n',
    );
    // Split every 1–3 bytes: multi-byte characters are cut in half.
    const chunks: Uint8Array[] = [];
    for (let start = 0, size = 1; start < bytes.length; size = (size % 3) + 1) {
      chunks.push(bytes.slice(start, start + size));
      start += size;
    }
    expect(await collect(streamOf(chunks))).toEqual([
      {event: 'token', data: '{"text": "東京 📈"}'},
    ]);
  });

  it('stops reading when the caller stops early', async () => {
    let cancelled = false;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('data: 1\n\ndata: 2\n\n'));
      },
      cancel() {
        cancelled = true;
      },
    });
    for await (const event of readSse(body)) {
      expect(event.data).toBe('1');
      break;
    }
    expect(cancelled).toBe(true);
  });
});
