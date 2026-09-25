import {apiClient} from './client';
import type {CallOptions} from './client';
import {healthSchema} from './schemas/health';
import type {Health} from './schemas/health';

/** `GET /health`. Public: no token, no refresh. */
export function getHealth({
  client = apiClient,
  signal,
}: CallOptions = {}): Promise<Health> {
  return client.request({
    path: '/health',
    schema: healthSchema,
    auth: false,
    signal,
  });
}
