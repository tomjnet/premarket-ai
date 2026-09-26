import type {NewsFilters} from '@/api/news';

/** TanStack Query keys of the news feature, built in one place. */
export const newsKeys = {
  all: ['news'] as const,
  list: (filters: NewsFilters) => ['news', 'list', filters] as const,
  detail: (id: number | undefined) => ['news', 'detail', id] as const,
};
