import {setupWorker} from 'msw/browser';

import {handlers} from './handlers';

export {prepareMockBackend} from './page-setup';

/** The mock backend in the browser. Started only from main.tsx in mock mode. */
export const worker = setupWorker(...handlers);
