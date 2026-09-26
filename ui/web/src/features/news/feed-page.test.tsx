import {fireEvent, screen, waitFor, within} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import type {NewsDetailWire} from '@/api/schemas/news';
import {db} from '@/mocks/data/db';
import {server} from '@/mocks/node';
import {setScenario} from '@/mocks/scenarios';
import {expectNoA11yViolations} from '@/test/axe';
import {renderApp, withMockSession} from '@/test/render';

// Friday 2026-09-25, 09:00 in New York. Only Date is faked; timers are real.
const NOW = new Date('2026-09-25T13:00:00Z');
// Re-rendering ~100 rows twice (StrictMode) in jsdom takes a moment, more
// so when all test files run in parallel. waitFor returns as soon as it can.
const SLOW_DOM = {timeout: 10_000};
// 100 items: 14 duplicates by the rule checks (9 of them by legacy) and 2
// paraphrases by the AI run.
const SHOWN_BY_DEFAULT = 84;

beforeEach(() => {
  vi.useFakeTimers({toFake: ['Date']});
  vi.setSystemTime(NOW);
  withMockSession();
});

afterEach(() => {
  vi.useRealTimers();
});

/** The feed rows (not the items of their badge lists). */
function rows(): HTMLElement[] {
  return within(screen.getByRole('list', {name: 'News items'}))
    .getAllByRole('listitem')
    .filter(row => row.hasAttribute('data-feed-row'));
}

/** The row of item `id` (headlines can repeat: copies). */
function rowOf(id: number | undefined): HTMLElement {
  const row = rows().find(
    candidate =>
      candidate.querySelector('a[data-row-link]')?.getAttribute('href') ===
      `/news/${id}`,
  );
  if (row === undefined) {
    throw new Error(`No row for item ${id}`);
  }
  return row;
}

/** The texts of a row's rule badges, in order. */
function badgeTexts(row: HTMLElement): string[] {
  const list = within(row).queryByRole('list', {name: 'Rule checks'});
  if (list === null) {
    return [];
  }
  return within(list)
    .getAllByRole('listitem')
    .map(item => item.textContent ?? '');
}

async function openFeed(path = '/news') {
  const view = renderApp(path);
  await screen.findByRole('list', {name: 'News items'}, SLOW_DOM);
  return view;
}

describe('FeedPage: default day', {timeout: 30_000}, () => {
  it("shows today's feed, newest first, duplicates hidden", async () => {
    await openFeed('/');

    const main = screen.getByRole('main');
    expect(
      within(main).getByText('Friday, September 25, 2026'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('84 items · 16 duplicates hidden · updated 05:30 ET'),
    ).toBeInTheDocument();
    const all = rows();
    expect(all).toHaveLength(SHOWN_BY_DEFAULT);
    const times = all.map(
      row => row.querySelector('time')?.getAttribute('dateTime') ?? '',
    );
    expect([...times].sort().reverse()).toEqual(times);
    expect(screen.queryByText(/Duplicate of/)).not.toBeInTheDocument();
  });

  it('has no axe violations (filtered view, so axe stays fast)', async () => {
    const {container} = await openFeed('/news?ticker=AAPL&dups=1');

    await expectNoA11yViolations(container);
  });

  it('shows duplicates, marked, when asked', async () => {
    const {user, router} = await openFeed();

    await user.click(screen.getByLabelText('Show duplicates'));

    await waitFor(() => expect(rows()).toHaveLength(100), SLOW_DOM);
    expect(router.state.location.search).toContain('dups=1');
    expect(screen.getAllByText(/^Duplicate of VND-/)).toHaveLength(16);
    expect(
      screen.getByText('100 items · 16 duplicates shown · updated 05:30 ET'),
    ).toBeInTheDocument();
  });
});

// Several tests here render the full feed more than once: slower in jsdom.
describe('FeedPage: rule checks', {timeout: 30_000}, () => {
  const day = () => db.day('2026-09-25');

  it('summarizes the rule run in the header', async () => {
    await openFeed();

    expect(
      screen.getByText(
        `Rule checks: 100 items · 14 duplicates · ${day().ruleRun?.flagged} flagged`,
      ),
    ).toBeInTheDocument();
  });

  it('shows the badges of flagged items, in order', async () => {
    await openFeed();
    const item = day().items.find(
      entry =>
        !entry.is_dup &&
        entry.reason_codes.includes('FAKE_COMPANY') &&
        entry.reason_codes.includes('SPOOFED_SOURCE'),
    );
    const clean = day().items.find(
      entry =>
        !entry.is_dup && entry.reason_codes.length === 0 && entry.copies === 0,
    );

    expect(badgeTexts(rowOf(item?.id))).toEqual([
      'FAKE COMPANY',
      'FAKE TICKER',
      'SPOOFED SOURCE',
    ]);
    expect(badgeTexts(rowOf(clean?.id))).toEqual([]);
  });

  it('counts the hidden copies of a story, and marks the copies', async () => {
    const {user} = await openFeed();
    const original = day().items.find(entry => entry.copies > 0);
    const copies = original?.copies ?? 0;
    const row = rowOf(original?.id);
    const spoken = `${copies} ${copies === 1 ? 'copy' : 'copies'} of this story`;

    expect(badgeTexts(row).at(-1)).toBe(`DUPLICATE ×${copies}${spoken} hidden`);
    expect(within(row).getByText(`${spoken} hidden`)).toBeInTheDocument();

    await user.click(screen.getByLabelText('Show duplicates'));
    await waitFor(() => expect(rows()).toHaveLength(100), SLOW_DOM);
    expect(
      within(rowOf(original?.id)).getByText(`${spoken} shown`),
    ).toBeInTheDocument();
    const near = day().items.find(entry => entry.dup_type === 'near');
    const nearRow = rowOf(near?.id);
    expect(within(nearRow).getByText('DUPLICATE · near')).toBeInTheDocument();
    expect(
      within(nearRow).getByText(`Duplicate of ${near?.dup_of ?? ''}`),
    ).toBeInTheDocument();
    expect(screen.getAllByText('STALE').length).toBeGreaterThan(0);
  });

  it('"Flagged only" lists flagged items without a new request, in the URL', async () => {
    const {user, router} = await openFeed();
    let requests = 0;
    server.events.on('request:start', () => {
      requests += 1;
    });
    const flagged = day().items.filter(
      entry => !entry.is_dup && entry.reason_codes.length > 0,
    ).length;

    await user.click(screen.getByLabelText('Flagged only'));

    await waitFor(() => expect(rows()).toHaveLength(flagged), SLOW_DOM);
    expect(router.state.location.search).toContain('flagged=1');
    expect(requests).toBe(0);
    expect(
      screen.getByText(
        `${flagged} of ${SHOWN_BY_DEFAULT} items flagged · 16 duplicates hidden · updated 05:30 ET`,
      ),
    ).toBeInTheDocument();
    for (const row of rows()) {
      expect(badgeTexts(row).length).toBeGreaterThan(0);
    }
    server.events.removeAllListeners();

    await router.navigate(-1);
    await waitFor(
      () => expect(rows()).toHaveLength(SHOWN_BY_DEFAULT),
      SLOW_DOM,
    );
  });

  it('"Flagged only" with nothing flagged offers all items', async () => {
    // Real companies from the vendor's outlets: no rule flags them.
    const {user, router} = renderApp('/news?ticker=AAPL&flagged=1');

    expect(
      await screen.findByText(
        'No item in this view was flagged by the rule checks.',
        {},
        SLOW_DOM,
      ),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: 'Show all items'}));
    expect(
      await screen.findByRole('list', {name: 'News items'}, SLOW_DOM),
    ).toBeInTheDocument();
    expect(router.state.location.search).toBe('?date=2026-09-25&ticker=AAPL');
  });

  it('before the rules ran for a date: says so, no badges, legacy duplicates', async () => {
    await openFeed('/news?date=2026-09-18');

    expect(
      screen.getByText("Rule checks haven't run for this date yet."),
    ).toBeInTheDocument();
    expect(rows()).toHaveLength(91);
    expect(
      screen.queryByRole('list', {name: 'Rule checks'}),
    ).not.toBeInTheDocument();
    expect(screen.queryByText('Not checked yet')).not.toBeInTheDocument();
  });

  it('rules-failed: a notice, and unchecked items say so', async () => {
    setScenario('rules-failed');
    await openFeed();

    expect(screen.getByText('Rule checks failed')).toBeInTheDocument();
    expect(
      screen.getByText(/^Rule checks failed after 50 items\./),
    ).toBeInTheDocument();
    expect(screen.getAllByText('Not checked yet').length).toBeGreaterThan(0);
  });

  it('has no axe violations with badges', async () => {
    const {container} = await openFeed('/news?flagged=1&ticker=QVXH&dups=1');

    expect(rows().length).toBeGreaterThan(0);
    await expectNoA11yViolations(container);
  });
});

describe('FeedPage: AI run', {timeout: 30_000}, () => {
  const day = () => db.day('2026-09-25');
  const find = (test: (item: NewsDetailWire) => boolean) => {
    const item = day().items.find(test);
    if (item === undefined) {
      throw new Error('No such item in the mock feed');
    }
    return item;
  };
  const summaryOf = (row: HTMLElement) =>
    row.querySelector('[data-slot="row-summary"]')?.textContent ?? null;

  it('summarizes the AI run in the header', async () => {
    await openFeed('/news?ticker=AAPL');
    const aiRun = day().aiRun;

    expect(
      screen.getByText(
        `AI: ${aiRun?.summarized} summarized · 2 paraphrases · ${aiRun?.fallbacks} lead sentences used · 1 failed`,
      ),
    ).toBeInTheDocument();
  });

  it('shows the summary instead of the excerpt, with its sentiment', async () => {
    const summarized = find(
      item => item.summary !== null && item.sentiment === 'bullish',
    );
    const unsummarized = find(
      item => !item.is_dup && item.rules_checked && item.summary === null,
    );
    await openFeed('/news?dups=1');

    const row = rowOf(summarized.id);
    expect(summaryOf(row)).toBe(`AI summary: ${summarized.summary ?? ''}`);
    expect(within(row).queryByText(summarized.excerpt)).not.toBeInTheDocument();
    expect(within(row).getByText('Sentiment: bullish')).toBeInTheDocument();

    const plain = rowOf(unsummarized.id);
    expect(summaryOf(plain)).toBeNull();
    expect(within(plain).getByText(unsummarized.excerpt)).toBeInTheDocument();
    expect(within(plain).queryByText(/^Sentiment:/)).not.toBeInTheDocument();
  });

  it('shows the AI run badges, and marks paraphrases as duplicates', async () => {
    await openFeed('/news?dups=1');

    for (const [code, text] of [
      ['INJECTION_ATTEMPT', 'INJECTION ATTEMPT'],
      ['UNSUPPORTED_LANGUAGE', 'UNSUPPORTED LANGUAGE'],
    ]) {
      const item = find(entry => entry.reason_codes.includes(code ?? ''));
      expect(badgeTexts(rowOf(item.id))).toContain(text);
    }
    const paraphrase = find(item => item.dup_type === 'paraphrase');
    expect(badgeTexts(rowOf(paraphrase.id))).toContain(
      'DUPLICATE · paraphraseDuplicate (paraphrase)',
    );
  });

  it('says when the AI run has not run for a date', async () => {
    await openFeed('/news?date=2026-09-23&ticker=AAPL');

    expect(
      screen.getByText("AI summaries haven't run for this date yet."),
    ).toBeInTheDocument();
    expect(document.querySelector('[data-slot="row-summary"]')).toBeNull();
  });
});

describe('FeedPage: filters in the URL', {timeout: 30_000}, () => {
  it('filters by a ticker chip, and back undoes it', async () => {
    const {user, router} = await openFeed();
    const [chip] = within(rows()[0] ?? document.body).getAllByRole('button', {
      name: /^Filter by /,
    });
    const ticker = chip?.textContent ?? '';

    await user.click(chip ?? document.body);

    await waitFor(() =>
      expect(router.state.location.search).toContain(`ticker=${ticker}`),
    );
    await waitFor(
      () => expect(rows().length).toBeLessThan(SHOWN_BY_DEFAULT),
      SLOW_DOM,
    );
    for (const row of rows()) {
      expect(
        within(row).getByRole('button', {name: `Filter by ${ticker}`}),
      ).toHaveAttribute('aria-pressed', 'true');
    }
    expect(screen.getByLabelText('Ticker')).toHaveValue(ticker);

    await router.navigate(-1);
    await waitFor(
      () => expect(rows()).toHaveLength(SHOWN_BY_DEFAULT),
      SLOW_DOM,
    );
    expect(screen.getByLabelText('Ticker')).toHaveValue('');
  });

  it('searches 300 ms after the last key, not on every key', async () => {
    const {user, router} = await openFeed();

    await user.type(
      screen.getByLabelText('Search headlines and text'),
      'Zentrality',
    );
    expect(router.state.location.search).not.toContain('q=');

    await waitFor(() =>
      expect(router.state.location.search).toContain('q=Zentrality'),
    );
    await waitFor(
      () => expect(rows().length).toBeLessThan(SHOWN_BY_DEFAULT),
      SLOW_DOM,
    );
    expect(screen.getByText(/matching item/)).toBeInTheDocument();
  });

  it('applies a typed ticker with Enter', async () => {
    const {user, router} = await openFeed();

    await user.type(screen.getByLabelText('Ticker'), 'aapl{Enter}');

    await waitFor(() =>
      expect(router.state.location.search).toContain('ticker=AAPL'),
    );
  });

  it('fills the inputs from a shared link and ignores bad values', async () => {
    await openFeed('/news?date=2026-09-24&q=oracle&ticker=%24%24');

    expect(screen.getByLabelText('Date')).toHaveValue('2026-09-24');
    expect(screen.getByLabelText('Search headlines and text')).toHaveValue(
      'oracle',
    );
    expect(screen.getByLabelText('Ticker')).toHaveValue('');
    expect(
      screen.getByText('Thursday, September 24, 2026'),
    ).toBeInTheDocument();
  });

  it('Back undoes a search', async () => {
    const {user, router} = await openFeed();

    await user.type(
      screen.getByLabelText('Search headlines and text'),
      'oracle',
    );
    // Wait for the filtered list itself (router.state changes first, and
    // the old list stays on screen while the new one loads).
    await waitFor(
      () => expect(rows().length).toBeLessThan(SHOWN_BY_DEFAULT),
      SLOW_DOM,
    );
    await router.navigate(-1);

    await waitFor(
      () =>
        expect(screen.getByLabelText('Search headlines and text')).toHaveValue(
          '',
        ),
      SLOW_DOM,
    );
    expect(rows()).toHaveLength(SHOWN_BY_DEFAULT);
    expect(router.state.location.search).not.toContain('q=');
  });

  it('keeps the space the user just typed after a search runs', async () => {
    const {user, router} = await openFeed();
    const input = screen.getByLabelText('Search headlines and text');

    await user.type(input, 'share ');
    await waitFor(
      () => expect(router.state.location.search).toContain('q=share'),
      SLOW_DOM,
    );
    await user.type(input, 'repurchase');

    expect(input).toHaveValue('share repurchase');
  });

  it('hides duplicates again when the box is unticked', async () => {
    const {user, router} = await openFeed('/news?dups=1');
    expect(rows()).toHaveLength(100);

    await user.click(screen.getByLabelText('Show duplicates'));

    await waitFor(
      () => expect(rows()).toHaveLength(SHOWN_BY_DEFAULT),
      SLOW_DOM,
    );
    expect(router.state.location.search).not.toContain('dups=1');
  });

  it('changes the date once the typing stops (one history entry)', async () => {
    const {router} = await openFeed();
    // Distinct locations visited after the page opened.
    const locations = new Set<string>();
    const unsubscribe = router.subscribe(state => {
      locations.add(state.location.key);
    });
    const dateInput = screen.getByLabelText('Date');

    // What Chrome fires while the year is typed digit by digit.
    for (const value of [
      '0002-09-24',
      '0020-09-24',
      '0202-09-24',
      '2026-09-24',
    ]) {
      fireEvent.change(dateInput, {target: {value}});
    }

    // router.state changes before React renders: wait for the page.
    expect(
      await within(screen.getByRole('main')).findByText(
        'Thursday, September 24, 2026',
        {},
        SLOW_DOM,
      ),
    ).toBeInTheDocument();
    expect(router.state.location.search).toContain('date=2026-09-24');
    expect(locations.size).toBe(1);
    unsubscribe();
  });

  it('a pressed ticker chip clears the ticker filter', async () => {
    const {user, router} = await openFeed('/news?ticker=AAPL');
    const [pressed] = screen.getAllByRole('button', {name: 'Filter by AAPL'});

    await user.click(pressed ?? document.body);

    await waitFor(
      () => expect(router.state.location.search).not.toContain('ticker='),
      SLOW_DOM,
    );
  });

  it('says so when a typed ticker is not valid, and keeps the filter', async () => {
    const {user, router} = await openFeed('/news?ticker=AAPL');

    await user.clear(screen.getByLabelText('Ticker'));
    await user.type(screen.getByLabelText('Ticker'), '1ABC{Enter}');

    expect(screen.getByText('Not a valid ticker')).toBeInTheDocument();
    expect(router.state.location.search).toContain('ticker=AAPL');
  });

  it('says so when nothing matches, and clears the filters', async () => {
    const {user} = renderApp('/news?q=no-such-words');

    expect(
      await screen.findByText('No items match this ticker or search.'),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: 'Show all items'}));
    await waitFor(
      () => expect(rows()).toHaveLength(SHOWN_BY_DEFAULT),
      SLOW_DOM,
    );
  });
});

describe('FeedPage: days without a feed', () => {
  it('explains a weekend and links to Friday', async () => {
    const {user} = renderApp('/news?date=2026-09-26');

    expect(
      await screen.findByRole('heading', {
        name: 'No feed for Saturday, September 26, 2026',
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText('US markets are closed on weekends.'),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole('link', {name: 'Go to Friday, September 25, 2026'}),
    );
    expect(
      await screen.findByRole('list', {name: 'News items'}),
    ).toBeInTheDocument();
  });

  it('explains a future date', async () => {
    renderApp('/news?date=2026-10-05');

    expect(
      await screen.findByText('This date is in the future.'),
    ).toBeInTheDocument();
  });
});

describe('FeedPage: scenarios', () => {
  it('empty: no ingest run yet', async () => {
    setScenario('empty');
    renderApp('/news');

    expect(
      await screen.findByText('No ingest run exists for this date yet.'),
    ).toBeInTheDocument();
  });

  it('running: polls every 30 s, the list grows, polling stops at DONE', async () => {
    // Real polling: fake the timers too (advancing with real time, so the
    // rest of the test still runs).
    vi.useRealTimers();
    vi.useFakeTimers({
      toFake: [
        'Date',
        'setTimeout',
        'clearTimeout',
        'setInterval',
        'clearInterval',
      ],
      shouldAdvanceTime: true,
    });
    vi.setSystemTime(NOW);
    let newsCalls = 0;
    server.events.on('request:start', ({request}) => {
      if (new URL(request.url).pathname === '/api/news') {
        newsCalls += 1;
      }
    });
    setScenario('running');
    await openFeed('/news?dups=1');

    expect(
      screen.getByText("Today's feed is still arriving"),
    ).toBeInTheDocument();
    expect(screen.getByText(/25 items received so far/)).toBeInTheDocument();
    expect(rows()).toHaveLength(25);
    expect(
      screen.getByText('Rule checks are running: 0 items checked so far.'),
    ).toBeInTheDocument();
    expect(screen.getAllByText('Not checked yet')).toHaveLength(25);

    await vi.advanceTimersByTimeAsync(30_000);
    await waitFor(() => expect(rows()).toHaveLength(50), SLOW_DOM);
    expect(
      screen.getByText('Rule checks are running: 25 items checked so far.'),
    ).toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(60_000);
    await waitFor(() => expect(rows()).toHaveLength(100), SLOW_DOM);
    expect(
      screen.getByText('100 items · 16 duplicates shown · updated 05:30 ET'),
    ).toBeInTheDocument();
    const callsAtDone = newsCalls;
    await vi.advanceTimersByTimeAsync(90_000);
    expect(newsCalls).toBe(callsAtDone);
    server.events.removeAllListeners();
  }, 20_000);

  it('failed: error panel with what the run received, and the items', async () => {
    setScenario('failed');
    renderApp('/news?ticker=AAPL');

    expect(
      await screen.findByText('The ingest run for this date failed'),
    ).toBeInTheDocument();
    // The run's count, not the filtered one.
    expect(
      screen.getByText(/40 items arrived before the failure/),
    ).toBeInTheDocument();
  });

  it('server-error: a plain message and a working Retry', async () => {
    setScenario('server-error');
    const {user} = renderApp('/news');

    expect(
      await screen.findByText('The server had a problem. Try again.'),
    ).toBeInTheDocument();
    setScenario('default');
    await user.click(screen.getByRole('button', {name: 'Retry'}));

    expect(
      await screen.findByRole('list', {name: 'News items'}),
    ).toBeInTheDocument();
  });

  it('contract-drift: "Unexpected response from the server"', async () => {
    const consoleError = vi
      .spyOn(console, 'error')
      .mockImplementation(() => undefined);
    setScenario('contract-drift');
    renderApp('/news');

    expect(
      await screen.findByText('Unexpected response from the server.'),
    ).toBeInTheDocument();
    consoleError.mockRestore();
  });

  it('expired-session: loads after one silent refresh', async () => {
    setScenario('expired-session');
    await openFeed();

    expect(rows()).toHaveLength(SHOWN_BY_DEFAULT);
  });

  it('slow: skeleton first, then the list', async () => {
    setScenario('slow');
    renderApp('/news');

    expect(
      await screen.findByText('Loading the feed…', {}, {timeout: 4000}),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole('list', {name: 'News items'}, {timeout: 8000}),
    ).toBeInTheDocument();
  }, 15_000);
});

describe('FeedPage: untrusted text and keyboard', () => {
  it('renders HTML-looking vendor text as plain text', async () => {
    const {container} = await openFeed('/news?q=Umbrix%20Robotics%20reports');

    expect(
      screen.getByText(/<script>alert\("headline"\)<\/script> Umbrix/),
    ).toBeInTheDocument();
    const list = screen.getByRole('list', {name: 'News items'});
    expect(list.querySelector('script, b, img')).toBeNull();
    expect(container.innerHTML).not.toContain('<script>alert');
  });

  it('/ focuses search; j/k move between rows; Enter opens', async () => {
    const {user, router} = await openFeed();
    const links = rows().map(
      row => row.querySelector('a[data-row-link]') ?? document.body,
    );

    await user.keyboard('/');
    expect(screen.getByLabelText('Search headlines and text')).toHaveFocus();
    // Keys typed into the search box are text, not shortcuts.
    await user.keyboard('j');
    expect(screen.getByLabelText('Search headlines and text')).toHaveValue('j');
    await user.clear(screen.getByLabelText('Search headlines and text'));
    await user.click(screen.getByRole('heading', {name: 'News feed'}));

    await user.keyboard('j');
    expect(links[0]).toHaveFocus();
    await user.keyboard('j');
    expect(links[1]).toHaveFocus();
    await user.keyboard('k');
    expect(links[0]).toHaveFocus();
    await user.keyboard('{Enter}');

    await waitFor(() =>
      expect(router.state.location.pathname).toMatch(/^\/news\/\d+$/),
    );
  });

  it('single-key shortcuts can be turned off, and it is remembered', async () => {
    const {user, unmount} = await openFeed();

    await user.click(
      screen.getByRole('button', {name: 'Turn off single-key shortcuts'}),
    );
    await user.keyboard('j');
    expect(document.activeElement?.hasAttribute('data-row-link')).toBe(false);
    await user.keyboard('/');
    expect(
      screen.getByLabelText('Search headlines and text'),
    ).not.toHaveFocus();

    unmount();
    await openFeed();
    expect(
      screen.getByRole('button', {name: 'Turn on single-key shortcuts'}),
    ).toBeInTheDocument();
  });
});
