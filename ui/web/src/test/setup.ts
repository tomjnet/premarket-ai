import '@/lib/zod-setup';
import '@testing-library/jest-dom/vitest';

import {cleanup} from '@testing-library/react';
import {afterAll, afterEach, beforeAll} from 'vitest';

import {db} from '@/mocks/data/db';
import {server} from '@/mocks/node';
import {setScenario} from '@/mocks/scenarios';

// A request without a handler fails the test, so a path typo can't pass.
beforeAll(() => server.listen({onUnhandledRequest: 'error'}));

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  window.localStorage.clear();
  server.resetHandlers();
  db.reset();
  setScenario('default');
});

afterAll(() => server.close());
