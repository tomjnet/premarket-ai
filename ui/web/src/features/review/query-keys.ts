/** TanStack Query keys of the review feature, built in one place. */
export const reviewKeys = {
  all: ['review'] as const,
  queue: (date: string) => ['review', 'queue', date] as const,
  runs: (date: string) => ['review', 'runs', date] as const,
};
