import {useQuery} from '@tanstack/react-query';

import {getNews} from '@/api/news';
import type {NewsList} from '@/api/schemas/news';
import {useSession} from '@/features/auth/session-context';

import type {FeedFilters} from '../feed';
import {newsKeys} from '../query-keys';

/** While a run is still arriving, the feed polls this often. */
export const FEED_POLL_MS = 30_000;

/** Poll only while the run is `RUNNING`. */
export function feedRefetchInterval(
  list: NewsList | undefined,
): number | false {
  return list?.run?.status === 'RUNNING' ? FEED_POLL_MS : false;
}

/** `GET /news` for the filters. */
export function useNewsFeed(filters: FeedFilters) {
  const {client} = useSession();
  return useQuery({
    queryKey: newsKeys.list(filters),
    queryFn: ({signal}) =>
      getNews(
        {
          date: filters.date,
          ticker: filters.ticker,
          q: filters.q,
          includeDuplicates: filters.dups,
        },
        {client, signal},
      ),
    // While another filter of the same date loads, keep the current list on
    // screen; a different date never shows the previous date's items.
    placeholderData: previous =>
      previous?.date === filters.date ? previous : undefined,
    refetchInterval: query => feedRefetchInterval(query.state.data),
  });
}
