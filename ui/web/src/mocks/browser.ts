import {setupWorker} from 'msw/browser';

import {handlers} from './handlers';

/** The mock backend in the browser. Started only from main.tsx in mock mode. */
export const worker = setupWorker(...handlers);
