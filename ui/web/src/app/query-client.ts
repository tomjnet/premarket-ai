import {QueryClient} from '@tanstack/react-query';

import {HttpError, NetworkError} from '@/api/errors';

/**
 * Retry a failed query once, and only when trying again can help: network
 * failures, timeouts and 5xx. A 4xx, a contract error or an expired session
 * won't change on a retry.
 */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= 1) {
    return false;
  }
  return (
    error instanceof NetworkError ||
    (error instanceof HttpError && error.status >= 500)
  );
}

/** The app's TanStack Query client. Tests pass `retry: false`. */
export function createQueryClient({retry = true} = {}): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: retry ? shouldRetry : false,
        // The feed polls on its own schedule; a tab switch shouldn't refetch.
        refetchOnWindowFocus: false,
      },
      mutations: {retry: false},
    },
  });
}
