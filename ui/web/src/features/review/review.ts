import type {Role} from '@/api/schemas/auth';
import type {Verdict} from '@/api/schemas/news';
import {COMMENT_MAX_CHARS, COMMENT_MIN_CHARS} from '@/api/schemas/verify';
import {HttpError, errorMessage} from '@/api/errors';
import {isIsoDate} from '@/lib/time';

/**
 * The review queue's rules (increment 4): who may review, what a valid
 * decision is, and the messages. The backend enforces the same rules.
 */

/** The roles that see the review queue and may start verify runs. */
export const REVIEW_ROLES: readonly Role[] = ['ANALYST', 'ADMIN'];

export function canReview(role: Role | undefined): boolean {
  return role !== undefined && REVIEW_ROLES.includes(role);
}

/** The queue's date from `?date=`, else today in New York. */
export function reviewDate(params: URLSearchParams, today: string): string {
  const date = params.get('date');
  return date !== null && isIsoDate(date) && date <= today ? date : today;
}

/** An override form's problem, or undefined when it can be sent. */
export function overrideProblem(
  verdict: Verdict | '',
  comment: string,
): string | undefined {
  if (verdict === '') {
    return 'Choose the new verdict.';
  }
  const text = comment.trim();
  if (text.length < COMMENT_MIN_CHARS) {
    return 'Say why you change the verdict (at least 3 characters).';
  }
  if (comment.length > COMMENT_MAX_CHARS) {
    return `Keep the comment under ${COMMENT_MAX_CHARS} characters.`;
  }
  return undefined;
}

/** What a failed decision shows. */
export function decisionErrorMessage(error: unknown): string {
  if (error instanceof HttpError && error.status === 409) {
    return 'Someone reviewed this item already. The queue has been updated.';
  }
  if (error instanceof HttpError && error.status === 404) {
    return 'This review task no longer exists. The queue has been updated.';
  }
  return errorMessage(error);
}

/** What a failed "Verify this date" shows. */
export function startRunErrorMessage(error: unknown): string {
  if (error instanceof HttpError && error.status === 409) {
    const detail = typeof error.detail === 'string' ? error.detail : '';
    return detail === ''
      ? "This date can't be verified right now."
      : `Can't start: ${detail}.`;
  }
  return errorMessage(error);
}
