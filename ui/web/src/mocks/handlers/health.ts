import {HttpResponse, http} from 'msw';

import {apiUrl} from '@/lib/env';

import {scenarioLatency} from './common';

/** `GET /health`. Public. */
export const healthHandlers = [
  http.get(apiUrl('/health'), async () => {
    await scenarioLatency();
    return HttpResponse.json({status: 'ok'});
  }),
];
