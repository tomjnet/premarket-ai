import {describe, expect, it} from 'vitest';

import {
  ContractError,
  HttpError,
  NetworkError,
  SessionExpiredError,
  errorMessage,
} from '@/api/errors';

import {shouldRetry} from './query-client';

describe('shouldRetry', () => {
  it('retries network failures and 5xx once', () => {
    expect(shouldRetry(0, new NetworkError('GET /news', 'offline'))).toBe(true);
    expect(shouldRetry(0, new HttpError('GET /news', 503, undefined))).toBe(
      true,
    );
    expect(shouldRetry(1, new NetworkError('GET /news', 'timeout'))).toBe(
      false,
    );
  });

  it('does not retry what a retry cannot fix', () => {
    expect(shouldRetry(0, new HttpError('GET /news/9', 404, 'Not found'))).toBe(
      false,
    );
    expect(shouldRetry(0, new ContractError('GET /news', 'count', 'x'))).toBe(
      false,
    );
    expect(shouldRetry(0, new SessionExpiredError())).toBe(false);
  });
});

describe('errorMessage', () => {
  it('gives each failure a plain message', () => {
    expect(errorMessage(new ContractError('GET /news', 'count', 'x'))).toBe(
      'Unexpected response from the server.',
    );
    expect(errorMessage(new NetworkError('GET /news', 'timeout'))).toBe(
      'The server took too long to answer. Try again.',
    );
    expect(errorMessage(new HttpError('GET /news', 500, undefined))).toBe(
      'The server had a problem. Try again.',
    );
    expect(errorMessage(new SessionExpiredError())).toBe(
      'Your session expired. Please log in again.',
    );
    expect(errorMessage(new Error('?'))).toBe(
      'Something went wrong. Try again.',
    );
  });
});
