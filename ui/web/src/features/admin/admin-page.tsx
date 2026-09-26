import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {useState} from 'react';
import type {FormEvent} from 'react';

import {HttpError, errorMessage} from '@/api/errors';
import {
  createUser,
  getLlmSettings,
  getSources,
  getUsers,
  saveCloudSwitches,
  saveSource,
  updateUser,
} from '@/api/ops';
import type {Role} from '@/api/schemas/auth';
import {TIERS} from '@/api/schemas/ops';
import type {AdminUser, CloudSwitches, Tier} from '@/api/schemas/ops';
import {useDocumentTitle} from '@/components/layout/use-document-title';
import {LoadError} from '@/components/load-error';
import {Alert, AlertDescription, AlertTitle} from '@/components/ui/alert';
import {Button} from '@/components/ui/button';
import {Input} from '@/components/ui/input';
import {Label} from '@/components/ui/label';
import {Skeleton} from '@/components/ui/skeleton';
import {useSession} from '@/features/auth/session-context';
import {percent, usd} from '@/features/ops/ops';

import {passwordProblem, sourceProblem, usernameProblem} from './admin';

const ROLES: readonly Role[] = ['TRADER', 'ANALYST', 'ADMIN'];
const SELECT_CLASS =
  'h-8 rounded-lg border border-input bg-transparent px-2 text-sm';

const adminKeys = {
  users: ['admin', 'users'] as const,
  sources: (q: string) => ['admin', 'sources', q] as const,
  llm: ['admin', 'llm'] as const,
};

/**
 * `/admin` (ADMIN): users, the source reputation list and the LLM
 * settings. Every change is audited by the server.
 */
export function AdminPage() {
  useDocumentTitle('Administration');
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-8">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">Administration</h1>
        <p className="text-muted-foreground">
          Users, source reputation and the cloud model switches. Every change is
          written to the audit log.
        </p>
      </div>
      <UsersSection />
      <SourcesSection />
      <LlmSection />
    </div>
  );
}

function problemOf(error: unknown): string | undefined {
  if (error === null || error === undefined) {
    return undefined;
  }
  if (error instanceof HttpError && typeof error.detail === 'string') {
    return error.detail;
  }
  if (error instanceof HttpError && error.status === 422) {
    return 'The server refused these values.';
  }
  return errorMessage(error);
}

// --- users --------------------------------------------------------------------

function UsersSection() {
  const {client, status} = useSession();
  const me =
    status.kind === 'authenticated' ? status.session.user.username : '';
  const queryClient = useQueryClient();
  const users = useQuery({
    queryKey: adminKeys.users,
    queryFn: ({signal}) => getUsers({client, signal}),
  });
  const [done, setDone] = useState('');
  const change = useMutation({
    mutationFn: ({
      username,
      update,
    }: {
      username: string;
      update: {role?: Role; disabled?: boolean; password?: string};
    }) => updateUser(username, update, {client}),
    onSuccess: async (user, {update}) => {
      setDone(
        update.password !== undefined
          ? `Password reset for ${user.username}.`
          : `${user.username} is now ${user.disabled ? 'disabled' : user.role}.`,
      );
      await queryClient.invalidateQueries({queryKey: adminKeys.users});
    },
  });

  return (
    <section aria-labelledby="users-heading" className="flex flex-col gap-3">
      <h2 id="users-heading" className="text-lg font-semibold">
        Users
      </h2>
      {users.isError && (
        <LoadError
          title="Couldn't load the users"
          error={users.error}
          onRetry={() => void users.refetch()}
        />
      )}
      {users.isPending && <Skeleton className="h-24 w-full" />}
      {users.data !== undefined && (
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Users</caption>
          <thead>
            <tr className="border-b">
              <th scope="col" className="py-1 pr-3">
                User
              </th>
              <th scope="col" className="py-1 pr-3">
                Role
              </th>
              <th scope="col" className="py-1 pr-3">
                Status
              </th>
              <th scope="col" className="py-1">
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {users.data.map(user => (
              <UserRow
                key={user.username}
                user={user}
                self={user.username === me}
                busy={change.isPending}
                onChange={update =>
                  change.mutate({username: user.username, update})
                }
              />
            ))}
          </tbody>
        </table>
      )}
      {change.error !== null && (
        <Alert variant="destructive">
          <AlertTitle>Not changed</AlertTitle>
          <AlertDescription>{problemOf(change.error)}</AlertDescription>
        </Alert>
      )}
      <p aria-live="polite" className="text-sm">
        {done}
      </p>
      <NewUserForm />
    </section>
  );
}

interface UserRowProps {
  user: AdminUser;
  /** The signed-in admin: can't disable or demote themselves. */
  self: boolean;
  busy: boolean;
  onChange(update: {role?: Role; disabled?: boolean; password?: string}): void;
}

function UserRow({user, self, busy, onChange}: UserRowProps) {
  const [password, setPassword] = useState('');
  const [problem, setProblem] = useState<string | undefined>(undefined);
  const roleId = `role-${user.username}`;
  const passwordId = `password-${user.username}`;
  return (
    <tr className="border-b align-top">
      <th scope="row" className="py-2 pr-3 font-medium">
        {user.username}
        {self && <span className="text-muted-foreground"> (you)</span>}
      </th>
      <td className="py-2 pr-3">
        <label htmlFor={roleId} className="sr-only">
          Role of {user.username}
        </label>
        <select
          id={roleId}
          className={SELECT_CLASS}
          value={user.role}
          disabled={busy || self}
          onChange={event => onChange({role: event.target.value as Role})}
        >
          {ROLES.map(role => (
            <option key={role} value={role}>
              {role}
            </option>
          ))}
        </select>
      </td>
      <td className="py-2 pr-3">{user.disabled ? 'Disabled' : 'Active'}</td>
      <td className="flex flex-wrap items-start gap-2 py-2">
        <Button
          variant="outline"
          size="sm"
          disabled={busy || self}
          onClick={() => onChange({disabled: !user.disabled})}
        >
          {user.disabled
            ? `Enable ${user.username}`
            : `Disable ${user.username}`}
        </Button>
        <form
          className="flex items-start gap-2"
          noValidate
          onSubmit={event => {
            event.preventDefault();
            const found = passwordProblem(password);
            setProblem(found);
            if (found === undefined) {
              onChange({password});
              setPassword('');
            }
          }}
        >
          <div className="flex flex-col gap-1">
            <label htmlFor={passwordId} className="sr-only">
              New password for {user.username}
            </label>
            <Input
              id={passwordId}
              type="password"
              autoComplete="new-password"
              placeholder="New password"
              value={password}
              onChange={event => setPassword(event.target.value)}
              className="h-8 w-40"
            />
            {problem !== undefined && (
              <p className="text-xs text-destructive">{problem}</p>
            )}
          </div>
          <Button type="submit" variant="outline" size="sm" disabled={busy}>
            Reset password
          </Button>
        </form>
      </td>
    </tr>
  );
}

function NewUserForm() {
  const {client} = useSession();
  const queryClient = useQueryClient();
  const [username, setUsername] = useState('');
  const [role, setRole] = useState<Role>('TRADER');
  const [password, setPassword] = useState('');
  const [problem, setProblem] = useState<string | undefined>(undefined);
  const [done, setDone] = useState('');
  const create = useMutation({
    mutationFn: () => createUser({username, role, password}, {client}),
    onSuccess: async user => {
      setDone(`Created ${user.username} (${user.role}).`);
      setUsername('');
      setPassword('');
      await queryClient.invalidateQueries({queryKey: adminKeys.users});
    },
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setDone('');
    const found = usernameProblem(username) ?? passwordProblem(password);
    setProblem(found);
    if (found === undefined) {
      create.mutate();
    }
  }

  const shown = problem ?? problemOf(create.error);
  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      aria-labelledby="new-user-heading"
      className="flex flex-col gap-3 rounded-lg border p-3"
    >
      <h3 id="new-user-heading" className="font-medium">
        New user
      </h3>
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="new-username">Username</Label>
          <Input
            id="new-username"
            value={username}
            onChange={event => setUsername(event.target.value)}
            autoComplete="off"
            className="w-40"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="new-role">Role</Label>
          <select
            id="new-role"
            className={SELECT_CLASS}
            value={role}
            onChange={event => setRole(event.target.value as Role)}
          >
            {ROLES.map(name => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="new-password">Password</Label>
          <Input
            id="new-password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={event => setPassword(event.target.value)}
            className="w-48"
          />
        </div>
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? 'Creating…' : 'Create user'}
        </Button>
      </div>
      {shown !== undefined && (
        <Alert variant="destructive">
          <AlertTitle>Not created</AlertTitle>
          <AlertDescription>{shown}</AlertDescription>
        </Alert>
      )}
      <p aria-live="polite" className="text-sm">
        {done}
      </p>
    </form>
  );
}

// --- sources ------------------------------------------------------------------

function SourcesSection() {
  const {client} = useSession();
  const [query, setQuery] = useState('');
  const sources = useQuery({
    queryKey: adminKeys.sources(query),
    queryFn: ({signal}) => getSources(query, {client, signal}),
  });
  return (
    <section aria-labelledby="sources-heading" className="flex flex-col gap-3">
      <h2 id="sources-heading" className="text-lg font-semibold">
        Source reputation
      </h2>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="source-search">Find a domain</Label>
        <Input
          id="source-search"
          type="search"
          value={query}
          onChange={event => setQuery(event.target.value.trim().toLowerCase())}
          className="w-64"
        />
      </div>
      {sources.isError && (
        <LoadError
          title="Couldn't load the sources"
          error={sources.error}
          onRetry={() => void sources.refetch()}
        />
      )}
      {sources.isPending && <Skeleton className="h-24 w-full" />}
      {sources.data !== undefined && (
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Source reputation</caption>
          <thead>
            <tr className="border-b">
              <th scope="col" className="py-1 pr-3">
                Domain
              </th>
              <th scope="col" className="py-1 pr-3">
                Tier
              </th>
              <th scope="col" className="py-1 pr-3">
                Score
              </th>
              <th scope="col" className="py-1">
                Note
              </th>
            </tr>
          </thead>
          <tbody>
            {sources.data.map(source => (
              <tr key={source.domain} className="border-b">
                <th scope="row" className="py-1 pr-3 font-normal">
                  {source.domain}
                </th>
                <td className="py-1 pr-3">{source.tier}</td>
                <td className="py-1 pr-3">{source.reputation.toFixed(2)}</td>
                <td className="py-1">{source.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <SourceForm />
    </section>
  );
}

function SourceForm() {
  const {client} = useSession();
  const queryClient = useQueryClient();
  const [domain, setDomain] = useState('');
  const [tier, setTier] = useState<Tier>('neutral');
  const [reputation, setReputation] = useState('0.5');
  const [note, setNote] = useState('');
  const [problem, setProblem] = useState<string | undefined>(undefined);
  const [done, setDone] = useState('');
  const save = useMutation({
    mutationFn: () =>
      saveSource(
        {domain, tier, reputation: Number(reputation), note: note.trim()},
        {client},
      ),
    onSuccess: async source => {
      setDone(`Saved ${source.domain}: ${source.tier}, ${source.reputation}.`);
      await queryClient.invalidateQueries({queryKey: ['admin', 'sources']});
    },
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setDone('');
    const found = sourceProblem(domain, reputation);
    setProblem(found);
    if (found === undefined) {
      save.mutate();
    }
  }

  const shown = problem ?? problemOf(save.error);
  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      aria-labelledby="source-form-heading"
      className="flex flex-col gap-3 rounded-lg border p-3"
    >
      <h3 id="source-form-heading" className="font-medium">
        Add or change a domain
      </h3>
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="source-domain">Domain</Label>
          <Input
            id="source-domain"
            value={domain}
            onChange={event =>
              setDomain(event.target.value.trim().toLowerCase())
            }
            placeholder="example.com"
            autoComplete="off"
            className="w-56"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="source-tier">Tier</Label>
          <select
            id="source-tier"
            className={SELECT_CLASS}
            value={tier}
            onChange={event => setTier(event.target.value as Tier)}
          >
            {TIERS.map(name => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="source-score">Score (0 to 1)</Label>
          <Input
            id="source-score"
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={reputation}
            onChange={event => setReputation(event.target.value)}
            className="w-24"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="source-note">Note</Label>
          <Input
            id="source-note"
            value={note}
            maxLength={300}
            onChange={event => setNote(event.target.value)}
            className="w-64"
          />
        </div>
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? 'Saving…' : 'Save domain'}
        </Button>
      </div>
      {shown !== undefined && (
        <Alert variant="destructive">
          <AlertTitle>Not saved</AlertTitle>
          <AlertDescription>{shown}</AlertDescription>
        </Alert>
      )}
      <p aria-live="polite" className="text-sm">
        {done}
      </p>
    </form>
  );
}

// --- LLM settings -------------------------------------------------------------

const SWITCHES: {name: keyof CloudSwitches; label: string; hint: string}[] = [
  {
    name: 'enabled',
    label: 'Cloud models allowed',
    hint: 'Off keeps every task on the local models.',
  },
  {
    name: 'judge',
    label: 'Judge escalation',
    hint: 'Uncertain verdicts (confidence 0.50 to 0.70) ask the cloud model.',
  },
  {
    name: 'brief',
    label: "Brief's overview",
    hint: 'The pre-market brief is written by the cloud model.',
  },
];

function LlmSection() {
  const {client} = useSession();
  const queryClient = useQueryClient();
  const llm = useQuery({
    queryKey: adminKeys.llm,
    queryFn: ({signal}) => getLlmSettings({client, signal}),
  });
  const save = useMutation({
    mutationFn: (change: Partial<CloudSwitches>) =>
      saveCloudSwitches(change, {client}),
    onSuccess: result => {
      queryClient.setQueryData(adminKeys.llm, result);
    },
  });
  const data = llm.data;
  return (
    <section aria-labelledby="llm-heading" className="flex flex-col gap-3">
      <h2 id="llm-heading" className="text-lg font-semibold">
        LLM settings
      </h2>
      {llm.isError && (
        <LoadError
          title="Couldn't load the LLM settings"
          error={llm.error}
          onRetry={() => void llm.refetch()}
        />
      )}
      {llm.isPending && <Skeleton className="h-24 w-full" />}
      {data !== undefined && (
        <>
          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="font-medium">Hardware profile</dt>
            <dd>{data.hwProfile || 'not set'}</dd>
            <dt className="font-medium">Local models</dt>
            <dd>
              {data.mainModel}, {data.embedModel}, {data.guardModel}
            </dd>
            <dt className="font-medium">Vector store</dt>
            <dd>{data.vectorStore}</dd>
            <dt className="font-medium">Judge cloud model</dt>
            <dd>{data.judgeCloudModel || 'none (local only)'}</dd>
            <dt className="font-medium">Brief model</dt>
            <dd>{data.briefModel || 'none (local only)'}</dd>
            <dt className="font-medium">Cloud budget</dt>
            <dd>
              {usd(data.budget.spentUsd)} of {usd(data.budget.capUsd)} this
              month ({percent(data.budget.share)})
              {data.budget.reached && ': reached, running local'}
            </dd>
          </dl>
          <p className="text-xs text-muted-foreground">
            The models are pinned in the LLM gateway's configuration. Ask the
            News always stays local: its answers are streamed, and a streamed
            answer doesn't report its cost.
          </p>
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-sm font-medium">Cloud switches</legend>
            {SWITCHES.map(({name, label, hint}) => (
              <div key={name} className="flex items-start gap-2">
                <input
                  id={`switch-${name}`}
                  type="checkbox"
                  className="mt-0.5 size-4"
                  checked={data.cloud[name]}
                  disabled={save.isPending}
                  aria-describedby={`switch-${name}-hint`}
                  onChange={event =>
                    save.mutate({[name]: event.target.checked})
                  }
                />
                <div className="flex flex-col">
                  <Label htmlFor={`switch-${name}`}>{label}</Label>
                  <p
                    id={`switch-${name}-hint`}
                    className="text-xs text-muted-foreground"
                  >
                    {hint}
                  </p>
                </div>
              </div>
            ))}
          </fieldset>
          {save.error !== null && (
            <Alert variant="destructive">
              <AlertTitle>Not saved</AlertTitle>
              <AlertDescription>{problemOf(save.error)}</AlertDescription>
            </Alert>
          )}
        </>
      )}
    </section>
  );
}
