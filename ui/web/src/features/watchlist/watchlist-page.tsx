import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {useState} from 'react';
import type {FormEvent} from 'react';

import {getWatchlist, saveWatchlist} from '@/api/brief';
import {HttpError, errorMessage} from '@/api/errors';
import {WATCHLIST_MAX_TICKERS} from '@/api/schemas/brief';
import type {Watchlist} from '@/api/schemas/brief';
import {useDocumentTitle} from '@/components/layout/use-document-title';
import {LoadError} from '@/components/load-error';
import {Alert, AlertDescription, AlertTitle} from '@/components/ui/alert';
import {Button} from '@/components/ui/button';
import {Input} from '@/components/ui/input';
import {Label} from '@/components/ui/label';
import {Skeleton} from '@/components/ui/skeleton';
import {useSession} from '@/features/auth/session-context';

import {parseTickers} from './watchlist';

const WATCHLIST_KEY = ['watchlist'] as const;

/**
 * `/watchlist`: the tickers and sectors the user follows (long-term memory
 * on the server). Their stories come first in Today's brief, the chat's
 * agents know them ("my watchlist"), and a FAKE or MISLEADING verdict for a
 * watched ticker goes to an analyst.
 */
export function WatchlistPage() {
  useDocumentTitle('My watchlist');
  const {client} = useSession();
  const saved = useQuery({
    queryKey: WATCHLIST_KEY,
    queryFn: ({signal}) => getWatchlist({client, signal}),
  });
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">My watchlist</h1>
        <p className="text-muted-foreground">
          The tickers and sectors you follow. Their stories come first in
          Today's brief, and "my watchlist" in Ask the News means them.
        </p>
      </div>
      {saved.isError && (
        <LoadError
          title="Couldn't load your watchlist"
          error={saved.error}
          onRetry={() => void saved.refetch()}
        />
      )}
      {saved.isPending && (
        <div aria-busy="true">
          <p role="status" className="sr-only">
            Loading your watchlist…
          </p>
          <Skeleton className="h-40 w-full" />
        </div>
      )}
      {saved.data !== undefined && <WatchlistForm saved={saved.data} />}
    </div>
  );
}

interface WatchlistFormProps {
  /** The watchlist when the page opened (the form's starting values). */
  saved: Watchlist;
}

function WatchlistForm({saved}: WatchlistFormProps) {
  const {client} = useSession();
  const queryClient = useQueryClient();
  const [tickers, setTickers] = useState(saved.tickers.join(', '));
  const [sectors, setSectors] = useState<string[]>(saved.sectors);
  const [problem, setProblem] = useState<string | undefined>(undefined);
  const [done, setDone] = useState('');
  const save = useMutation({
    mutationFn: (next: {tickers: string[]; sectors: string[]}) =>
      saveWatchlist(next, {client}),
    onSuccess: result => {
      queryClient.setQueryData(WATCHLIST_KEY, result);
      // What the server saved (upper case, no repeats).
      setTickers(result.tickers.join(', '));
      setDone(
        `Watchlist saved: ${result.tickers.length} tickers, ${result.sectors.length} sectors.`,
      );
    },
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setDone('');
    const parsed = parseTickers(tickers);
    if ('problem' in parsed) {
      setProblem(parsed.problem);
      return;
    }
    setProblem(undefined);
    save.mutate({tickers: parsed.tickers, sectors});
  }

  const serverProblem =
    save.error instanceof HttpError &&
    save.error.status === 422 &&
    typeof save.error.detail === 'string'
      ? save.error.detail
      : save.error === null
        ? undefined
        : errorMessage(save.error);
  const shownProblem = problem ?? serverProblem;

  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      className="flex flex-col gap-4"
      aria-describedby={
        shownProblem === undefined ? undefined : 'watchlist-problem'
      }
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="watchlist-tickers">Tickers</Label>
        <Input
          id="watchlist-tickers"
          value={tickers}
          onChange={event => setTickers(event.target.value)}
          placeholder="AAPL, MSFT, BRK.B"
          aria-describedby="watchlist-tickers-hint"
          autoComplete="off"
        />
        <p
          id="watchlist-tickers-hint"
          className="text-xs text-muted-foreground"
        >
          Up to {WATCHLIST_MAX_TICKERS} US tickers, separated by commas or
          spaces.
        </p>
      </div>
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-medium">Sectors</legend>
        {saved.availableSectors.map(sector => {
          const id = `sector-${sector.replace(/\W+/g, '-').toLowerCase()}`;
          return (
            <div key={sector} className="flex items-center gap-2">
              <input
                id={id}
                type="checkbox"
                checked={sectors.includes(sector)}
                onChange={event =>
                  setSectors(current =>
                    event.target.checked
                      ? [...current, sector]
                      : current.filter(name => name !== sector),
                  )
                }
                className="size-4"
              />
              <Label htmlFor={id} className="font-normal">
                {sector}
              </Label>
            </div>
          );
        })}
      </fieldset>
      {shownProblem !== undefined && (
        <Alert variant="destructive" id="watchlist-problem">
          <AlertTitle>Not saved</AlertTitle>
          <AlertDescription>{shownProblem}</AlertDescription>
        </Alert>
      )}
      <p aria-live="polite" className="text-sm">
        {done}
      </p>
      <div>
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? 'Saving…' : 'Save watchlist'}
        </Button>
      </div>
    </form>
  );
}
