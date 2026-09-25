import '@testing-library/jest-dom/vitest';

import {cleanup} from '@testing-library/react';
import {afterAll, afterEach, beforeAll} from 'vitest';

import {server} from '@/mocks/node';

// A request without a handler fails the test, so a path typo can't pass.
beforeAll(() => server.listen({onUnhandledRequest: 'error'}));

afterEach(() => {
  cleanup();
  server.resetHandlers();
});

afterAll(() => server.close());
