import {Link, useNavigate, useSearchParams} from 'react-router';

import type {Brief, BriefItem} from '@/api/schemas/brief';
import {useDocumentTitle} from '@/components/layout/use-document-title';
import {Alert, AlertDescription, AlertTitle} from '@/components/ui/alert';
import {Button} from '@/components/ui/button';
import {Input} from '@/components/ui/input';
import {Label} from '@/components/ui/label';
import {Skeleton} from '@/components/ui/skeleton';
import {useSession} from '@/features/auth/session-context';
import {AnswerText} from '@/features/chat/components/answer-text';
import {canReview} from '@/features/review/review';
import {
  formatEtTime,
  formatLongDate,
  isIsoDate,
  todayInNewYork,
} from '@/lib/time';

import {
  briefDate,
  editionText,
  leftOutText,
  orderedSectors,
  pick,
} from './brief';
import {BriefItemView} from './components/brief-item';
import {useTodayBrief} from './hooks/use-today-brief';

const anchor = (n: number) => `brief-item-${n}`;

/**
 * `/brief`: Today's Brief, the web page that replaces the legacy PDF. Only
 * VERIFIED stories, plus high-impact UNVERIFIED ones under "Unconfirmed –
 * watch"; MISLEADING, FAKE and pending items are only counted. The date is
 * in the URL (`?date=`). Analysts and admins can write it again.
 */
export function BriefPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const {status} = useSession();
  const today = todayInNewYork();
  const date = briefDate(searchParams, today);
  useDocumentTitle(`Today's brief, ${formatLongDate(date)}`);
  const {view, write, writeError} = useTodayBrief(date);
  const role = status.kind === 'authenticated' ? status.session.user.role : '';
  const writer = role !== '' && canReview(role);

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">Today's brief</h1>
        <p className="text-muted-foreground">
          The pre-market brief: verified stories first, then what is worth
          watching. It replaces the daily PDF.
        </p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="brief-date">Date</Label>
          <Input
            id="brief-date"
            type="date"
            min="2020-01-01"
            max={today}
            value={date}
            onChange={event => {
              const next = event.target.value;
              if (isIsoDate(next) && next <= today) {
                void navigate({pathname: '/brief', search: `?date=${next}`});
              }
            }}
            className="w-40"
          />
        </div>
        {writer && (
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              disabled={view.phase === 'writing' || view.phase === 'loading'}
              onClick={() => void write('morning')}
            >
              Write the brief now
            </Button>
            <Button
              variant="outline"
              disabled={view.phase !== 'done'}
              onClick={() => void write('refresh')}
            >
              Refresh with reviewed items
            </Button>
          </div>
        )}
      </div>
      {writeError !== undefined && (
        <Alert variant="destructive">
          <AlertTitle>The brief wasn't started</AlertTitle>
          <AlertDescription>{writeError}</AlertDescription>
        </Alert>
      )}
      <div aria-live="polite" aria-busy={view.phase === 'writing'}>
        {view.phase === 'writing' && (
          <p role="status" className="rounded-md border p-3">
            The brief of {formatLongDate(date)} is being written:{' '}
            {view.progress ?? 'waiting to start'}…
          </p>
        )}
        {view.phase === 'done' && view.brief !== undefined && (
          <p className="sr-only">
            The brief of {formatLongDate(date)} is ready.
          </p>
        )}
      </div>
      {view.phase === 'loading' && (
        <div aria-busy="true" className="flex flex-col gap-3">
          <p role="status" className="sr-only">
            Loading the brief…
          </p>
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      )}
      {view.phase === 'missing' && <p className="py-4">{view.error}</p>}
      {view.phase === 'failed' && (
        <Alert variant="destructive">
          <AlertTitle>No brief</AlertTitle>
          <AlertDescription>{view.error}</AlertDescription>
        </Alert>
      )}
      {view.phase === 'done' && view.brief !== undefined && (
        <BriefContent brief={view.brief} />
      )}
    </div>
  );
}

interface BriefContentProps {
  brief: Brief;
}

function BriefContent({brief}: BriefContentProps) {
  const verifiedNumbers = new Set(
    brief.items.filter(item => item.section !== 'watch').map(item => item.n),
  );
  const focusItem = (n: number) => {
    document.getElementById(anchor(n))?.focus();
  };
  const mine = pick(brief, brief.watchlist.items);
  const top = pick(brief, brief.top);
  const watch = pick(brief, brief.watch);
  const hasWatchlist =
    brief.watchlist.tickers.length > 0 || brief.watchlist.sectors.length > 0;
  return (
    <article aria-labelledby="brief-heading" className="flex flex-col gap-5">
      <header className="flex flex-col gap-1">
        <h2 id="brief-heading" className="text-lg font-semibold">
          {formatLongDate(brief.feedDate)} · {editionText(brief.edition)}
        </h2>
        <p className="text-xs text-muted-foreground">
          {brief.finishedAt !== null &&
            `Published ${formatEtTime(brief.finishedAt)} ET · `}
          {brief.counts.verified} verified · {brief.counts.unconfirmed} to watch
          {brief.counts.new > 0 && ` · ${brief.counts.new} added after review`}
        </p>
      </header>
      <section
        aria-labelledby="overview-heading"
        className="flex flex-col gap-2"
      >
        <h3 id="overview-heading" className="font-semibold">
          Overview
        </h3>
        <AnswerText
          text={brief.overview}
          sourceNumbers={verifiedNumbers}
          onCite={focusItem}
          citeLabel="Item"
        />
        <p className="text-xs text-muted-foreground">
          {brief.overviewSource === 'fallback'
            ? 'Written from the top items by code: the model’s overview didn’t pass the checks.'
            : `Written by a language model (${brief.model ?? 'unknown'}${
                brief.cloud ? ', cloud' : ''
              }) from the verified items; it can be wrong.`}
        </p>
      </section>
      <section aria-labelledby="mine-heading" className="flex flex-col gap-2">
        <h3 id="mine-heading" className="font-semibold">
          Your watchlist
        </h3>
        {!hasWatchlist && (
          <p className="text-sm">
            You follow no ticker or sector yet.{' '}
            <Link to="/watchlist" className="underline underline-offset-2">
              Set up your watchlist
            </Link>{' '}
            to see its stories here first.
          </p>
        )}
        {hasWatchlist && mine.length === 0 && (
          <p className="text-sm">
            No story in this brief is on your watchlist.
          </p>
        )}
        {mine.length > 0 && <ItemList label="Your watchlist" items={mine} />}
      </section>
      <section aria-labelledby="top-heading" className="flex flex-col gap-2">
        <h3 id="top-heading" className="font-semibold">
          Top stories
        </h3>
        {top.length === 0 ? (
          <p className="text-sm">No story is verified yet.</p>
        ) : (
          <ItemList label="Top stories" items={top} anchored />
        )}
      </section>
      {brief.sectors.some(sector =>
        pick(brief, sector.items).some(item => item.section === 'sector'),
      ) && (
        <section
          aria-labelledby="sectors-heading"
          className="flex flex-col gap-3"
        >
          <h3 id="sectors-heading" className="font-semibold">
            More verified stories by sector
          </h3>
          {orderedSectors(brief, brief.watchlist.sectors).map(sector => {
            const rest = pick(brief, sector.items).filter(
              item => item.section === 'sector',
            );
            if (rest.length === 0) {
              return null;
            }
            return (
              <div key={sector.name} className="flex flex-col gap-2">
                <h4 className="text-sm font-semibold">{sector.name}</h4>
                <ItemList label={sector.name} items={rest} anchored />
              </div>
            );
          })}
        </section>
      )}
      <section aria-labelledby="watch-heading" className="flex flex-col gap-2">
        <h3 id="watch-heading" className="font-semibold">
          Unconfirmed – watch
        </h3>
        <p className="text-sm text-muted-foreground">
          High-impact stories nobody has confirmed yet. They may be real
          breaking news; don't treat them as fact.
        </p>
        {watch.length === 0 ? (
          <p className="text-sm">Nothing to watch.</p>
        ) : (
          <ItemList label="Unconfirmed – watch" items={watch} anchored />
        )}
      </section>
      <section aria-labelledby="out-heading" className="flex flex-col gap-1">
        <h3 id="out-heading" className="font-semibold">
          Not in the brief
        </h3>
        <p className="text-sm">
          {leftOutText(brief.counts)}. Misleading and fake stories never go in;
          stories waiting for an analyst join the 09:00 refresh once approved.
        </p>
      </section>
      <p className="border-t pt-3 text-sm font-medium">
        Decision support only, not investment advice.
      </p>
    </article>
  );
}

interface ItemListProps {
  label: string;
  items: BriefItem[];
  /** Citations focus these items (not the watchlist's copies). */
  anchored?: boolean;
}

function ItemList({label, items, anchored = false}: ItemListProps) {
  return (
    <ol aria-label={label} className="flex flex-col gap-2">
      {items.map(item => (
        <BriefItemView
          key={item.n}
          item={item}
          anchorId={anchored ? anchor(item.n) : undefined}
        />
      ))}
    </ol>
  );
}
