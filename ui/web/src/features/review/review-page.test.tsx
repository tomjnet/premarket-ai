import {screen, waitFor, within} from '@testing-library/react';
import {HttpResponse, http} from 'msw';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import {apiUrl} from '@/lib/env';
import {db} from '@/mocks/data/db';
import {server} from '@/mocks/node';
import {expectNoA11yViolations} from '@/test/axe';
import {renderApp, withMockSession} from '@/test/render';

// Friday 2026-09-25, 09:00 in New York. Only Date is faked; timers are real.
const NOW = new Date('2026-09-25T13:00:00Z');
const WAIT = {timeout: 10_000};

beforeEach(() => {
  vi.useFakeTimers({toFake: ['Date']});
  vi.setSystemTime(NOW);
  db.runItemMs = 0;
});

afterEach(() => {
  vi.useRealTimers();
});

async function openQueue(path = '/review?date=2026-09-24') {
  const view = renderApp(path);
  await screen.findByRole('list', {name: 'Review tasks'}, WAIT);
  return view;
}

function tasks(): HTMLElement[] {
  return within(screen.getByRole('list', {name: 'Review tasks'})).getAllByRole(
    'listitem',
  );
}

describe('ReviewPage: access', () => {
  it('shows traders the 403 page and no nav link', async () => {
    withMockSession('trader1');
    renderApp('/review');
    expect(
      await screen.findByRole(
        'heading',
        {level: 1, name: "You don't have access to this page"},
        WAIT,
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('link', {name: 'Review queue'}),
    ).not.toBeInTheDocument();
  });

  it('shows analysts the nav link and the queue', async () => {
    withMockSession('analyst1');
    await openQueue();
    expect(
      screen.getByRole('link', {name: 'Review queue'}),
    ).toBeInTheDocument();
    expect(document.title).toContain('Review queue');
    expect(tasks().length).toBeGreaterThan(1);
  });
});

describe('ReviewPage: decisions', () => {
  beforeEach(() => withMockSession('analyst1'));

  it('approves the top task: it leaves the queue', async () => {
    const {user} = await openQueue();
    const before = tasks().length;
    const first = tasks()[0];
    if (first === undefined) {
      throw new Error('no task');
    }
    const headline = within(first).getByRole('link').textContent;
    await user.click(within(first).getByRole('button', {name: /^Approve/}));
    await waitFor(() => expect(tasks()).toHaveLength(before - 1), WAIT);
    expect(screen.queryByRole('link', {name: headline ?? ''})).toBeNull();
    expect(
      await screen.findByText(/Verdict approved for VND-/),
    ).toBeInTheDocument();
  });

  it('asks for a verdict and a reason before an override', async () => {
    const {user} = await openQueue();
    const first = tasks()[0];
    if (first === undefined) {
      throw new Error('no task');
    }
    await user.click(
      within(first).getByRole('button', {name: 'Change verdict…'}),
    );
    const form = within(first).getByRole('form', {name: 'Change the verdict'});
    await user.click(
      within(form).getByRole('button', {name: 'Save the new verdict'}),
    );
    expect(within(form).getByRole('alert')).toHaveTextContent(
      'Choose the new verdict.',
    );
    await user.selectOptions(
      within(form).getByLabelText('New verdict'),
      'FAKE',
    );
    await user.click(
      within(form).getByRole('button', {name: 'Save the new verdict'}),
    );
    expect(within(form).getByRole('alert')).toHaveTextContent(
      'Say why you change the verdict',
    );
    await user.type(
      within(form).getByLabelText('Why (required)'),
      'No such dividend was declared.',
    );
    const before = tasks().length;
    await user.click(
      within(form).getByRole('button', {name: 'Save the new verdict'}),
    );
    await waitFor(() => expect(tasks()).toHaveLength(before - 1), WAIT);
    expect(
      await screen.findByText(/Verdict changed for VND-/),
    ).toBeInTheDocument();
  });

  it('says so when someone else decided first (409)', async () => {
    server.use(
      http.post(apiUrl('/review/:id'), () =>
        HttpResponse.json(
          {detail: 'This item was already reviewed'},
          {status: 409},
        ),
      ),
    );
    const {user} = await openQueue();
    const first = tasks()[0];
    if (first === undefined) {
      throw new Error('no task');
    }
    await user.click(within(first).getByRole('button', {name: /^Approve/}));
    expect(
      await within(first).findByText(/Someone reviewed this item already/),
    ).toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const {container} = await openQueue();
    await expectNoA11yViolations(container);
  });
});

describe('ReviewPage: verify runs', () => {
  beforeEach(() => withMockSession('admin1'));

  it('starts a run and follows it to the end', async () => {
    const {user} = await openQueue();
    expect(screen.getByText(/Latest run #\d+ by analyst1/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: 'Verify this date'}));
    expect(
      await screen.findByText(
        /Verification finished: \d+ items, \d+ sent to review\./,
        {},
        WAIT,
      ),
    ).toBeInTheDocument();
    const bar = screen.getByRole('progressbar', {
      name: 'Verification progress',
    });
    expect(bar).toHaveAttribute('value', bar.getAttribute('max'));
    expect(
      await screen.findByText(/Latest run #1 by admin1/, {}, WAIT),
    ).toBeInTheDocument();
  });

  it("explains why a date can't be verified", async () => {
    const {user} = renderApp('/review?date=2026-09-23');
    await screen.findByText(
      'Nothing waiting for review on Wednesday, September 23, 2026.',
      {},
      WAIT,
    );
    await user.click(screen.getByRole('button', {name: 'Verify this date'}));
    expect(
      await screen.findByText(
        "Can't start: The AI run of 2026-09-23 is missing.",
      ),
    ).toBeInTheDocument();
  });
});
