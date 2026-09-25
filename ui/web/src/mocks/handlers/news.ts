import {HttpResponse, http} from 'msw';

import type {
  IngestRunWire,
  NewsDetailWire,
  NewsItemWire,
  NewsListWire,
} from '@/api/schemas/news';
import {apiUrl} from '@/lib/env';
import {isIsoDate} from '@/lib/time';

import {db} from '../data/db';
import type {GeneratedDay} from '../data/generator';
import {activeScenario} from '../scenarios';

import {
  notFound,
  rejectUnauthenticated,
  scenarioLatency,
  serverError,
  validationError,
} from './common';

/**
 * `running`: 25 more items (oldest first) every 30 s, the UI's poll
 * interval, counted from the first look at the date. Time-based, so filter
 * changes and refetches don't move the run forward.
 */
export const RUNNING_ITEMS_PER_STEP = 25;
export const RUNNING_STEP_MS = 30_000;
/** `failed`: how many items arrived before the run failed. */
export const FAILED_ITEMS = 40;

// Pydantic's accepted spellings for a bool query parameter.
const TRUE_VALUES = ['true', '1', 'yes', 'on', 't', 'y'];
const FALSE_VALUES = ['false', '0', 'no', 'off', 'f', 'n'];

/** `GET /news` and `GET /news/{id}`. */
export const newsHandlers = [
  http.get(apiUrl('/news'), async ({request}) => {
    await scenarioLatency();
    const denied = rejectUnauthenticated(request);
    if (denied !== undefined) {
      return denied;
    }
    if (activeScenario() === 'server-error') {
      return serverError();
    }
    const params = new URL(request.url).searchParams;
    const date = params.get('date');
    if (date === null || !isIsoDate(date)) {
      return validationError({
        loc: ['query', 'date'],
        msg:
          date === null
            ? 'Field required'
            : 'Input should be a valid date in the format YYYY-MM-DD',
        type: date === null ? 'missing' : 'date_from_datetime_parsing',
      });
    }
    const includeDuplicates = parseBool(params.get('include_duplicates'));
    if (includeDuplicates === undefined) {
      return validationError({
        loc: ['query', 'include_duplicates'],
        msg: 'Input should be a valid boolean, unable to interpret input',
        type: 'bool_parsing',
      });
    }
    const feed = scenarioFeed(db.day(date));
    const items = feed.items
      .filter(item => includeDuplicates || !item.is_dup)
      .filter(item => matchesTicker(item, params.get('ticker')))
      .filter(item => matchesText(item, params.get('q')))
      .map(withoutBody);
    const list: NewsListWire = {
      date,
      run: feed.run,
      count: items.length,
      items,
    };
    if (activeScenario() === 'contract-drift') {
      // `count` as a string: the client must answer with a ContractError.
      return HttpResponse.json({...list, count: String(list.count)});
    }
    return HttpResponse.json(list);
  }),

  http.get(apiUrl('/news/:id'), async ({request, params}) => {
    await scenarioLatency();
    const denied = rejectUnauthenticated(request);
    if (denied !== undefined) {
      return denied;
    }
    if (activeScenario() === 'server-error') {
      return serverError();
    }
    const id = String(params.id);
    if (!/^\d+$/.test(id)) {
      return validationError({
        loc: ['path', 'id'],
        msg: 'Input should be a valid integer, unable to parse string as an integer',
        type: 'int_parsing',
      });
    }
    const item = db.item(Number(id));
    // In `running`/`failed`, items that haven't arrived don't exist yet.
    const arrived =
      item !== undefined &&
      scenarioFeed(db.day(item.feed_date)).items.some(
        candidate => candidate.id === item.id,
      );
    if (!arrived) {
      return notFound();
    }
    if (activeScenario() === 'contract-drift') {
      // `id` as a string: the client must answer with a ContractError.
      return HttpResponse.json({...item, id: String(item.id)});
    }
    return HttpResponse.json(item);
  }),
];

/** The list endpoint sends items without their body. */
function withoutBody({body, ...item}: NewsDetailWire): NewsItemWire {
  return item;
}

function parseBool(value: string | null): boolean | undefined {
  if (value === null) {
    return false;
  }
  const lower = value.toLowerCase();
  if (TRUE_VALUES.includes(lower)) {
    return true;
  }
  return FALSE_VALUES.includes(lower) ? false : undefined;
}

function matchesTicker(item: NewsDetailWire, ticker: string | null): boolean {
  if (ticker === null || ticker === '') {
    return true;
  }
  return item.tickers.includes(ticker.toUpperCase());
}

function matchesText(item: NewsDetailWire, q: string | null): boolean {
  if (q === null || q.trim() === '') {
    return true;
  }
  const needle = q.trim().toLowerCase();
  return (
    item.headline.toLowerCase().includes(needle) ||
    item.body.toLowerCase().includes(needle)
  );
}

/** The run and items the active scenario shows for a day. */
function scenarioFeed(day: GeneratedDay): {
  run: IngestRunWire | null;
  items: NewsDetailWire[];
} {
  if (day.run === null) {
    return day;
  }
  switch (activeScenario()) {
    case 'empty':
      return {run: null, items: []};
    case 'running': {
      const steps = Math.floor(
        (db.now() - db.runningSince(day.date)) / RUNNING_STEP_MS,
      );
      const shown = (steps + 1) * RUNNING_ITEMS_PER_STEP;
      if (shown >= day.items.length) {
        return day;
      }
      return partialFeed(day.run, day.items, shown, 'RUNNING');
    }
    case 'failed':
      return partialFeed(day.run, day.items, FAILED_ITEMS, 'FAILED');
    default:
      return day;
  }
}

/** The first `count` items to arrive (oldest first) of a newest-first list. */
function partialFeed(
  run: IngestRunWire,
  items: readonly NewsDetailWire[],
  count: number,
  status: 'RUNNING' | 'FAILED',
): {run: IngestRunWire; items: NewsDetailWire[]} {
  const arrived = items.slice(-count);
  return {
    run: {
      ...run,
      status,
      finished_at: status === 'RUNNING' ? null : run.finished_at,
      rows_received: arrived.length,
      dups: arrived.filter(item => item.is_dup).length,
    },
    items: arrived,
  };
}
