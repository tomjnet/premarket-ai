import {http, HttpResponse} from 'msw';
import {describe, expect, it} from 'vitest';

import {server} from './node';

describe('MSW in Vitest', () => {
  it('answers a relative fetch, as the app will call /api/...', async () => {
    server.use(http.get('/api/ping', () => HttpResponse.json({pong: true})));

    const response = await fetch('/api/ping');

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({pong: true});
  });
});
