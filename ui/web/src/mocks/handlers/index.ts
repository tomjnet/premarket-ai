import {authHandlers} from './auth';
import {briefHandlers} from './brief';
import {chatHandlers} from './chat';
import {healthHandlers} from './health';
import {newsHandlers} from './news';
import {opsHandlers} from './ops';
import {verifyHandlers} from './verify';

/** Every mock endpoint of the contract. */
export const handlers = [
  ...authHandlers,
  ...newsHandlers,
  ...chatHandlers,
  ...verifyHandlers,
  ...briefHandlers,
  ...opsHandlers,
  ...healthHandlers,
];
