import {apiClient} from './client';
import type {CallOptions} from './client';
import {newsDetailSchema, newsListSchema} from './schemas/news';
import type {NewsDetail, NewsList} from './schemas/news';

/** The filters of `GET /news`, as the UI holds them. */
export interface NewsFilters {
  /** Trading date, `YYYY-MM-DD`. */
  date: string;
  ticker?: string;
  /** Text search in headline and body. */
  q?: string;
  includeDuplicates?: boolean;
}

/** `GET /news`: the feed of one trading date. */
export function getNews(
  filters: NewsFilters,
  {client = apiClient, signal}: CallOptions = {},
): Promise<NewsList> {
  return client.request({
    path: '/news',
    query: {
      date: filters.date,
      ticker: filters.ticker,
      q: filters.q,
      include_duplicates:
        filters.includeDuplicates === undefined
          ? undefined
          : String(filters.includeDuplicates),
    },
    schema: newsListSchema,
    signal,
  });
}

/** `GET /news/{id}`: one item with its body. `HttpError` 404 if unknown. */
export function getNewsItem(
  id: number,
  {client = apiClient, signal}: CallOptions = {},
): Promise<NewsDetail> {
  return client.request({
    path: `/news/${id}`,
    schema: newsDetailSchema,
    signal,
  });
}
