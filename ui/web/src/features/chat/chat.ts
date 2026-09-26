import {HttpError, errorMessage} from '@/api/errors';
import {QUESTION_MAX_CHARS, QUESTION_MIN_CHARS} from '@/api/schemas/chat';
import type {SourceKind} from '@/api/schemas/chat';

/**
 * Pure rules of "Ask the News" (increment 3): citation markers, source
 * labels, question limits and error messages.
 */

/** A piece of an answer: plain text, or a citation of source `n`. */
export type AnswerSegment =
  {kind: 'text'; text: string} | {kind: 'citation'; n: number};

const CITATION = /\[(\d{1,3})\]/g;

/**
 * Splits an answer on its citation markers (`[1]`, `[2][3]`). A marker
 * becomes a citation only if `known` has its number; any other marker stays
 * text. The answer itself is never parsed as HTML or Markdown.
 */
export function answerSegments(
  text: string,
  known: ReadonlySet<number>,
): AnswerSegment[] {
  const segments: AnswerSegment[] = [];
  let pending = '';
  let last = 0;
  for (const match of text.matchAll(CITATION)) {
    const n = Number(match[1]);
    if (!known.has(n)) {
      continue;
    }
    pending += text.slice(last, match.index);
    if (pending !== '') {
      segments.push({kind: 'text', text: pending});
      pending = '';
    }
    segments.push({kind: 'citation', n});
    last = match.index + match[0].length;
  }
  pending += text.slice(last);
  if (pending !== '') {
    segments.push({kind: 'text', text: pending});
  }
  return segments;
}

const KIND_LABEL: Record<SourceKind, string> = {
  edgar_8k: 'SEC filing 8-K',
  edgar_ex99: 'Company press release (EX-99.1)',
  xbrl_facts: 'SEC company facts',
  fed_press: 'Federal Reserve release',
  sec_press: 'SEC release',
  vendor: 'Vendor item (unverified)',
};

/** What a source is, in words: `SEC filing 8-K`. */
export function sourceKindLabel(kind: SourceKind): string {
  return KIND_LABEL[kind];
}

/** The news id of a vendor source's `/news/<id>` link, if it is one. */
export function vendorNewsId(url: string): number | undefined {
  const match = /^\/news\/(\d{1,15})$/.exec(url);
  return match === null ? undefined : Number(match[1]);
}

/** Why a question can't be sent, or undefined when it can. */
export function questionProblem(question: string): string | undefined {
  const length = [...question.trim()].length;
  if (length < QUESTION_MIN_CHARS) {
    return `Write a question of at least ${QUESTION_MIN_CHARS} characters.`;
  }
  if (length > QUESTION_MAX_CHARS) {
    return `Shorten the question to ${QUESTION_MAX_CHARS} characters or less.`;
  }
  return undefined;
}

/** The backend's `429` detail when this user's last answer isn't done. */
export const CHAT_BUSY_DETAIL =
  'Another question of yours is still being answered';

/** A short, plain message for a question that failed before or while
 * streaming. */
export function chatErrorMessage(error: unknown): string {
  if (error instanceof HttpError) {
    if (error.status === 429) {
      return error.detail === CHAT_BUSY_DETAIL
        ? 'Another question of yours is still being answered. Wait for it to finish, then ask again.'
        : 'Too many questions in a short time. Wait a few minutes and try again.';
    }
    if (error.status === 503) {
      return "Ask the News isn't available on this server right now.";
    }
    if (error.status === 422) {
      return `The question must be ${QUESTION_MIN_CHARS} to ${QUESTION_MAX_CHARS} characters.`;
    }
  }
  return errorMessage(error);
}
