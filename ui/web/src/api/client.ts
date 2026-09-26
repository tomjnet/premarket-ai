import type {z} from 'zod';

import {ENV, apiUrl} from '@/lib/env';

import {
  ContractError,
  HttpError,
  NetworkError,
  SessionExpiredError,
} from './errors';
import {authSessionSchema} from './schemas/auth';
import type {AuthSession, AuthUser} from './schemas/auth';
import {errorBodySchema} from './schemas/errors';

/** Network failures and timeouts after this long show the generic error. */
export const REQUEST_TIMEOUT_MS = 15_000;

/** The logged-in user. Kept in memory only, never in browser storage. */
export interface Session {
  accessToken: string;
  /** When the access token expires, in epoch milliseconds. */
  expiresAt: number;
  user: AuthUser;
}

/** Why the session changed, for listeners (the session context). */
export type SessionChange = 'login' | 'refresh' | 'logout' | 'expired';

type SessionListener = (
  session: Session | undefined,
  change: SessionChange,
) => void;

/** One call to the backend. */
export interface RequestOptions<T> {
  method?: 'GET' | 'POST';
  /** Contract path, for example `/news` or `/news/42`. */
  path: string;
  /** Query parameters; `undefined` values are left out. */
  query?: Record<string, string | undefined>;
  /** Sent as `application/x-www-form-urlencoded` (OAuth2 password flow). */
  form?: Record<string, string>;
  /** Parses the `2xx` body into the UI model. */
  schema: z.ZodType<T>;
  /**
   * Attach the access token and recover from a `401` by refreshing once.
   * Off for the auth endpoints themselves. Default: true.
   */
  auth?: boolean;
  /** Cancels the call (TanStack Query passes one); rejects with AbortError. */
  signal?: AbortSignal;
}

/** Options every API function accepts. */
export interface CallOptions {
  /** Defaults to the app's `apiClient`; tests pass their own. */
  client?: ApiClient;
  signal?: AbortSignal;
}

interface ClientOptions {
  baseUrl: string;
  timeoutMs?: number;
  now?: () => number;
}

interface RawResponse {
  status: number;
  body: unknown;
}

/**
 * fetch wrapper for the backend contract: base URL, bearer token, one shared
 * refresh on `401` followed by one retry, a timeout, typed errors, and zod
 * parsing of every response.
 */
export class ApiClient {
  private session: Session | undefined = undefined;
  private refreshing: Promise<Session> | undefined = undefined;
  // Bumped on login and on every clear, so a refresh that was in flight
  // meanwhile can't bring an old session back.
  private generation = 0;
  private readonly listeners = new Set<SessionListener>();
  private readonly timeoutMs: number;
  private readonly now: () => number;

  constructor(private readonly options: ClientOptions) {
    this.timeoutMs = options.timeoutMs ?? REQUEST_TIMEOUT_MS;
    this.now = options.now ?? Date.now;
  }

  getSession(): Session | undefined {
    return this.session;
  }

  /** Calls `listener` on every session change; returns the unsubscribe. */
  subscribe(listener: SessionListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /** Stores a login or refresh response as the current session. */
  setSession(auth: AuthSession, change: 'login' | 'refresh'): Session {
    if (change === 'login') {
      this.generation += 1;
    }
    this.session = {
      accessToken: auth.accessToken,
      expiresAt: this.now() + auth.expiresInS * 1000,
      user: auth.user,
    };
    this.notify(change);
    return this.session;
  }

  clearSession(change: 'logout' | 'expired'): void {
    this.generation += 1;
    this.session = undefined;
    this.notify(change);
  }

  /**
   * Gets a new access token with the refresh cookie. Concurrent callers
   * share one request. Rejects with `HttpError` 401 when there is no valid
   * session, after ending the current one (if any). If the user logged out
   * or in while it was running, its result is dropped and it rejects with
   * `SessionExpiredError`.
   */
  refresh(): Promise<Session> {
    this.refreshing ??= this.requestRefresh().finally(() => {
      this.refreshing = undefined;
    });
    return this.refreshing;
  }

  async request<T>(options: RequestOptions<T>): Promise<T> {
    const useAuth = options.auth ?? true;
    const token = useAuth ? this.session?.accessToken : undefined;
    const response = await this.send(options, token);
    if (response.status !== 401 || !useAuth) {
      return this.parse(options, response);
    }
    await this.recoverFrom401(token);
    const retry = await this.send(options, this.session?.accessToken);
    if (retry.status === 401) {
      this.expireSession();
      throw new SessionExpiredError();
    }
    return this.parse(options, retry);
  }

  private async requestRefresh(): Promise<Session> {
    const generation = this.generation;
    try {
      const auth = await this.request({
        method: 'POST',
        path: '/auth/refresh',
        schema: authSessionSchema,
        auth: false,
      });
      if (generation !== this.generation) {
        throw new SessionExpiredError();
      }
      return this.setSession(auth, 'refresh');
    } catch (error: unknown) {
      if (
        error instanceof HttpError &&
        error.status === 401 &&
        generation === this.generation
      ) {
        this.expireSession();
      }
      throw error;
    }
  }

  /**
   * Makes sure a newer token exists after a `401`. If another request already
   * refreshed since `usedToken` was sent, that token is reused.
   */
  private async recoverFrom401(usedToken: string | undefined): Promise<void> {
    const current = this.session?.accessToken;
    if (current !== undefined && current !== usedToken) {
      return;
    }
    try {
      await this.refresh();
    } catch (error: unknown) {
      if (error instanceof HttpError && error.status === 401) {
        throw new SessionExpiredError();
      }
      throw error;
    }
  }

  /** Ends the session, once: concurrent failures notify listeners once. */
  private expireSession(): void {
    if (this.session !== undefined) {
      this.clearSession('expired');
    }
  }

  private async send<T>(
    options: RequestOptions<T>,
    token: string | undefined,
  ): Promise<RawResponse> {
    const method = options.method ?? 'GET';
    const endpoint = `${method} ${options.path}`;
    const headers = new Headers({Accept: 'application/json'});
    if (token !== undefined) {
      headers.set('Authorization', `Bearer ${token}`);
    }
    let body: URLSearchParams | undefined;
    if (options.form !== undefined) {
      body = new URLSearchParams(options.form);
    }
    const timeout = new AbortController();
    const timer = setTimeout(() => timeout.abort(), this.timeoutMs);
    const signal =
      options.signal === undefined
        ? timeout.signal
        : AbortSignal.any([options.signal, timeout.signal]);
    try {
      const response = await fetch(this.url(options), {
        method,
        headers,
        body,
        // Sends the httpOnly refresh cookie.
        credentials: 'include',
        signal,
      });
      return {status: response.status, body: readBody(await response.text())};
    } catch (error: unknown) {
      if (options.signal?.aborted === true) {
        // The caller cancelled: not an error to show (Query ignores it).
        throw error;
      }
      throw new NetworkError(
        endpoint,
        timeout.signal.aborted ? 'timeout' : 'offline',
      );
    } finally {
      clearTimeout(timer);
    }
  }

  private url<T>(options: RequestOptions<T>): string {
    const url = apiUrl(options.path, this.options.baseUrl);
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(options.query ?? {})) {
      if (value !== undefined) {
        query.set(key, value);
      }
    }
    const search = query.toString();
    return search === '' ? url : `${url}?${search}`;
  }

  private parse<T>(options: RequestOptions<T>, response: RawResponse): T {
    const endpoint = `${options.method ?? 'GET'} ${options.path}`;
    if (response.status < 200 || response.status >= 300) {
      const error = errorBodySchema.safeParse(response.body);
      throw new HttpError(
        endpoint,
        response.status,
        error.success ? error.data.detail : undefined,
      );
    }
    const result = options.schema.safeParse(response.body);
    if (result.success) {
      return result.data;
    }
    const issue = result.error.issues[0];
    const path = issue?.path.join('.') ?? '';
    const problem = issue?.message ?? 'invalid response';
    // Names the endpoint and the field, so drift is found on the first call.
    console.error(
      `Unexpected response from ${endpoint} at "${path}": ${problem}`,
      result.error.issues,
    );
    throw new ContractError(endpoint, path, problem);
  }

  private notify(change: SessionChange): void {
    for (const listener of this.listeners) {
      listener(this.session, change);
    }
  }
}

/** JSON when the body is JSON, the raw text otherwise, undefined if empty. */
function readBody(text: string): unknown {
  if (text === '') {
    return undefined;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

/** The client the app uses. Tests create their own. */
export const apiClient = new ApiClient({baseUrl: ENV.apiBaseUrl});
