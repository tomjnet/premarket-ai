import type {FeedFilters} from './feed';

/** TanStack Query keys of the news feature, built in one place. */
export const newsKeys = {
  all: ['news'] as const,
  list: (filters: FeedFilters) => ['news', 'list', filters] as const,
  detail: (id: number) => ['news', 'detail', id] as const,
};
