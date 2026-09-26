import {screen, waitFor, within} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import type {Alert} from '@/api/schemas/ops';
import {db} from '@/mocks/data/db';
import {pushAlert} from '@/mocks/handlers/ops';
import {expectNoA11yViolations} from '@/test/axe';
import {renderApp, withMockSession} from '@/test/render';

import {applyAlertEvent, chartMax, percent, usd} from './ops';

// Friday 2026-09-25, 09:00 in New York. Only Date is faked.
const NOW = new Date('2026-09-25T13:00:00Z');
const WAIT = {timeout: 10_000};

beforeEach(() => {
  vi.useFakeTimers({toFake: ['Date']});
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('ScorecardPage', () => {
  it('shows the SLA panel, the days and the weekly summary', async () => {
    withMockSession('analyst1');
    const {container} = renderApp('/scorecard');
    expect(
      await screen.findByText('Every SLA green (4 checks).', {}, WAIT),
    ).toBeInTheDocument();
    const table = await screen.findByRole(
      'table',
      {name: 'Vendor scorecard by day'},
      WAIT,
    );
    const rows = within(table).getAllByRole('row');
    expect(rows.length).toBeGreaterThan(2);
    expect(within(table).getAllByRole('rowheader')[0]).toHaveTextContent(
      '2026-09-25',
    );
    expect(
      screen.getByRole('img', {
        name: 'Received and billable items per day against the contract',
      }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/billable items a day against 100 contracted/),
    ).toBeInTheDocument();
    expect(document.title).toContain('Vendor scorecard');
    await expectNoA11yViolations(container);
  });

  it('downloads the CSV', async () => {
    withMockSession('admin1');
    const created = vi.fn(() => 'blob:scorecard');
    const revoked = vi.fn();
    vi.stubGlobal(
      'URL',
      Object.assign(URL, {
        createObjectURL: created,
        revokeObjectURL: revoked,
      }),
    );
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined);
    const {user} = renderApp('/scorecard');
    await user.click(
      await screen.findByRole('button', {name: 'Download CSV'}, WAIT),
    );
    await waitFor(() => expect(click).toHaveBeenCalled());
    expect(created).toHaveBeenCalled();
    expect(revoked).toHaveBeenCalledWith('blob:scorecard');
    click.mockRestore();
    vi.unstubAllGlobals();
  });

  it('shows traders the 403 page and no nav link', async () => {
    withMockSession('trader1');
    renderApp('/scorecard');
    expect(
      await screen.findByRole(
        'heading',
        {name: "You don't have access to this page"},
        WAIT,
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('link', {name: 'Vendor scorecard'}),
    ).not.toBeInTheDocument();
  });
});

describe('OpsBanners', () => {
  it('shows analysts the firing alerts, and hides one', async () => {
    pushAlert({
      key: 'sla:brief:2026-09-25',
      title: 'Brief of 2026-09-25 not published by 07:30 ET',
      severity: 'critical',
      status: 'firing',
      detail: 'morning brief missing',
      source: 'scheduler',
    });
    withMockSession('analyst1');
    const {user} = renderApp('/news');
    const list = await screen.findByRole(
      'list',
      {name: 'Operations alerts'},
      WAIT,
    );
    expect(list).toHaveTextContent('not published by 07:30 ET');
    await user.click(
      screen.getByRole('button', {
        name: 'Hide: Brief of 2026-09-25 not published by 07:30 ET',
      }),
    );
    expect(
      screen.queryByRole('list', {name: 'Operations alerts'}),
    ).not.toBeInTheDocument();
  });

  it("doesn't show traders the alerts, but shows the budget cap", async () => {
    pushAlert({
      key: 'grafana:WorkerDown:x',
      title: 'No verification worker is running',
      severity: 'critical',
      status: 'firing',
      detail: '',
      source: 'grafana',
    });
    db.cloudSpendUsd = 21;
    withMockSession('trader1');
    renderApp('/news');
    expect(
      await screen.findByText('Cloud budget reached, running local.', {}, WAIT),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('list', {name: 'Operations alerts'}),
    ).not.toBeInTheDocument();
  });

  it('shows analysts the 80% budget warning', async () => {
    db.cloudSpendUsd = 17;
    withMockSession('analyst1');
    renderApp('/news');
    expect(
      await screen.findByText('Cloud budget at 85% this month.', {}, WAIT),
    ).toBeInTheDocument();
  });
});

function alert(key: string, status: Alert['status'], id: string): Alert {
  return {
    id,
    key,
    title: key,
    severity: 'warning',
    status,
    detail: '',
    source: 'scheduler',
    at: '2026-09-25T11:00:00Z',
  };
}

describe('ops helpers', () => {
  it('keeps the latest firing alert of each key', () => {
    let alerts = applyAlertEvent([], {
      type: 'snapshot',
      alerts: [alert('a', 'firing', '1-0'), alert('b', 'resolved', '2-0')],
    });
    expect(alerts.map(a => a.key)).toEqual(['a']);
    alerts = applyAlertEvent(alerts, {
      type: 'alert',
      alert: alert('c', 'firing', '3-0'),
    });
    expect(alerts.map(a => a.key)).toEqual(['c', 'a']);
    alerts = applyAlertEvent(alerts, {
      type: 'alert',
      alert: alert('a', 'resolved', '4-0'),
    });
    expect(alerts.map(a => a.key)).toEqual(['c']);
  });

  it('formats shares, dollars and the chart range', () => {
    expect(percent(0.125)).toBe('12.5%');
    expect(percent(0.2)).toBe('20%');
    expect(usd(0.0412)).toBe('$0.04');
    expect(chartMax([])).toBe(10);
  });
});
