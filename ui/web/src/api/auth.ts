import {z} from 'zod';

import {apiClient} from './client';
import type {CallOptions, Session} from './client';
import {HttpError} from './errors';
import {authSessionSchema} from './schemas/auth';

/**
 * `POST /auth/login`. Rejects with `HttpError` 401 on a wrong username or
 * password.
 */
export async function login(
  username: string,
  password: string,
  {client = apiClient, signal}: CallOptions = {},
): Promise<Session> {
  const auth = await client.request({
    method: 'POST',
    path: '/auth/login',
    form: {username, password},
    schema: authSessionSchema,
    auth: false,
    signal,
  });
  return client.setSession(auth, 'login');
}

/**
 * Restores the session from the refresh cookie on app start. Resolves to
 * undefined when there is no valid session (`401`).
 */
export async function restoreSession({
  client = apiClient,
}: CallOptions = {}): Promise<Session | undefined> {
  try {
    return await client.refresh();
  } catch (error: unknown) {
    if (error instanceof HttpError && error.status === 401) {
      return undefined;
    }
    throw error;
  }
}

/** `POST /auth/logout` (`204`). The local session is cleared either way. */
export async function logout({
  client = apiClient,
}: CallOptions = {}): Promise<void> {
  try {
    await client.request({
      method: 'POST',
      path: '/auth/logout',
      schema: z.undefined(),
      auth: false,
    });
  } finally {
    client.clearSession('logout');
  }
}
