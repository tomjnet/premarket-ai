import {useCallback, useMemo, useRef} from 'react';
import {useLocation, useNavigate, useSearchParams} from 'react-router';

import {useDocumentTitle} from '@/components/layout/use-document-title';
import {LoadError} from '@/components/load-error';
import {formatLongDate, todayInNewYork} from '@/lib/time';

import {FeedFiltersBar} from './components/feed-filters-bar';
import {
  AiRunStatus,
  FeedSkeleton,
  NoFeed,
  RuleRunStatus,
  RunStatus,
  VerifyRunStatus,
} from './components/feed-states';
import {NewsRow} from './components/news-row';
import {feedSearch, newestFirst, parseFeedFilters, visibleItems} from './feed';
import type {FeedFilters} from './feed';
import {
  useFeedKeyboard,
  useShortcutsPreference,
} from './hooks/use-feed-keyboard';
import {useNewsFeed} from './hooks/use-news-feed';

/**
 * `/` and `/news`: the news of one trading date. The filters live in the
 * URL, so a view can be shared and the back button works.
 */
export function FeedPage() {
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const today = todayInNewYork();
  const query = searchParams.toString();
  const filters = useMemo(
    () => parseFeedFilters(new URLSearchParams(query), today),
    [query, today],
  );
  const feed = useNewsFeed(filters);
  useDocumentTitle(`News feed, ${formatLongDate(filters.date)}`);
  const listRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const shortcuts = useShortcutsPreference();
  useFeedKeyboard(listRef, searchRef, shortcuts.enabled);

  const currentSearch = location.search;
  const setFilters = useCallback(
    (next: FeedFilters, options: {replace?: boolean} = {}) => {
      const search = feedSearch(next);
      // Same view: no navigation, so no duplicate history entry.
      if (search === currentSearch) {
        return;
      }
      void navigate(
        {pathname: '/news', search},
        {replace: options.replace ?? false},
      );
    },
    [navigate, currentSearch],
  );

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">News feed</h1>
        <p className="text-muted-foreground">{formatLongDate(filters.date)}</p>
      </div>
      <FeedFiltersBar
        filters={filters}
        today={today}
        onChange={setFilters}
        searchRef={searchRef}
      />
      <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
        {shortcuts.enabled && (
          <span>
            Keyboard: <kbd>/</kbd> search · <kbd>j</kbd>/<kbd>k</kbd> next or
            previous item · <kbd>Enter</kbd> open ·
          </span>
        )}
        <button
          type="button"
          onClick={shortcuts.toggle}
          className="underline underline-offset-4"
        >
          {shortcuts.enabled
            ? 'Turn off single-key shortcuts'
            : 'Turn on single-key shortcuts'}
        </button>
      </p>
      <div
        ref={listRef}
        aria-busy={feed.isFetching}
        className="flex flex-col gap-3"
      >
        <FeedBody
          feed={feed}
          filters={filters}
          today={today}
          onChange={setFilters}
        />
      </div>
    </div>
  );
}

interface FeedBodyProps {
  feed: ReturnType<typeof useNewsFeed>;
  filters: FeedFilters;
  today: string;
  onChange(filters: FeedFilters): void;
}

/** Loading, error, no feed, no matches, or the list. */
function FeedBody({feed, filters, today, onChange}: FeedBodyProps) {
  const list = feed.data;
  const items = useMemo(
    () => (list === undefined ? [] : newestFirst(list.items)),
    [list],
  );
  const shown = useMemo(() => visibleItems(items, filters), [items, filters]);
  if (list === undefined) {
    if (feed.isError) {
      return (
        <LoadError
          title="Couldn't load the feed"
          error={feed.error}
          onRetry={() => void feed.refetch()}
        />
      );
    }
    return <FeedSkeleton />;
  }
  if (list.run === null) {
    return <NoFeed date={filters.date} today={today} />;
  }
  const filtered =
    filters.ticker !== undefined ||
    filters.q !== undefined ||
    filters.verdict !== undefined;
  const search = feedSearch(filters);
  // A pressed chip clears the ticker filter; another chip sets it.
  const toggleTicker = (ticker: string) =>
    onChange({
      ...filters,
      ticker: ticker === filters.ticker ? undefined : ticker,
    });
  return (
    <>
      {feed.isError && (
        <LoadError
          title="Couldn't load the feed"
          error={feed.error}
          onRetry={() => void feed.refetch()}
        />
      )}
      {feed.isPlaceholderData ? (
        // The list on screen is from the previous filters: no summary for it.
        <p role="status" className="text-sm text-muted-foreground">
          Updating…
        </p>
      ) : (
        <RunStatus list={list} filters={filters} today={today} />
      )}
      <RuleRunStatus ruleRun={list.ruleRun} />
      {/* Only once the rules have run: the AI run comes after them, and
          the verification after the AI run. */}
      {list.ruleRun !== null && <AiRunStatus aiRun={list.aiRun} />}
      {list.aiRun !== null && <VerifyRunStatus verifyRun={list.verifyRun} />}
      {items.length > 0 && shown.length === 0 && (
        <div className="flex flex-col items-start gap-2 py-6">
          <p>No item in this view was flagged by the rule checks.</p>
          <button
            type="button"
            onClick={() => onChange({...filters, flagged: false})}
            className="font-medium underline underline-offset-4"
          >
            Show all items
          </button>
        </div>
      )}
      {items.length === 0 && (
        <div className="flex flex-col items-start gap-2 py-6">
          <p>
            {filtered
              ? 'No items match this ticker, search or verdict.'
              : 'No items in this feed yet.'}
          </p>
          {filtered && (
            <button
              type="button"
              onClick={() =>
                onChange({
                  ...filters,
                  ticker: undefined,
                  q: undefined,
                  verdict: undefined,
                })
              }
              className="font-medium underline underline-offset-4"
            >
              Show all items
            </button>
          )}
        </div>
      )}
      {shown.length > 0 && (
        <ul aria-label="News items" className="flex flex-col gap-3">
          {shown.map(item => (
            <NewsRow
              key={item.id}
              item={item}
              activeTicker={filters.ticker}
              onTickerClick={toggleTicker}
              feedSearch={search}
              duplicatesShown={filters.dups}
              markUnchecked={list.ruleRun !== null}
            />
          ))}
        </ul>
      )}
    </>
  );
}
