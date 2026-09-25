import {describe, expect, it} from 'vitest';

import {
  addDays,
  addSeconds,
  daysBetween,
  formatEtTime,
  formatLongDate,
  formatUtcDateTime,
  formatUtcTime,
  isIsoDate,
  isWeekend,
  newYorkDateOf,
  newYorkTimeToUtc,
  previousTradingDate,
  todayInNewYork,
} from './time';

describe('isIsoDate', () => {
  it('accepts real dates only', () => {
    expect(isIsoDate('2026-09-24')).toBe(true);
    expect(isIsoDate('2028-02-29')).toBe(true);
    expect(isIsoDate('2026-02-29')).toBe(false);
    expect(isIsoDate('2026-9-24')).toBe(false);
    expect(isIsoDate('24/09/2026')).toBe(false);
    expect(isIsoDate('')).toBe(false);
  });
});

describe('calendar arithmetic', () => {
  it('adds days across month and year ends', () => {
    expect(addDays('2026-09-30', 1)).toBe('2026-10-01');
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01');
    expect(addDays('2026-03-01', -1)).toBe('2026-02-28');
  });

  it('counts days between dates', () => {
    expect(daysBetween('2026-09-24', '2026-09-28')).toBe(4);
    expect(daysBetween('2026-09-28', '2026-09-24')).toBe(-4);
  });

  it('knows weekends', () => {
    expect(isWeekend('2026-09-26')).toBe(true); // Saturday
    expect(isWeekend('2026-09-27')).toBe(true); // Sunday
    expect(isWeekend('2026-09-28')).toBe(false); // Monday
  });

  it('goes back from Monday or Sunday to Friday', () => {
    expect(previousTradingDate('2026-09-28')).toBe('2026-09-25');
    expect(previousTradingDate('2026-09-27')).toBe('2026-09-25');
    expect(previousTradingDate('2026-09-24')).toBe('2026-09-23');
  });

  it('rejects malformed dates', () => {
    expect(() => addDays('2026-13-01', 1)).toThrow('Not a YYYY-MM-DD date');
  });
});

describe('formatLongDate', () => {
  it('spells the date out, independent of the browser zone', () => {
    expect(formatLongDate('2026-09-25')).toBe('Friday, September 25, 2026');
    expect(formatLongDate('2027-01-01')).toBe('Friday, January 1, 2027');
  });
});

describe('formatEtTime', () => {
  it('shows New York time, 24 h, in summer and winter', () => {
    expect(formatEtTime('2026-09-24T08:12:00Z')).toBe('04:12');
    expect(formatEtTime('2026-12-01T13:30:00Z')).toBe('08:30');
    expect(formatEtTime('2026-09-24T04:05:00Z')).toBe('00:05');
  });
});

describe('formatUtcTime and newYorkDateOf', () => {
  it('shows UTC time and the New York date of an instant', () => {
    expect(formatUtcTime('2026-09-24T02:05:00Z')).toBe('02:05');
    // 02:05 UTC on the 24th is still the 23rd in New York.
    expect(newYorkDateOf('2026-09-24T02:05:00Z')).toBe('2026-09-23');
    expect(newYorkDateOf('2026-09-24T08:12:00Z')).toBe('2026-09-24');
  });

  it('gives the UTC date with the UTC time', () => {
    // 21:30 ET on the 24th is 01:30 UTC on the 25th.
    expect(formatUtcDateTime('2026-09-25T01:30:00Z')).toBe(
      '2026-09-25 01:30 UTC',
    );
  });
});

describe('New York time', () => {
  it('uses New York, not UTC, for today', () => {
    // 02:00 UTC on the 25th is still the evening of the 24th in New York.
    expect(todayInNewYork(new Date('2026-09-25T02:00:00Z'))).toBe('2026-09-24');
    expect(todayInNewYork(new Date('2026-09-25T05:00:00Z'))).toBe('2026-09-25');
  });

  it('converts wall-clock time in summer (EDT) and winter (EST)', () => {
    expect(newYorkTimeToUtc('2026-09-24', 5, 30)).toBe('2026-09-24T09:30:00Z');
    expect(newYorkTimeToUtc('2026-12-01', 5, 30)).toBe('2026-12-01T10:30:00Z');
  });

  it('rolls minutes over into the next day', () => {
    expect(newYorkTimeToUtc('2026-09-23', 16, 13 * 60 + 15)).toBe(
      '2026-09-24T09:15:00Z',
    );
  });

  it('handles the day DST ends', () => {
    // 2026-11-01: 01:59 EDT is followed by 01:00 EST.
    expect(newYorkTimeToUtc('2026-11-01', 0, 30)).toBe('2026-11-01T04:30:00Z');
    expect(newYorkTimeToUtc('2026-11-01', 3, 0)).toBe('2026-11-01T08:00:00Z');
  });

  it('adds seconds to an instant', () => {
    expect(addSeconds('2026-09-24T09:30:02Z', 3)).toBe('2026-09-24T09:30:05Z');
  });
});
