import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {expectNoA11yViolations} from '@/test/axe';

import {MockStartError} from './mock-start-error';

describe('MockStartError', () => {
  it('explains why the app did not load instead of a blank page', async () => {
    const {container} = render(<MockStartError />);

    expect(
      screen.getByRole('heading', {name: "The mock backend didn't start"}),
    ).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('service worker');
    await expectNoA11yViolations(container);
  });
});
