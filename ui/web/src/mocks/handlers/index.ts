import {authHandlers} from './auth';
import {chatHandlers} from './chat';
import {healthHandlers} from './health';
import {newsHandlers} from './news';
import {verifyHandlers} from './verify';

/** Every mock endpoint of the contract. */
export const handlers = [
  ...authHandlers,
  ...newsHandlers,
  ...chatHandlers,
  ...verifyHandlers,
  ...healthHandlers,
];
