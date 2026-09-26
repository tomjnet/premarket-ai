import {z} from 'zod';

import {isIsoDate} from '@/lib/time';

/**
 * "Ask the News" (`POST /chat`, increment 3). The answer comes as
 * server-sent events: `sources`, then `token`s, then `done` (or `error`).
 * Each event's `data` is JSON, parsed with one of these schemas.
 */

export const QUESTION_MIN_CHARS = 3;
export const QUESTION_MAX_CHARS = 500;

const isoDateSchema = z.string().refine(isIsoDate, 'Expected YYYY-MM-DD');

/** Where a source comes from. Everything but `vendor` is trusted. */
export const sourceKindSchema = z.enum([
  'edgar_8k',
  'edgar_ex99',
  'xbrl_facts',
  'fed_press',
  'sec_press',
  'vendor',
]);

/** Wire format of one numbered source of an answer. */
export const chatSourceWireSchema = z.object({
  n: z.number().int().positive(),
  kind: sourceKindSchema,
  trusted: z.boolean(),
  title: z.string(),
  // An absolute https URL for trusted sources; `/news/<id>` for vendor ones.
  url: z.string(),
  published_at: isoDateSchema.nullable(),
  ticker: z.string().nullable(),
  snippet: z.string(),
});

/** `event: sources`. */
export const chatSourcesWireSchema = z.object({
  sources: z.array(chatSourceWireSchema),
  reranked: z.boolean(),
});

/** `event: token`: more answer text, appended in order. */
export const chatTokenWireSchema = z.object({
  text: z.string(),
});

/** `event: done`: the checked answer, which replaces the streamed text. */
export const chatDoneWireSchema = z.object({
  answer: z.string(),
  citations: z.array(z.number().int().positive()),
  cites_trusted: z.boolean(),
  refused: z.boolean(),
  injection_flagged: z.boolean(),
  model: z.string(),
  prompt_version: z.string(),
  elapsed_ms: z.number().int().nonnegative(),
});

/** `event: error`: the answer failed after the stream started. */
export const chatErrorWireSchema = z.object({
  detail: z.string(),
});

export const chatSourcesSchema = chatSourcesWireSchema.transform(wire => ({
  sources: wire.sources.map(source => ({
    n: source.n,
    kind: source.kind,
    trusted: source.trusted,
    title: source.title,
    url: source.url,
    publishedAt: source.published_at,
    ticker: source.ticker,
    snippet: source.snippet,
  })),
  reranked: wire.reranked,
}));

export const chatDoneSchema = chatDoneWireSchema.transform(wire => ({
  answer: wire.answer,
  citations: wire.citations,
  citesTrusted: wire.cites_trusted,
  refused: wire.refused,
  injectionFlagged: wire.injection_flagged,
  model: wire.model,
  promptVersion: wire.prompt_version,
  elapsedMs: wire.elapsed_ms,
}));

export type SourceKind = z.infer<typeof sourceKindSchema>;
export type ChatSources = z.output<typeof chatSourcesSchema>;
export type ChatSource = ChatSources['sources'][number];
export type ChatDone = z.output<typeof chatDoneSchema>;
export type ChatSourceWire = z.infer<typeof chatSourceWireSchema>;
export type ChatSourcesWire = z.infer<typeof chatSourcesWireSchema>;
export type ChatDoneWire = z.infer<typeof chatDoneWireSchema>;

/** One event of the answer stream, as the UI uses it. */
export type ChatEvent =
  | {type: 'sources'; data: ChatSources}
  | {type: 'token'; text: string}
  | {type: 'done'; data: ChatDone}
  | {type: 'error'; detail: string};
