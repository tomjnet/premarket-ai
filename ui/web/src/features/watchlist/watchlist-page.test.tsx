import {screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {db} from '@/mocks/data/db';
import {expectNoA11yViolations} from '@/test/axe';
import {renderApp, withMockSession} from '@/test/render';

import {parseTickers} from './watchlist';

const WAIT = {timeout: 10_000};

describe('WatchlistPage', () => {
  it('saves tickers and sectors', async () => {
    withMockSession('trader1');
    const {user, container} = renderApp('/watchlist');
    const tickers = await screen.findByLabelText('Tickers', {}, WAIT);
    expect(document.title).toContain('My watchlist');
    await user.type(tickers, 'aapl msft, AAPL');
    await user.click(screen.getByLabelText('Energy'));
    await user.click(screen.getByRole('button', {name: 'Save watchlist'}));
    expect(
      await screen.findByText('Watchlist saved: 2 tickers, 1 sectors.'),
    ).toBeInTheDocument();
    expect(tickers).toHaveValue('AAPL, MSFT');
    expect(db.watchlists.get('trader1')).toEqual({
      tickers: ['AAPL', 'MSFT'],
      sectors: ['Energy'],
    });
    await expectNoA11yViolations(container);
  });

  it("shows the server's reason for a ticker it doesn't know", async () => {
    withMockSession('trader1');
    const {user} = renderApp('/watchlist');
    await user.type(await screen.findByLabelText('Tickers', {}, WAIT), 'QVXH');
    await user.click(screen.getByRole('button', {name: 'Save watchlist'}));
    expect(
      await screen.findByText('Not in the SEC ticker registry: QVXH'),
    ).toBeInTheDocument();
  });

  it('checks the form before sending', async () => {
    withMockSession('trader1');
    const {user} = renderApp('/watchlist');
    await user.type(await screen.findByLabelText('Tickers', {}, WAIT), 'A;B!');
    await user.click(screen.getByRole('button', {name: 'Save watchlist'}));
    expect(
      await screen.findByText('"B!" is not a ticker.'),
    ).toBeInTheDocument();
    expect(db.watchlists.size).toBe(0);
  });
});

describe('parseTickers', () => {
  it('splits, upper-cases and de-duplicates', () => {
    expect(parseTickers(' brk.b, aapl;AAPL ')).toEqual({
      tickers: ['BRK.B', 'AAPL'],
    });
    expect(parseTickers('')).toEqual({tickers: []});
    expect(
      parseTickers(
        Array.from({length: 26}, (_, i) => `T${String(i)}`).join(' '),
      ),
    ).toEqual({problem: 'Follow at most 25 tickers.'});
  });
});
