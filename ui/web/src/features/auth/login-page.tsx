import {useMutation} from '@tanstack/react-query';
import {useId, useRef, useState} from 'react';
import type {FormEvent} from 'react';
import {Navigate, useSearchParams} from 'react-router';

import {HttpError, errorMessage} from '@/api/errors';
import {PageMain} from '@/components/layout/page-main';
import {useDocumentTitle} from '@/components/layout/use-document-title';
import {Alert, AlertDescription} from '@/components/ui/alert';
import {Button} from '@/components/ui/button';
import {Card, CardContent, CardHeader} from '@/components/ui/card';
import {Input} from '@/components/ui/input';
import {Label} from '@/components/ui/label';
import {ENV} from '@/lib/env';

import {safeNextPath} from './session';
import {useSession} from './session-context';

// The seeded mock users (src/mocks/data/users.ts). Listed here because app
// code must not import mock code; shown in mock mode only.
const MOCK_USERS_HINT =
  'Mock mode: log in as trader1, analyst1 or admin1, password demo.';

interface Credentials {
  username: string;
  password: string;
}

function isWrongCredentials(error: unknown): boolean {
  return error instanceof HttpError && error.status === 401;
}

/** `/login`: username and password; afterwards, back to `?next=`. */
export function LoginPage() {
  const {status, login, retryRestore} = useSession();
  useDocumentTitle('Log in');
  const [searchParams] = useSearchParams();
  const next = safeNextPath(searchParams.get('next'));
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [missing, setMissing] = useState({username: false, password: false});
  const passwordRef = useRef<HTMLInputElement>(null);
  const errorId = useId();
  const mutation = useMutation({
    mutationFn: (credentials: Credentials) =>
      login(credentials.username, credentials.password),
    onError: error => {
      // Only a wrong password is worth retyping; a network blip isn't.
      if (isWrongCredentials(error)) {
        setPassword('');
        passwordRef.current?.focus();
      }
    },
  });

  if (status.kind === 'authenticated') {
    return <Navigate to={next} replace />;
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutation.isPending) {
      return;
    }
    const credentials = {username: username.trim(), password};
    const nowMissing = {
      username: credentials.username === '',
      password: password === '',
    };
    setMissing(nowMissing);
    if (!nowMissing.username && !nowMissing.password) {
      mutation.mutate(credentials);
    }
  }

  const anyMissing = missing.username || missing.password;
  const wrongCredentials =
    mutation.isError && isWrongCredentials(mutation.error);
  let error: string | undefined;
  if (anyMissing) {
    error = 'Enter your username and password.';
  } else if (wrongCredentials) {
    error = 'Wrong username or password.';
  } else if (mutation.isError) {
    error = errorMessage(mutation.error);
  }
  const describedBy = error === undefined ? undefined : errorId;
  const expired = status.kind === 'anonymous' && status.expired;
  const restoreFailed = status.kind === 'anonymous' && status.restoreFailed;

  return (
    <PageMain className="flex items-start justify-center px-4 py-12">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <h1 className="text-xl font-semibold">Log in to premarket-ai</h1>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {expired && (
            <Alert role="status">
              <AlertDescription>
                Your session expired. Please log in again.
              </AlertDescription>
            </Alert>
          )}
          {restoreFailed && (
            <Alert role="status">
              <AlertDescription className="flex flex-col items-start gap-2">
                Can't reach the server to restore your session.
                <Button variant="outline" size="sm" onClick={retryRestore}>
                  Try again
                </Button>
              </AlertDescription>
            </Alert>
          )}
          <form
            onSubmit={handleSubmit}
            noValidate
            className="flex flex-col gap-4"
          >
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                name="username"
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                value={username}
                onChange={event => setUsername(event.target.value)}
                aria-invalid={missing.username || wrongCredentials}
                aria-describedby={describedBy}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                ref={passwordRef}
                value={password}
                onChange={event => setPassword(event.target.value)}
                aria-invalid={missing.password || wrongCredentials}
                aria-describedby={describedBy}
              />
            </div>
            {error !== undefined && (
              <Alert variant="destructive" id={errorId}>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? 'Logging in…' : 'Log in'}
            </Button>
          </form>
          {ENV.apiMode === 'mock' && (
            <p className="text-sm text-muted-foreground">{MOCK_USERS_HINT}</p>
          )}
        </CardContent>
      </Card>
    </PageMain>
  );
}
