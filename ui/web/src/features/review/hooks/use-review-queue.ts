import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';

import type {ReviewDecision} from '@/api/schemas/verify';
import {decideReview, getReviewQueue} from '@/api/verify';
import {useSession} from '@/features/auth/session-context';
import {newsKeys} from '@/features/news/query-keys';

import {reviewKeys} from '../query-keys';

/** The pending review tasks of a date, highest market impact first. */
export function useReviewQueue(date: string) {
  const {client} = useSession();
  return useQuery({
    queryKey: reviewKeys.queue(date),
    queryFn: ({signal}) =>
      getReviewQueue({date, status: 'PENDING'}, {client, signal}),
  });
}

/**
 * Approve or override one task. Afterwards (also after a 409: someone else
 * decided) the queue and the news are fetched again.
 */
export function useDecideReview(date: string) {
  const {client} = useSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({id, decision}: {id: number; decision: ReviewDecision}) =>
      decideReview(id, decision, {client}),
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({queryKey: reviewKeys.queue(date)}),
        queryClient.invalidateQueries({queryKey: newsKeys.all}),
      ]);
    },
  });
}
