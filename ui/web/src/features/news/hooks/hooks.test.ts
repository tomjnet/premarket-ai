import {describe, expect, it} from 'vitest';

import type {NewsList} from '@/api/schemas/news';

import {isTypingTarget, nextRowIndex} from './use-feed-keyboard';
import {FEED_POLL_MS, feedRefetchInterval} from './use-news-feed';

describe('feedRefetchInterval', () => {
  const run = {
    runId: 1,
    startedAt: '2026-09-25T09:30:02Z',
    finishedAt: null,
    rowsReceived: 25,
    dups: 2,
  };
  const list = (status: 'RUNNING' | 'DONE' | 'FAILED'): NewsList => ({
    date: '2026-09-25',
    run: {...run, status},
    ruleRun: null,
    aiRun: null,
    count: 0,
    items: [],
  });
  const ruleRun = {
    finishedAt: null,
    items: 50,
    duplicates: 7,
    flagged: 9,
  };

  it('polls every 30 s only while the run is RUNNING', () => {
    expect(feedRefetchInterval(list('RUNNING'))).toBe(FEED_POLL_MS);
    expect(FEED_POLL_MS).toBe(30_000);
    expect(feedRefetchInterval(list('DONE'))).toBe(false);
    expect(feedRefetchInterval(list('FAILED'))).toBe(false);
    expect(feedRefetchInterval(undefined)).toBe(false);
  });

  it('also polls while the rule checks are RUNNING', () => {
    const done = list('DONE');
    expect(
      feedRefetchInterval({
        ...done,
        ruleRun: {...ruleRun, status: 'RUNNING'},
      }),
    ).toBe(FEED_POLL_MS);
    expect(
      feedRefetchInterval({...done, ruleRun: {...ruleRun, status: 'FAILED'}}),
    ).toBe(false);
  });

  it('also polls while the AI run is RUNNING', () => {
    const aiRun = {
      finishedAt: null,
      items: 86,
      paraphrases: 0,
      conflicts: 0,
      summarized: 10,
      fallbacks: 0,
      failed: 0,
      model: 'main-gpu4gb',
    };
    const done = list('DONE');
    expect(
      feedRefetchInterval({...done, aiRun: {...aiRun, status: 'RUNNING'}}),
    ).toBe(FEED_POLL_MS);
    expect(
      feedRefetchInterval({...done, aiRun: {...aiRun, status: 'DONE'}}),
    ).toBe(false);
  });
});

describe('nextRowIndex', () => {
  it('starts at the first row and stays inside the list', () => {
    expect(nextRowIndex(-1, 1, 3)).toBe(0);
    expect(nextRowIndex(-1, -1, 3)).toBe(0);
    expect(nextRowIndex(0, 1, 3)).toBe(1);
    expect(nextRowIndex(2, 1, 3)).toBe(2);
    expect(nextRowIndex(0, -1, 3)).toBe(0);
    expect(nextRowIndex(-1, 1, 0)).toBe(-1);
  });
});

describe('isTypingTarget', () => {
  it('is true for text fields, false for checkboxes and buttons', () => {
    const text = document.createElement('input');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    expect(isTypingTarget(text)).toBe(true);
    expect(isTypingTarget(document.createElement('textarea'))).toBe(true);
    expect(isTypingTarget(checkbox)).toBe(false);
    expect(isTypingTarget(document.createElement('button'))).toBe(false);
    expect(isTypingTarget(null)).toBe(false);
  });
});
