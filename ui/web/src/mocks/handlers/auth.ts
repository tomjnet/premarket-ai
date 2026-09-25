import {HttpResponse, http} from 'msw';

import {apiUrl} from '@/lib/env';

import {db} from '../data/db';
import {activeScenario} from '../scenarios';

import {scenarioLatency, unauthorized, validationError} from './common';

/** `POST /auth/login`, `/auth/refresh` and `/auth/logout`. */
export const authHandlers = [
  http.post(apiUrl('/auth/login'), async ({request}) => {
    await scenarioLatency();
    const form = new URLSearchParams(await request.text());
    const username = form.get('username');
    const password = form.get('password');
    if (username === null || password === null) {
      return validationError({
        loc: ['body', username === null ? 'username' : 'password'],
        msg: 'Field required',
        type: 'missing',
      });
    }
    const token = db.login(username, password);
    if (token === undefined) {
      return unauthorized('Incorrect username or password');
    }
    return HttpResponse.json(token);
  }),

  http.post(apiUrl('/auth/refresh'), async () => {
    await scenarioLatency();
    if (activeScenario() === 'logged-out') {
      db.logout();
    }
    const token = db.refresh();
    return token === undefined ? unauthorized() : HttpResponse.json(token);
  }),

  http.post(apiUrl('/auth/logout'), async () => {
    await scenarioLatency();
    db.logout();
    return new HttpResponse(null, {status: 204});
  }),
];
