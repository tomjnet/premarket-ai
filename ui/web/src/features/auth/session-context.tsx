import {useQueryClient} from '@tanstack/react-query';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import type {ReactNode} from 'react';

import * as authApi from '@/api/auth';
import type {ApiClient, Session} from '@/api/client';

import {
  forgetHadSession,
  hadSession,
  proactiveRefreshDelayMs,
  rememberHadSession,
} from './session';

/** Where the session is: being restored on start, absent, or present. */
export type SessionStatus =
  | {kind: 'restoring'}
  | {
      kind: 'anonymous';
      /** The session ended (or this tab's session couldn't be restored). */
      expired: boolean;
      /** The backend couldn't be reached to restore the session. */
      restoreFailed: boolean;
    }
  | {kind: 'authenticated'; session: Session};

interface SessionContextValue {
  status: SessionStatus;
  /** The API client every data hook uses. */
  client: ApiClient;
  login(username: string, password: string): Promise<Session>;
  logout(): Promise<void>;
  /** Tries the start-up session restore again (after `restoreFailed`). */
  retryRestore(): void;
}

const SessionContext = createContext<SessionContextValue | undefined>(
  undefined,
);

interface SessionProviderProps {
  client: ApiClient;
  children: ReactNode;
}

/**
 * Owns the login state: restores the session from the refresh cookie on
 * start, refreshes the token before it expires, and follows every session
 * change the API client reports (login, refresh, logout, expiry).
 */
export function SessionProvider({client, children}: SessionProviderProps) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<SessionStatus>({kind: 'restoring'});
  // Read once per page load: StrictMode runs the restore effect twice, and
  // the first run clears the flag.
  const [hadSessionAtStart] = useState(hadSession);

  useEffect(
    () =>
      client.subscribe((session, change) => {
        if (session !== undefined) {
          rememberHadSession();
          setStatus({kind: 'authenticated', session});
          return;
        }
        // Another user's data must not survive a logout or an expiry.
        queryClient.clear();
        if (change === 'logout') {
          forgetHadSession();
        }
        setStatus({
          kind: 'anonymous',
          expired: change === 'expired',
          restoreFailed: false,
        });
      }),
    [client, queryClient],
  );

  const restore = useCallback(() => {
    void restoredStatus(client, hadSessionAtStart).then(next => {
      if (next !== undefined) {
        setStatus(next);
      }
    });
  }, [client, hadSessionAtStart]);

  useEffect(restore, [restore]);

  const retryRestore = useCallback(() => {
    setStatus({kind: 'restoring'});
    restore();
  }, [restore]);

  const expiresAt =
    status.kind === 'authenticated' ? status.session.expiresAt : undefined;
  useEffect(() => {
    if (expiresAt === undefined) {
      return undefined;
    }
    const timer = setTimeout(
      () => {
        // A 401 ends the session inside the client (listeners hear it); other
        // failures are left to the next call's own refresh-on-401.
        client.refresh().catch(() => undefined);
      },
      proactiveRefreshDelayMs(expiresAt - Date.now()),
    );
    return () => clearTimeout(timer);
  }, [client, expiresAt]);

  const login = useCallback(
    (username: string, password: string) =>
      authApi.login(username, password, {client}),
    [client],
  );
  const logout = useCallback(() => authApi.logout({client}), [client]);

  const value = useMemo(
    () => ({status, client, login, logout, retryRestore}),
    [status, client, login, logout, retryRestore],
  );
  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

/**
 * Restores the session on start and says what the status becomes, or
 * undefined when nothing changes. A successful restore reaches the state
 * through the client subscription; a login that finished meanwhile wins
 * (the client then has a session).
 */
async function restoredStatus(
  client: ApiClient,
  hadSessionBefore: boolean,
): Promise<SessionStatus | undefined> {
  try {
    const session = await authApi.restoreSession({client});
    if (session !== undefined || client.getSession() !== undefined) {
      return undefined;
    }
    // A tab that had a session and can't restore it: it expired.
    forgetHadSession();
    return {kind: 'anonymous', expired: hadSessionBefore, restoreFailed: false};
  } catch {
    if (client.getSession() !== undefined) {
      return undefined;
    }
    return {kind: 'anonymous', expired: false, restoreFailed: true};
  }
}

/** The session and the API client. Use inside `SessionProvider`. */
export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (value === undefined) {
    throw new Error('useSession() needs a SessionProvider above it');
  }
  return value;
}
