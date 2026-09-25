/**
 * Calendar and time-zone helpers. Dates are `YYYY-MM-DD` strings (a trading
 * date has no time zone); instants are ISO 8601 UTC strings. "Today" means
 * today in New York, not in the browser's zone.
 */

export const NEW_YORK = 'America/New_York';

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const DAY_MS = 24 * 60 * 60 * 1000;

// Built once: creating an Intl.DateTimeFormat is slow.
const NEW_YORK_DATE = new Intl.DateTimeFormat('en-US', {
  timeZone: NEW_YORK,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});
const NEW_YORK_OFFSET = new Intl.DateTimeFormat('en-US', {
  timeZone: NEW_YORK,
  timeZoneName: 'shortOffset',
});

/** True for a real calendar date in `YYYY-MM-DD` form. */
export function isIsoDate(value: string): boolean {
  const match = ISO_DATE.exec(value);
  if (match === null) {
    return false;
  }
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && toIsoDate(date) === value;
}

function toIsoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function parseIsoDate(value: string): Date {
  if (!isIsoDate(value)) {
    throw new Error(`Not a YYYY-MM-DD date: ${value}`);
  }
  return new Date(`${value}T00:00:00Z`);
}

/** The date `days` days after `date` (negative to go back). */
export function addDays(date: string, days: number): string {
  return toIsoDate(new Date(parseIsoDate(date).getTime() + days * DAY_MS));
}

/** Saturday or Sunday. NYSE holidays are ignored, as in the mock. */
export function isWeekend(date: string): boolean {
  const weekday = parseIsoDate(date).getUTCDay();
  return weekday === 0 || weekday === 6;
}

/** The closest weekday before `date`. */
export function previousTradingDate(date: string): string {
  let previous = addDays(date, -1);
  while (isWeekend(previous)) {
    previous = addDays(previous, -1);
  }
  return previous;
}

/** Whole days from `from` to `to` (negative when `to` is earlier). */
export function daysBetween(from: string, to: string): number {
  return Math.round(
    (parseIsoDate(to).getTime() - parseIsoDate(from).getTime()) / DAY_MS,
  );
}

/** The instant `seconds` after `instant` (ISO 8601 UTC, no milliseconds). */
export function addSeconds(instant: string, seconds: number): string {
  return new Date(Date.parse(instant) + seconds * 1000)
    .toISOString()
    .replace('.000Z', 'Z');
}

/** Today's date in New York. */
export function todayInNewYork(now: Date = new Date()): string {
  // Built from parts, not from a locale's date pattern, which can change.
  const parts = NEW_YORK_DATE.formatToParts(now);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find(candidate => candidate.type === type)?.value ?? '';
  return `${part('year')}-${part('month')}-${part('day')}`;
}

const LONG_DATE = new Intl.DateTimeFormat('en-US', {
  weekday: 'long',
  year: 'numeric',
  month: 'long',
  day: 'numeric',
  timeZone: 'UTC',
});

/** `2026-09-25` → `Friday, September 25, 2026`. */
export function formatLongDate(date: string): string {
  return LONG_DATE.format(parseIsoDate(date));
}

const NEW_YORK_CLOCK = new Intl.DateTimeFormat('en-US', {
  timeZone: NEW_YORK,
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

/** An ISO UTC instant as New York wall-clock time, `HH:MM` (24 h). */
export function formatEtTime(instant: string): string {
  return NEW_YORK_CLOCK.format(new Date(instant));
}

const UTC_CLOCK = new Intl.DateTimeFormat('en-US', {
  timeZone: 'UTC',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

/** An ISO UTC instant as UTC wall-clock time, `HH:MM` (24 h). */
export function formatUtcTime(instant: string): string {
  return UTC_CLOCK.format(new Date(instant));
}

/**
 * An ISO UTC instant as `YYYY-MM-DD HH:MM UTC`. With the date, because the
 * UTC day can differ from the New York day (evening news).
 */
export function formatUtcDateTime(instant: string): string {
  const date = new Date(instant).toISOString().slice(0, 10);
  return `${date} ${formatUtcTime(instant)} UTC`;
}

/** The New York calendar date of an ISO UTC instant, `YYYY-MM-DD`. */
export function newYorkDateOf(instant: string): string {
  return todayInNewYork(new Date(instant));
}

/** New York's offset from UTC in minutes at `instant` (-240 or -300). */
function newYorkOffsetMinutes(instant: Date): number {
  const name = NEW_YORK_OFFSET.formatToParts(instant).find(
    part => part.type === 'timeZoneName',
  )?.value;
  const match = /GMT([+-]\d+)(?::(\d{2}))?/.exec(name ?? '');
  if (match === null) {
    return 0;
  }
  const hours = Number(match[1]);
  const minutes = Number(match[2] ?? '0');
  return hours * 60 + Math.sign(hours) * minutes;
}

/**
 * The UTC instant (ISO 8601, `Z`) of a New York wall-clock time. Minutes may
 * exceed 59 or be negative; they roll over into other hours and days.
 */
export function newYorkTimeToUtc(
  date: string,
  hours: number,
  minutes: number,
): string {
  const wallAsUtc =
    parseIsoDate(date).getTime() + (hours * 60 + minutes) * 60_000;
  // The offset at the guessed instant is right except within an hour of a
  // DST switch, where one correction pass fixes it.
  let offset = newYorkOffsetMinutes(new Date(wallAsUtc));
  offset = newYorkOffsetMinutes(new Date(wallAsUtc - offset * 60_000));
  return new Date(wallAsUtc - offset * 60_000)
    .toISOString()
    .replace('.000Z', 'Z');
}
