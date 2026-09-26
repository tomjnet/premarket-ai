import {authHandlers} from './auth';
import {chatHandlers} from './chat';
import {healthHandlers} from './health';
import {newsHandlers} from './news';

/** Every mock endpoint of the contract. */
export const handlers = [
  ...authHandlers,
  ...newsHandlers,
  ...chatHandlers,
  ...healthHandlers,
];
