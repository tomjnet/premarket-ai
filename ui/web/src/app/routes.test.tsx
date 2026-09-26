import {act, screen, waitFor, within} from '@testing-library/react';
import {HttpResponse, http} from 'msw';
import {afterEach, describe, expect, it, vi} from 'vitest';

import {AppShell} from '@/components/layout/root-layout';
import {ErrorPage} from '@/components/pages/error-page';
import {RequireAuth, RequireRole} from '@/features/auth/require-auth';
import {apiUrl} from '@/lib/env';
import {SCENARIOS, SCENARIO_STORAGE_KEY} from '@/lib/mock-scenarios';
import {formatLongDate, todayInNewYork} from '@/lib/time';
import {db} from '@/mocks/data/db';
import {server} from '@/mocks/node';
import {setScenario} from '@/mocks/scenarios';
import {expectNoA11yViolations} from '@/test/axe';
import {renderApp, withMockSession} from '@/test/render';

afterEach(() => {
  server.events.removeAllListeners();
});

describe('route guard and session restore', () => {
  it('sends a visitor without a session to login, keeping the target', async () => {
    const {router} = renderApp('/news?ticker=AAPL');

    expect(screen.getByRole('status')).toHaveTextContent(
      'Restoring your session…',
    );
    await screen.findByRole('heading', {name: 'Log in to premarket-ai'});
    expect(router.state.location.pathname).toBe('/login');
    expect(router.state.location.search).toBe(
      `?next=${encodeURIComponent('/news?ticker=AAPL')}`,
    );
    expect(screen.queryByText(/session expired/)).not.toBeInTheDocument();
  });

  it('restores the session on start (a reload keeps you logged in)', async () => {
    withMockSession('admin1');
    renderApp('/news');

    expect(
      await screen.findByRole('heading', {name: 'News feed'}),
    ).toBeInTheDocument();
    expect(screen.getByText('admin1')).toBeInTheDocument();
    expect(screen.getByText('ADMIN')).toBeInTheDocument();
  });

  it('says the session expired when this tab had one that is gone', async () => {
    window.sessionStorage.setItem('premarket-ai.had-session', '1');
    renderApp('/');

    await screen.findByRole('heading', {name: 'Log in to premarket-ai'});
    expect(screen.getByRole('status')).toHaveTextContent(
      'Your session expired. Please log in again.',
    );
  });
});

describe('app shell', () => {
  it('shows notices, trading date, user and backend status', async () => {
    withMockSession();
    // A weekend date: the shell with a short page, so axe stays fast.
    const {container} = renderApp('/news?date=2026-09-26');

    await screen.findByRole('heading', {name: /No feed for/});
    expect(
      screen.getByText('SIMULATION: synthetic vendor data'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Decision support only, not investment advice.'),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole('banner')).getByText(
        formatLongDate(todayInNewYork()),
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', {name: 'Skip to main content'}),
    ).toHaveAttribute('href', '#main');
    expect(await screen.findByText('Backend: ok')).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it('shows the backend as unreachable when /health fails', async () => {
    server.use(http.get(apiUrl('/health'), () => HttpResponse.error()));
    renderApp('/login');

    expect(await screen.findByText('Backend: unreachable')).toBeInTheDocument();
  });

  it('shows the MOCK API tag and the current scenario', async () => {
    window.sessionStorage.setItem(SCENARIO_STORAGE_KEY, 'failed');
    const {user} = renderApp('/login');

    expect(await screen.findByText('MOCK API')).toBeInTheDocument();
    const switcher = screen.getByLabelText('Mock scenario');
    expect(switcher).toHaveValue('failed');
    expect(screen.getAllByRole('option')).toHaveLength(SCENARIOS.length);
    // Changing the select alone doesn't reload; Apply does.
    const apply = screen.getByRole('button', {name: 'Apply (reloads)'});
    expect(apply).toBeDisabled();
    await user.selectOptions(switcher, 'slow');
    expect(apply).toBeEnabled();
  });

  it('logs out: back to login, no notice, session gone on the server', async () => {
    withMockSession();
    const {user, router} = renderApp('/');
    await screen.findByRole('heading', {name: 'News feed'});

    await user.click(screen.getByRole('button', {name: 'Log out'}));

    await screen.findByRole('heading', {name: 'Log in to premarket-ai'});
    expect(router.state.location.pathname).toBe('/login');
    expect(screen.queryByText(/session expired/)).not.toBeInTheDocument();
    expect(db.refresh()).toBeUndefined();
  });

  it('logs out locally even when the logout request fails', async () => {
    withMockSession();
    server.use(http.post(apiUrl('/auth/logout'), () => HttpResponse.error()));
    const {user} = renderApp('/');
    await screen.findByRole('heading', {name: 'News feed'});

    await user.click(screen.getByRole('button', {name: 'Log out'}));

    expect(
      await screen.findByRole('heading', {name: 'Log in to premarket-ai'}),
    ).toBeInTheDocument();
  });

  it('ends on login with a notice when the proactive refresh gets 401', async () => {
    db.tokenTtlS = 2;
    withMockSession();
    // A light page (a weekend, no rows): with the whole suite running in
    // parallel, re-rendering 100 feed rows after every 1 s refresh starved
    // this test's timers.
    const {router} = renderApp('/news?date=2026-09-26');
    await screen.findByRole('heading', {name: 'News feed'});

    setScenario('logged-out');

    await screen.findByRole(
      'heading',
      {name: 'Log in to premarket-ai'},
      {
        timeout: 3000,
      },
    );
    expect(screen.getByRole('status')).toHaveTextContent(
      'Your session expired. Please log in again.',
    );
    expect(router.state.location.search).toBe(
      `?next=${encodeURIComponent('/news?date=2026-09-26')}`,
    );
  });

  it('offers a retry when the backend is unreachable at start', async () => {
    withMockSession();
    server.use(
      http.post(apiUrl('/auth/refresh'), () => HttpResponse.error(), {
        once: true,
      }),
    );
    // StrictMode starts the restore twice; both share one refresh request.
    const {user} = renderApp('/');

    expect(
      await screen.findByText(
        "Can't reach the server to restore your session.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/session expired/)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: 'Try again'}));

    expect(
      await screen.findByRole('heading', {name: 'News feed'}),
    ).toBeInTheDocument();
  });

  it('goes to login with a notice when the session expires', async () => {
    withMockSession();
    const {client, router, queryClient} = renderApp('/news');
    await screen.findByRole('heading', {name: 'News feed'});
    queryClient.setQueryData(['news', 'private'], {from: 'trader1'});

    act(() => client.clearSession('expired'));

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Your session expired. Please log in again.',
    );
    expect(router.state.location.search).toBe('?next=%2Fnews');
    // No data from the old session is kept.
    expect(queryClient.getQueryData(['news', 'private'])).toBeUndefined();
  });

  it('refreshes the token before it expires', async () => {
    db.tokenTtlS = 2;
    withMockSession();
    const {client} = renderApp('/');
    await screen.findByRole('heading', {name: 'News feed'});
    const first = client.getSession()?.accessToken;

    await waitFor(
      () => expect(client.getSession()?.accessToken).not.toBe(first),
      {timeout: 3000},
    );
    expect(client.getSession()).toBeDefined();
  });
});

describe('403, 404 and crashes', () => {
  it('shows 404 for an unknown route, with a way back', async () => {
    withMockSession();
    renderApp('/no-such-page');

    expect(
      await screen.findByRole('heading', {name: 'Page not found'}),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', {name: 'Back to the news feed'}),
    ).toHaveAttribute('href', '/');
    expect(document.title).toBe('Page not found · premarket-ai');
  });

  const adminRoutes = [
    {
      element: <RequireAuth />,
      children: [
        {
          element: <AppShell />,
          children: [
            {
              element: <RequireRole roles={['ADMIN']} />,
              children: [{path: '/admin', element: <p>Admin area</p>}],
            },
          ],
        },
      ],
    },
  ];

  it('shows 403 when the role may not see the page', async () => {
    withMockSession('trader1');
    const {container} = renderApp('/admin', adminRoutes);

    expect(
      await screen.findByRole('heading', {
        name: "You don't have access to this page",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText('Admin area')).not.toBeInTheDocument();
    expect(document.title).toBe(
      "You don't have access to this page · premarket-ai",
    );
    await expectNoA11yViolations(container);
  });

  it('announces the new page to screen readers after navigation', async () => {
    withMockSession();
    const {router} = renderApp('/');
    await screen.findByRole('heading', {name: 'News feed'});
    const announcer = document.querySelector(
      '[aria-live="polite"][aria-atomic="true"]',
    );
    // Silent on the first page.
    expect(announcer?.textContent).toBe('');

    await act(() => router.navigate('/no-such-page'));

    await waitFor(() =>
      expect(announcer?.textContent).toBe('Page not found · premarket-ai'),
    );
  });

  it('lets the right role through', async () => {
    withMockSession('admin1');
    renderApp('/admin', adminRoutes);

    expect(await screen.findByText('Admin area')).toBeInTheDocument();
  });

  it('shows an error page, with the notices, when a page crashes', async () => {
    const consoleError = vi
      .spyOn(console, 'error')
      .mockImplementation(() => undefined);
    function Broken(): never {
      throw new Error('boom');
    }
    renderApp('/', [
      {path: '/', element: <Broken />, errorElement: <ErrorPage />},
    ]);

    expect(
      await screen.findByRole('heading', {name: 'Something went wrong'}),
    ).toBeInTheDocument();
    expect(
      screen.getByText('SIMULATION: synthetic vendor data'),
    ).toBeInTheDocument();
    consoleError.mockRestore();
  });
});
