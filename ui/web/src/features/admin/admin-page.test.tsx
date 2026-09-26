import {screen, within} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {db} from '@/mocks/data/db';
import {expectNoA11yViolations} from '@/test/axe';
import {renderApp, withMockSession} from '@/test/render';

import {passwordProblem, sourceProblem, usernameProblem} from './admin';

const WAIT = {timeout: 10_000};

async function openAdmin() {
  withMockSession('admin1');
  const view = renderApp('/admin');
  await screen.findByRole('table', {name: 'Users'}, WAIT);
  return view;
}

describe('AdminPage', () => {
  it('lists users, sources and the LLM settings', async () => {
    const {container} = await openAdmin();
    expect(document.title).toContain('Administration');
    const users = screen.getByRole('table', {name: 'Users'});
    expect(within(users).getAllByRole('rowheader')).toHaveLength(3);
    expect(
      await screen.findByRole('table', {name: 'Source reputation'}),
    ).toHaveTextContent('pennyrocket.example');
    expect(
      await screen.findByText('main-gpu4gb, embed-gpu4gb, guard-gpu4gb'),
    ).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it('creates a user and checks the form first', async () => {
    const {user} = await openAdmin();
    await user.type(screen.getByLabelText('Username'), 'trader2');
    await user.type(screen.getByLabelText('Password'), 'short');
    await user.click(screen.getByRole('button', {name: 'Create user'}));
    expect(
      await screen.findByText('A password has at least 12 characters.'),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText('Password'), '-but-long-now');
    await user.click(screen.getByRole('button', {name: 'Create user'}));
    expect(
      await screen.findByText('Created trader2 (TRADER).'),
    ).toBeInTheDocument();
    expect(db.adminUsers.get('trader2')?.role).toBe('TRADER');
    await user.type(screen.getByLabelText('Username'), 'trader2');
    await user.type(screen.getByLabelText('Password'), 'another-long-one');
    await user.click(screen.getByRole('button', {name: 'Create user'}));
    expect(
      await screen.findByText('The username is taken'),
    ).toBeInTheDocument();
  });

  it('changes a role and disables a user, never the admin themself', async () => {
    const {user} = await openAdmin();
    expect(screen.getByLabelText('Role of admin1')).toBeDisabled();
    expect(screen.getByRole('button', {name: 'Disable admin1'})).toBeDisabled();
    await user.selectOptions(
      screen.getByLabelText('Role of trader1'),
      'ANALYST',
    );
    expect(
      await screen.findByText('trader1 is now ANALYST.'),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: 'Disable trader1'}));
    expect(
      await screen.findByText('trader1 is now disabled.'),
    ).toBeInTheDocument();
    expect(db.adminUsers.get('trader1')?.disabled).toBe(true);
  });

  it('saves a domain', async () => {
    const {user} = await openAdmin();
    await user.type(screen.getByLabelText('Domain'), 'Bad Domain');
    await user.click(screen.getByRole('button', {name: 'Save domain'}));
    expect(
      await screen.findByText(
        'Enter a domain such as example.com (lower case).',
      ),
    ).toBeInTheDocument();
    await user.clear(screen.getByLabelText('Domain'));
    await user.type(screen.getByLabelText('Domain'), 'news.example');
    await user.selectOptions(screen.getByLabelText('Tier'), 'low');
    await user.click(screen.getByRole('button', {name: 'Save domain'}));
    expect(
      await screen.findByText('Saved news.example: low, 0.5.'),
    ).toBeInTheDocument();
    expect(db.sources.get('news.example')?.tier).toBe('low');
  });

  it('switches the cloud off for the brief', async () => {
    const {user} = await openAdmin();
    const brief = await screen.findByRole('checkbox', {
      name: "Brief's overview",
    });
    expect(brief).toBeChecked();
    await user.click(brief);
    await expect.poll(() => db.cloudSwitches.brief).toBe(false);
    expect(
      await screen.findByRole('checkbox', {name: "Brief's overview"}),
    ).not.toBeChecked();
  });

  it('is for admins only', async () => {
    withMockSession('analyst1');
    renderApp('/admin');
    expect(
      await screen.findByRole(
        'heading',
        {name: "You don't have access to this page"},
        WAIT,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole('link', {name: 'Admin'})).not.toBeInTheDocument();
  });
});

describe('admin form checks', () => {
  it('checks usernames, passwords and domains', () => {
    expect(usernameProblem('trader2')).toBeUndefined();
    expect(usernameProblem('Trader')).toBeDefined();
    expect(passwordProblem('x'.repeat(12))).toBeUndefined();
    expect(passwordProblem('x'.repeat(257))).toBeDefined();
    expect(sourceProblem('sec.gov', '1')).toBeUndefined();
    expect(sourceProblem('sec.gov', '1.5')).toBeDefined();
    expect(sourceProblem('sec.gov', '')).toBeDefined();
    expect(sourceProblem('localhost', '0.5')).toBeDefined();
  });
});
