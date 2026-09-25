import {render, screen} from '@testing-library/react';
import {userEvent} from '@testing-library/user-event';
import {describe, expect, it} from 'vitest';

import {expectNoA11yViolations} from '@/test/axe';

import {App} from './app';

describe('App placeholder', () => {
  it('shows the simulation ribbon and the compliance notice', () => {
    render(<App />);

    expect(
      screen.getByText('SIMULATION: synthetic vendor data'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Decision support only, not investment advice.'),
    ).toBeInTheDocument();
  });

  it('toggles the toolchain list with the keyboard', async () => {
    const user = userEvent.setup();
    render(<App />);
    const toggle = screen.getByRole('button', {name: 'Show toolchain'});

    await user.tab();
    expect(toggle).toHaveFocus();
    await user.keyboard('{Enter}');

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('list')).toHaveTextContent('MSW mock backend');
    expect(
      screen.getByRole('button', {name: 'Hide toolchain'}),
    ).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const {container} = render(<App />);

    await expectNoA11yViolations(container);
  });
});
