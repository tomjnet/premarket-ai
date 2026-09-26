import {HttpError, errorMessage} from '@/api/errors';
import type {Brief, BriefEdition, BriefItem} from '@/api/schemas/brief';
import {isIsoDate} from '@/lib/time';

/**
 * Pure rules of Today's Brief (increment 5): the date from the URL, the
 * order of the sections, and the texts.
 */

/** `?date=` when it is a real date not after today, else today. */
export function briefDate(params: URLSearchParams, today: string): string {
  const date = params.get('date');
  return date !== null && isIsoDate(date) && date <= today ? date : today;
}

const EDITION_TEXT: Record<BriefEdition, string> = {
  morning: 'Morning edition (07:15 ET)',
  refresh: 'Refreshed at 09:00 ET',
};

export function editionText(edition: BriefEdition): string {
  return EDITION_TEXT[edition];
}

/** The items by number. */
export function itemsByNumber(brief: Brief): Map<number, BriefItem> {
  return new Map(brief.items.map(item => [item.n, item]));
}

/** The items of some numbers, in that order (unknown numbers skipped). */
export function pick(brief: Brief, numbers: readonly number[]): BriefItem[] {
  const byNumber = itemsByNumber(brief);
  return numbers.flatMap(n => {
    const item = byNumber.get(n);
    return item === undefined ? [] : [item];
  });
}

/** The sector sections, the ones the reader follows first. */
export function orderedSectors(
  brief: Brief,
  followed: readonly string[],
): Brief['sectors'] {
  const first = brief.sectors.filter(sector => followed.includes(sector.name));
  const rest = brief.sectors.filter(sector => !followed.includes(sector.name));
  return [...first, ...rest];
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/**
 * What the brief left out, in words: only counted, never shown ("6 items
 * pending review · 9 misleading · 17 fake").
 */
export function leftOutText(counts: Brief['counts']): string {
  const parts = [
    plural(counts.pendingReview, 'item pending review', 'items pending review'),
    `${counts.misleading} misleading`,
    `${counts.fake} fake`,
  ];
  if (counts.failed > 0) {
    parts.push(`${counts.failed} not checked (failed)`);
  }
  return parts.join(' · ');
}

/** The message for a brief that couldn't be loaded or written. */
export function briefErrorMessage(error: unknown, date: string): string {
  if (error instanceof HttpError) {
    if (error.status === 404) {
      return `No brief for ${date} yet. It is written after the AI verification of the day.`;
    }
    if (error.status === 409) {
      const detail =
        typeof error.detail === 'string' ? error.detail : 'try again later';
      return `Can't write the brief now: ${detail}.`;
    }
    if (error.status === 503) {
      return "The brief isn't available on this server right now.";
    }
  }
  return errorMessage(error);
}
