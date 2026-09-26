import {describe, expect, it} from 'vitest';

import {HttpError, NetworkError} from '@/api/errors';

import {
  CHAT_BUSY_DETAIL,
  answerSegments,
  chatErrorMessage,
  questionProblem,
  sourceKindLabel,
  vendorNewsId,
} from './chat';

describe('answerSegments', () => {
  const known = new Set([1, 2, 3]);

  it('splits the text on known citation markers', () => {
    expect(answerSegments('Revenue grew [1][2]. Vendor says [3].', known))
      .toMatchInlineSnapshot(`
      [
        {
          "kind": "text",
          "text": "Revenue grew ",
        },
        {
          "kind": "citation",
          "n": 1,
        },
        {
          "kind": "citation",
          "n": 2,
        },
        {
          "kind": "text",
          "text": ". Vendor says ",
        },
        {
          "kind": "citation",
          "n": 3,
        },
        {
          "kind": "text",
          "text": ".",
        },
      ]
    `);
  });

  it('keeps unknown markers and other brackets as text', () => {
    expect(answerSegments('See [9] and [a] and [1]', known)).toEqual([
      {kind: 'text', text: 'See [9] and [a] and '},
      {kind: 'citation', n: 1},
    ]);
    expect(answerSegments('', known)).toEqual([]);
    expect(answerSegments('<b>[2]</b>', known)).toEqual([
      {kind: 'text', text: '<b>'},
      {kind: 'citation', n: 2},
      {kind: 'text', text: '</b>'},
    ]);
  });
});

describe('source helpers', () => {
  it('labels every source kind', () => {
    expect(sourceKindLabel('edgar_8k')).toBe('SEC filing 8-K');
    expect(sourceKindLabel('edgar_ex99')).toBe(
      'Company press release (EX-99.1)',
    );
    expect(sourceKindLabel('xbrl_facts')).toBe('SEC company facts');
    expect(sourceKindLabel('fed_press')).toBe('Federal Reserve release');
    expect(sourceKindLabel('sec_press')).toBe('SEC release');
    expect(sourceKindLabel('vendor')).toBe('Vendor item (unverified)');
  });

  it('reads the news id of a vendor link, nothing else', () => {
    expect(vendorNewsId('/news/2458007')).toBe(2458007);
    for (const url of [
      'https://evil.example/news/1',
      '/news/1/../admin',
      '//news/1',
      '/news/abc',
    ]) {
      expect(vendorNewsId(url)).toBeUndefined();
    }
  });
});

describe('questionProblem', () => {
  it('needs 3 to 500 characters, trimmed', () => {
    expect(questionProblem('  Hi ')).toMatch(/at least 3/);
    expect(questionProblem('Why?')).toBeUndefined();
    expect(questionProblem(`${'x'.repeat(499)}📈`)).toBeUndefined();
    expect(questionProblem('x'.repeat(501))).toMatch(/500 characters/);
  });
});

describe('chatErrorMessage', () => {
  it('explains 429, 503 and 422 in plain words', () => {
    expect(
      chatErrorMessage(new HttpError('POST /chat', 429, CHAT_BUSY_DETAIL)),
    ).toMatch(/^Another question of yours is still being answered/);
    expect(
      chatErrorMessage(new HttpError('POST /chat', 429, 'Too Many Requests')),
    ).toMatch(/^Too many questions/);
    expect(chatErrorMessage(new HttpError('POST /chat', 503, 'x'))).toBe(
      "Ask the News isn't available on this server right now.",
    );
    expect(chatErrorMessage(new HttpError('POST /chat', 422, []))).toBe(
      'The question must be 3 to 500 characters.',
    );
    expect(chatErrorMessage(new NetworkError('POST /chat', 'offline'))).toMatch(
      /^Can't reach the server/,
    );
  });
});
