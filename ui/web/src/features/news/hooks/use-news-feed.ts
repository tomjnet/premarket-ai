import {useQuery} from '@tanstack/react-query';

import {getNews} from '@/api/news';
import type {NewsFilters} from '@/api/news';
import type {NewsList} from '@/api/schemas/news';
import {useSession} from '@/features/auth/session-context';

import type {FeedFilters} from '../feed';
import {newsKeys} from '../query-keys';

/** While a run is still arriving, the feed polls this often. */
export const FEED_POLL_MS = 30_000;

/** Poll only while the ingest, rule-check or AI run is `RUNNING`. */
export function feedRefetchInterval(
  list: NewsList | undefined,
): number | false {
  const running =
    list?.run?.status === 'RUNNING' ||
    list?.ruleRun?.status === 'RUNNING' ||
    list?.aiRun?.status === 'RUNNING';
  return running ? FEED_POLL_MS : false;
}

/**
 * `GET /news` for the filters. "Flagged only" is applied by the page to
 * this list, so it is not part of the request or the query key.
 */
export function useNewsFeed(filters: FeedFilters) {
  const {client} = useSession();
  const request: NewsFilters = {
    date: filters.date,
    ticker: filters.ticker,
    q: filters.q,
    includeDuplicates: filters.dups,
  };
  return useQuery({
    queryKey: newsKeys.list(request),
    queryFn: ({signal}) => getNews(request, {client, signal}),
    // While another filter of the same date loads, keep the current list on
    // screen; a different date never shows the previous date's items.
    placeholderData: previous =>
      previous?.date === filters.date ? previous : undefined,
    refetchInterval: query => feedRefetchInterval(query.state.data),
  });
}
