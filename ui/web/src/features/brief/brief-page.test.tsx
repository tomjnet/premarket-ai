import {screen, waitFor, within} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import {db} from '@/mocks/data/db';
import {setScenario} from '@/mocks/scenarios';
import {expectNoA11yViolations} from '@/test/axe';
import {renderApp, withMockSession} from '@/test/render';

import {briefDate, leftOutText, orderedSectors} from './brief';

// Friday 2026-09-25, 09:00 in New York. Only Date is faked; timers are real.
const NOW = new Date('2026-09-25T13:00:00Z');
const WAIT = {timeout: 10_000};

beforeEach(() => {
  vi.useFakeTimers({toFake: ['Date']});
  vi.setSystemTime(NOW);
  db.briefStepMs = 0;
});

afterEach(() => {
  vi.useRealTimers();
});

async function openBrief(path = '/brief?date=2026-09-24') {
  const view = renderApp(path);
  await screen.findByRole('heading', {name: 'Overview'}, WAIT);
  return view;
}

describe('BriefPage', () => {
  it('shows the brief: overview, sections, left-out counts', async () => {
    withMockSession('trader1');
    const {container} = await openBrief();
    expect(document.title).toContain("Today's brief");
    expect(
      screen.getByRole('link', {name: "Today's brief"}),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', {name: /Morning edition \(07:15 ET\)/}),
    ).toBeInTheDocument();
    const top = screen.getByRole('list', {name: 'Top stories'});
    expect(within(top).getAllByRole('listitem').length).toBeGreaterThan(1);
    expect(within(top).getAllByText('VERIFIED').length).toBeGreaterThan(1);
    expect(screen.getByText(/items pending review ·/)).toBeInTheDocument();
    expect(
      screen.getAllByText('Decision support only, not investment advice.')
        .length,
    ).toBeGreaterThan(0);
    // No FAKE or MISLEADING item: every badge says VERIFIED or UNCONFIRMED.
    expect(screen.queryByText('FAKE')).toBeNull();
    await expectNoA11yViolations(container);
  });

  it('moves focus to an item from its citation', async () => {
    withMockSession('trader1');
    const {user} = await openBrief();
    const [citation] = screen.getAllByRole('button', {name: /^Item \d+$/});
    if (citation === undefined) {
      throw new Error('no citation');
    }
    await user.click(citation);
    expect(document.activeElement?.id).toMatch(/^brief-item-\d+$/);
  });

  it('suggests a watchlist when there is none', async () => {
    withMockSession('trader1');
    await openBrief();
    expect(
      screen.getByRole('link', {name: 'Set up your watchlist'}),
    ).toHaveAttribute('href', '/watchlist');
  });

  it("lists the watchlist's stories", async () => {
    withMockSession('trader1');
    db.watchlists.set('trader1', {tickers: [], sectors: ['Energy']});
    await openBrief();
    const mine = screen.getByRole('list', {name: 'Your watchlist'});
    expect(within(mine).getAllByRole('listitem').length).toBeGreaterThan(0);
  });

  it('says when a date has no brief yet', async () => {
    withMockSession('trader1');
    renderApp('/brief?date=2026-09-23');
    expect(
      await screen.findByText(/No brief for 2026-09-23 yet/, {}, WAIT),
    ).toBeInTheDocument();
  });

  it('follows a brief being written', async () => {
    setScenario('brief-writing');
    db.briefStepMs = 150;
    withMockSession('trader1');
    renderApp('/brief?date=2026-09-24');
    expect(
      await screen.findByText(/is being written/, {}, WAIT),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole('heading', {name: 'Overview'}, WAIT),
    ).toBeInTheDocument();
    expect(screen.queryByText(/is being written/)).toBeNull();
  });

  it('shows a failed brief', async () => {
    setScenario('brief-failed');
    withMockSession('trader1');
    renderApp('/brief?date=2026-09-24');
    expect(
      await screen.findByText(/An analyst can write it again/, {}, WAIT),
    ).toBeInTheDocument();
  });

  it('lets analysts write it again, not traders', async () => {
    withMockSession('trader1');
    await openBrief();
    expect(
      screen.queryByRole('button', {name: 'Write the brief now'}),
    ).toBeNull();
  });

  it('writes a refresh for an analyst', async () => {
    withMockSession('analyst1');
    const {user} = await openBrief();
    await user.click(
      screen.getByRole('button', {name: 'Refresh with reviewed items'}),
    );
    await waitFor(
      () =>
        expect(
          screen.getByRole('heading', {name: /Refreshed at 09:00 ET/}),
        ).toBeInTheDocument(),
      WAIT,
    );
  });
});

describe('brief rules', () => {
  it('reads the date from the URL, never a future one', () => {
    const today = '2026-09-25';
    expect(briefDate(new URLSearchParams('date=2026-09-24'), today)).toBe(
      '2026-09-24',
    );
    expect(briefDate(new URLSearchParams('date=2026-09-26'), today)).toBe(
      today,
    );
    expect(briefDate(new URLSearchParams('date=x'), today)).toBe(today);
  });

  it('counts what was left out, and orders followed sectors first', () => {
    const counts = {
      verified: 1,
      unconfirmed: 0,
      unverified: 0,
      pendingReview: 1,
      misleading: 2,
      fake: 3,
      failed: 1,
      new: 0,
    };
    expect(leftOutText(counts)).toBe(
      '1 item pending review · 2 misleading · 3 fake · 1 not checked (failed)',
    );
    const brief = {
      sectors: [
        {name: 'Energy', items: [1]},
        {name: 'Financials', items: [2]},
      ],
    } as Parameters<typeof orderedSectors>[0];
    expect(orderedSectors(brief, ['Financials']).map(s => s.name)).toEqual([
      'Financials',
      'Energy',
    ]);
  });
});
