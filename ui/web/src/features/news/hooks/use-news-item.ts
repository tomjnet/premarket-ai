import {skipToken, useQuery} from '@tanstack/react-query';

import {getNewsItem} from '@/api/news';
import {useSession} from '@/features/auth/session-context';

import {newsKeys} from '../query-keys';

/**
 * `GET /news/{id}`. `id` is undefined when the URL's id isn't a number: no
 * request is sent, and the page shows "doesn't exist" directly.
 */
export function useNewsItem(id: number | undefined) {
  const {client} = useSession();
  return useQuery({
    queryKey: newsKeys.detail(id),
    queryFn:
      id === undefined
        ? skipToken
        : ({signal}) => getNewsItem(id, {client, signal}),
  });
}
