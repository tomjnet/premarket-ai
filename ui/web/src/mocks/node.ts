import {setupServer} from 'msw/node';

import {handlers} from './handlers';

/** The mock backend in Vitest: the same handlers as the browser worker. */
export const server = setupServer(...handlers);
