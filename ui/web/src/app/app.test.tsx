import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {App} from './app';

describe('App', () => {
  it('starts on the login page when there is no session', async () => {
    render(<App />);

    expect(
      await screen.findByRole('heading', {name: 'Log in to premarket-ai'}),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe('/login');
  });
});
