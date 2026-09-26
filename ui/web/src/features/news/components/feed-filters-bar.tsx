import {useEffect, useId, useState} from 'react';
import type {FormEvent, RefObject} from 'react';

import {Button} from '@/components/ui/button';
import {Input} from '@/components/ui/input';
import {Label} from '@/components/ui/label';
import {isIsoDate} from '@/lib/time';

import {MAX_QUERY_LENGTH, normalizeTicker} from '../feed';
import type {FeedFilters, VerdictFilter} from '../feed';
import {VERDICTS, verdictText} from '../verdicts';

/** Text search waits this long after the last key before it searches. */
export const SEARCH_DEBOUNCE_MS = 300;
/** A typed date is applied once the user stops typing (Chrome fires a
 * change per digit: 0002-, 0020-, 0202-, 2026-…). */
export const DATE_DEBOUNCE_MS = 500;

interface FeedFiltersBarProps {
  filters: FeedFilters;
  today: string;
  /** `replace`: update the URL without a new history entry. */
  onChange(filters: FeedFilters, options?: {replace?: boolean}): void;
  searchRef: RefObject<HTMLInputElement | null>;
}

/**
 * An input's text (a draft) kept in step with its URL value. Typing changes
 * only the draft. When the URL value changes:
 * - to the value this input just committed, the draft is kept: the
 *   navigation is applied in a transition and can land after more typing
 *   (or after a trailing space the URL trims away);
 * - to anything else (back button, a ticker chip), the draft is replaced.
 */
function useUrlDraft(urlValue: string) {
  const [text, setText] = useState(urlValue);
  const [synced, setSynced] = useState(urlValue);
  const [committed, setCommitted] = useState<string | undefined>(undefined);
  if (urlValue !== synced) {
    setSynced(urlValue);
    if (urlValue === committed) {
      setCommitted(undefined);
    } else {
      setText(urlValue);
    }
  }
  return {text, setText, commit: setCommitted};
}

function searchValue(text: string): string | undefined {
  const q = text.trim();
  return q === '' ? undefined : q;
}

/** Date, ticker, text search, and the duplicates and flagged toggles. */
export function FeedFiltersBar({
  filters,
  today,
  onChange,
  searchRef,
}: FeedFiltersBarProps) {
  const tickerErrorId = useId();
  const date = useUrlDraft(filters.date);
  const ticker = useUrlDraft(filters.ticker ?? '');
  const search = useUrlDraft(filters.q ?? '');
  const [tickerInvalid, setTickerInvalid] = useState(false);
  const commitSearch = search.commit;
  const commitDate = date.commit;

  // Search 300 ms after the last key. The first search of a view is a new
  // history entry (Back undoes it); refining it replaces that entry.
  useEffect(() => {
    const q = searchValue(search.text);
    if (q === filters.q) {
      return undefined;
    }
    const timer = setTimeout(() => {
      commitSearch(q ?? '');
      onChange({...filters, q}, {replace: filters.q !== undefined});
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [search.text, commitSearch, filters, onChange]);

  // Apply a typed date once it is complete and the typing has stopped.
  useEffect(() => {
    if (!isIsoDate(date.text) || date.text === filters.date) {
      return undefined;
    }
    const timer = setTimeout(() => {
      commitDate(date.text);
      onChange({...filters, date: date.text});
    }, DATE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [date.text, commitDate, filters, onChange]);

  // Enter in any field applies the ticker and the search at once.
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextTicker = normalizeTicker(ticker.text);
    const invalid = ticker.text.trim() !== '' && nextTicker === undefined;
    setTickerInvalid(invalid);
    if (invalid) {
      return;
    }
    const q = searchValue(search.text);
    ticker.commit(nextTicker ?? '');
    search.commit(q ?? '');
    onChange({...filters, ticker: nextTicker, q});
  }

  return (
    <form
      role="search"
      aria-label="Filter the feed"
      onSubmit={handleSubmit}
      className="flex flex-wrap items-end gap-3"
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="feed-date">Date</Label>
        <Input
          id="feed-date"
          type="date"
          min="2020-01-01"
          max={today}
          value={date.text}
          onChange={event => date.setText(event.target.value)}
          className="w-40"
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="feed-ticker">Ticker</Label>
        <Input
          id="feed-ticker"
          value={ticker.text}
          onChange={event => {
            ticker.setText(event.target.value);
            setTickerInvalid(false);
          }}
          autoCapitalize="characters"
          spellCheck={false}
          placeholder="e.g. AAPL"
          maxLength={10}
          aria-invalid={tickerInvalid}
          aria-describedby={tickerInvalid ? tickerErrorId : undefined}
          className="w-28 uppercase"
        />
        {tickerInvalid && (
          <p id={tickerErrorId} className="text-xs text-destructive">
            Not a valid ticker
          </p>
        )}
      </div>
      <div className="flex min-w-48 flex-1 flex-col gap-1.5">
        <Label htmlFor="feed-search">Search headlines and text</Label>
        <Input
          id="feed-search"
          type="search"
          ref={searchRef}
          value={search.text}
          maxLength={MAX_QUERY_LENGTH}
          onChange={event => search.setText(event.target.value)}
          aria-keyshortcuts="/"
        />
      </div>
      {/* A form with several text fields submits on Enter only if it has a
          submit button. */}
      <Button type="submit" variant="outline">
        Apply
      </Button>
      {/* After Apply: Tab from the text fields reaches Apply first. */}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="feed-verdict">Verdict</Label>
        <select
          id="feed-verdict"
          value={filters.verdict ?? ''}
          onChange={event =>
            onChange({
              ...filters,
              verdict:
                event.target.value === ''
                  ? undefined
                  : (event.target.value as VerdictFilter),
            })
          }
          className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm"
        >
          <option value="">Any verdict</option>
          {VERDICTS.map(verdict => (
            <option key={verdict} value={verdict}>
              {verdictText(verdict)}
            </option>
          ))}
          <option value="PENDING">Pending review</option>
        </select>
      </div>
      <label className="flex h-8 items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={filters.dups}
          onChange={event => onChange({...filters, dups: event.target.checked})}
          className="size-4"
        />
        Show duplicates
      </label>
      <label className="flex h-8 items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={filters.flagged}
          onChange={event =>
            onChange({...filters, flagged: event.target.checked})
          }
          className="size-4"
        />
        Flagged only
      </label>
      {(filters.ticker !== undefined || filters.q !== undefined) && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() =>
            onChange({...filters, ticker: undefined, q: undefined})
          }
        >
          Clear ticker and search
        </Button>
      )}
    </form>
  );
}
