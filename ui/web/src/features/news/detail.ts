import {feedSearch, parseFeedFilters} from './feed';

/** The numeric id from `/news/:id`, or undefined if it can't be one. */
export function parseNewsId(param: string | undefined): number | undefined {
  if (param === undefined || !/^\d{1,15}$/.test(param)) {
    return undefined;
  }
  return Number(param);
}

/**
 * The feed query the back link returns to. Opened from the feed, the feed's
 * filters come in the router state (re-parsed, never trusted as they are);
 * opened directly, it is the item's feed date, or the default feed.
 */
export function backToFeedSearch(
  routerState: unknown,
  feedDate: string | undefined,
  today: string,
): string {
  if (
    typeof routerState === 'object' &&
    routerState !== null &&
    'feedSearch' in routerState &&
    typeof routerState.feedSearch === 'string'
  ) {
    const params = new URLSearchParams(routerState.feedSearch);
    return feedSearch(parseFeedFilters(params, today));
  }
  if (feedDate !== undefined) {
    return feedSearch({date: feedDate, dups: false});
  }
  return '';
}

/** Paragraphs of a plain-text body: split on blank lines, empty ones dropped. */
export function bodyParagraphs(body: string): string[] {
  return body
    .split(/\n\s*\n/)
    .map(paragraph => paragraph.trim())
    .filter(paragraph => paragraph !== '');
}
