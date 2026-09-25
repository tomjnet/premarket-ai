import {describe, expect, it} from 'vitest';

import {backToFeedSearch, bodyParagraphs, parseNewsId} from './detail';

const TODAY = '2026-09-25';

describe('parseNewsId', () => {
  it('accepts a positive integer id', () => {
    expect(parseNewsId('2458087')).toBe(2458087);
    expect(parseNewsId('0')).toBe(0);
  });

  it('rejects anything else', () => {
    for (const param of [
      undefined,
      '',
      'abc',
      '12a',
      '-1',
      '1.5',
      ' 1',
      '9'.repeat(16),
    ]) {
      expect(parseNewsId(param)).toBeUndefined();
    }
  });
});

describe('backToFeedSearch', () => {
  it("returns to the feed's filters from the router state", () => {
    expect(
      backToFeedSearch(
        {feedSearch: '?date=2026-09-24&ticker=AAPL&q=buyback&dups=1'},
        '2026-09-24',
        TODAY,
      ),
    ).toBe('?date=2026-09-24&ticker=AAPL&q=buyback&dups=1');
  });

  it('cleans up whatever the state holds', () => {
    expect(
      backToFeedSearch(
        {feedSearch: '?date=nope&ticker=%3Cb%3E&evil=1'},
        undefined,
        TODAY,
      ),
    ).toBe(`?date=${TODAY}`);
  });

  it("falls back to the item's feed date, then to the default feed", () => {
    expect(backToFeedSearch(null, '2026-09-24', TODAY)).toBe(
      '?date=2026-09-24',
    );
    expect(backToFeedSearch({feedSearch: 42}, undefined, TODAY)).toBe('');
    expect(backToFeedSearch(undefined, undefined, TODAY)).toBe('');
  });
});

describe('bodyParagraphs', () => {
  it('splits on blank lines and keeps single line breaks inside', () => {
    expect(
      bodyParagraphs('One.\nStill one.\n\n  Two.  \n\n\n\nThree.'),
    ).toEqual(['One.\nStill one.', 'Two.', 'Three.']);
    expect(bodyParagraphs('\n\n')).toEqual([]);
  });
});
