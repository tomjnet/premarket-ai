/**
 * A server-sent events reader for `fetch` responses. `EventSource` can't
 * send a POST body or an `Authorization` header, so `POST /chat` is read
 * with fetch and parsed here, following the WHATWG event-stream rules:
 * lines end with LF, CR or CRLF; a blank line dispatches the event; `data`
 * lines are joined with LF; lines starting with `:` are comments.
 */

/** One dispatched event. `event` is `message` when the stream names none. */
export interface SseEvent {
  event: string;
  data: string;
}

/**
 * Incremental parser: feed it text in any pieces (chunk boundaries may
 * split a line, or a CRLF), and it returns the events completed so far.
 */
export class SseParser {
  private buffer = '';
  private eventName = '';
  private dataLines: string[] = [];

  /** Adds text; returns the events it completed. */
  push(text: string): SseEvent[] {
    this.buffer += text;
    const events: SseEvent[] = [];
    let start = 0;
    for (let i = 0; i < this.buffer.length; i++) {
      const char = this.buffer[i];
      if (char !== '\n' && char !== '\r') {
        continue;
      }
      if (char === '\r' && i === this.buffer.length - 1) {
        // A CR at the end may be the first half of a CRLF: wait for more.
        break;
      }
      const line = this.buffer.slice(start, i);
      if (char === '\r' && this.buffer[i + 1] === '\n') {
        i += 1;
      }
      start = i + 1;
      const event = this.line(line);
      if (event !== undefined) {
        events.push(event);
      }
    }
    this.buffer = this.buffer.slice(start);
    return events;
  }

  /**
   * The end of the stream. A trailing CR ends its line; an event without
   * its blank line is dropped, as the standard says.
   */
  end(): SseEvent[] {
    const events: SseEvent[] = [];
    if (this.buffer.endsWith('\r')) {
      const event = this.line(this.buffer.slice(0, -1));
      if (event !== undefined) {
        events.push(event);
      }
    }
    this.buffer = '';
    this.eventName = '';
    this.dataLines = [];
    return events;
  }

  private line(line: string): SseEvent | undefined {
    if (line === '') {
      return this.dispatch();
    }
    if (line.startsWith(':')) {
      return undefined;
    }
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) {
      value = value.slice(1);
    }
    if (field === 'event') {
      this.eventName = value;
    } else if (field === 'data') {
      this.dataLines.push(value);
    }
    // `id` and `retry` only matter to EventSource reconnects: ignored.
    return undefined;
  }

  private dispatch(): SseEvent | undefined {
    const name = this.eventName;
    const lines = this.dataLines;
    this.eventName = '';
    this.dataLines = [];
    if (lines.length === 0) {
      return undefined;
    }
    return {event: name === '' ? 'message' : name, data: lines.join('\n')};
  }
}

/**
 * The events of a response body, as they arrive. Stops when the stream
 * ends; a read error (network, abort) is thrown as is.
 */
export async function* readSse(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SseEvent, void, undefined> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    for (;;) {
      const {done, value} = await reader.read();
      if (done) {
        break;
      }
      yield* parser.push(decoder.decode(value, {stream: true}));
    }
    yield* parser.push(decoder.decode());
    yield* parser.end();
  } finally {
    // Stops the download when the caller stops early (cancel, error).
    reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
