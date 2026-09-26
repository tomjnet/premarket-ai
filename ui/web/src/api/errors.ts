import type {ValidationIssue} from './schemas/errors';

/** The backend answered with a non-2xx status. */
export class HttpError extends Error {
  constructor(
    readonly endpoint: string,
    readonly status: number,
    /** FastAPI's `detail`, when the body had one. */
    readonly detail: string | ValidationIssue[] | undefined,
  ) {
    super(`${endpoint} failed with HTTP ${status}`);
    this.name = 'HttpError';
  }
}

/** No answer: the network failed or the request timed out. */
export class NetworkError extends Error {
  constructor(
    readonly endpoint: string,
    readonly reason: 'timeout' | 'offline',
  ) {
    super(`${endpoint} failed: ${reason}`);
    this.name = 'NetworkError';
  }
}

/**
 * The backend answered, but not in the agreed shape (contract drift). The
 * message is what the UI shows; `endpoint` and `path` say what broke.
 */
export class ContractError extends Error {
  constructor(
    readonly endpoint: string,
    /** Where the response differs, for example `items.0.published_at`. */
    readonly path: string,
    readonly problem: string,
  ) {
    super('Unexpected response from the server');
    this.name = 'ContractError';
  }
}

/** A short, plain message for the user; details go to the console. */
export function errorMessage(error: unknown): string {
  if (error instanceof ContractError) {
    return 'Unexpected response from the server.';
  }
  if (error instanceof NetworkError) {
    return error.reason === 'timeout'
      ? 'The server took too long to answer. Try again.'
      : "Can't reach the server. Check your connection and try again.";
  }
  if (error instanceof SessionExpiredError) {
    return error.message;
  }
  if (error instanceof HttpError && error.status === 429) {
    // The edge's rate limit, or ai-api's lockout after failed logins.
    return 'Too many attempts. Wait a few minutes and try again.';
  }
  if (error instanceof HttpError && error.status >= 500) {
    return 'The server had a problem. Try again.';
  }
  return 'Something went wrong. Try again.';
}

/** The session could not be refreshed; the user has to log in again. */
export class SessionExpiredError extends Error {
  constructor() {
    super('Your session expired. Please log in again.');
    this.name = 'SessionExpiredError';
  }
}
