import {screen, waitFor} from '@testing-library/react';
import {HttpResponse, delay, http} from 'msw';
import {afterEach, describe, expect, it} from 'vitest';

import {apiUrl} from '@/lib/env';
import {server} from '@/mocks/node';
import {expectNoA11yViolations} from '@/test/axe';
import {renderApp, withMockSession} from '@/test/render';

afterEach(() => {
  server.events.removeAllListeners();
});

async function logIn(
  user: ReturnType<typeof renderApp>['user'],
  username: string,
  password: string,
) {
  await user.type(screen.getByLabelText('Username'), username);
  await user.type(screen.getByLabelText('Password'), password);
  await user.keyboard('{Enter}');
}

describe('LoginPage', () => {
  it('shows the form, the notices and the mock users, with no axe issues', async () => {
    const {container} = renderApp('/login');

    expect(
      await screen.findByRole('heading', {name: 'Log in to premarket-ai'}),
    ).toBeInTheDocument();
    expect(
      screen.getByText('SIMULATION: synthetic vendor data'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Decision support only, not investment advice.'),
    ).toBeInTheDocument();
    expect(screen.getByText(/log in as trader1/)).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it('logs in with Enter and goes back to ?next=', async () => {
    const {user, router} = renderApp('/login?next=%2Fnews%3Fticker%3DAAPL');

    await logIn(user, 'trader1', 'demo');

    expect(
      await screen.findByRole('heading', {name: 'News feed'}),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/news');
    expect(router.state.location.search).toBe('?ticker=AAPL');
    expect(screen.getByText('trader1')).toBeInTheDocument();
    expect(screen.getByText('TRADER')).toBeInTheDocument();
    // The Log in button is gone; focus moved to the page, not <body>.
    expect(document.activeElement).toBe(document.getElementById('main'));
  });

  it('never redirects off the site', async () => {
    const {user, router} = renderApp('/login?next=%2F%2Fevil.example');

    await logIn(user, 'analyst1', 'demo');

    await screen.findByRole('heading', {name: 'News feed'});
    expect(router.state.location.pathname).toBe('/');
  });

  it('says so on a wrong password, clears it and focuses it', async () => {
    const {user, router} = renderApp('/login');

    await logIn(user, 'trader1', 'wrong');

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Wrong username or password.',
    );
    const password = screen.getByLabelText('Password');
    expect(password).toHaveValue('');
    expect(password).toHaveFocus();
    expect(screen.getByLabelText('Username')).toHaveValue('trader1');
    expect(router.state.location.pathname).toBe('/login');
  });

  it('asks for both fields before sending anything', async () => {
    let requests = 0;
    server.events.on('request:start', () => {
      requests += 1;
    });
    const {user} = renderApp('/login');
    await screen.findByRole('heading', {name: 'Log in to premarket-ai'});
    const before = requests;

    await user.click(screen.getByRole('button', {name: 'Log in'}));

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Enter your username and password.',
    );
    expect(requests).toBe(before);
  });

  it('disables the button while sending and sends only once', async () => {
    let logins = 0;
    server.use(
      http.post(apiUrl('/auth/login'), async () => {
        logins += 1;
        await delay(150);
        return undefined;
      }),
    );
    const {user} = renderApp('/login');

    await logIn(user, 'trader1', 'demo');
    const button = screen.getByRole('button', {name: 'Logging in…'});
    expect(button).toBeDisabled();
    await user.keyboard('{Enter}');

    await screen.findByRole('heading', {name: 'News feed'});
    expect(logins).toBe(1);
  });

  it('reports an unreachable server plainly', async () => {
    server.use(http.post(apiUrl('/auth/login'), () => HttpResponse.error()));
    const {user} = renderApp('/login');

    await logIn(user, 'trader1', 'demo');

    expect(await screen.findByRole('alert')).toHaveTextContent(
      "Can't reach the server.",
    );
  });

  it('skips the form for a user who is already logged in', async () => {
    withMockSession();
    const {router} = renderApp('/login?next=%2Fnews');

    await waitFor(() => expect(router.state.location.pathname).toBe('/news'));
  });
});
