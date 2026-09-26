import {Link} from 'react-router';

import type {AiRun, NewsList, RuleRun, VerifyRun} from '@/api/schemas/news';
import {Alert, AlertDescription, AlertTitle} from '@/components/ui/alert';
import {Skeleton} from '@/components/ui/skeleton';
import {formatLongDate, isWeekend} from '@/lib/time';

import {aiRunSummary} from '../ai';
import {feedFallbackDate, feedSearch, feedSummary} from '../feed';
import type {FeedFilters} from '../feed';
import {ruleRunSummary} from '../rules';
import {verifyRunSummary} from '../verdicts';

const SKELETON_ROWS = 6;

/** Loading: placeholders shaped like feed rows. */
export function FeedSkeleton() {
  return (
    <div aria-busy="true">
      <p role="status" className="sr-only">
        Loading the feed…
      </p>
      <ul className="flex flex-col gap-3">
        {Array.from({length: SKELETON_ROWS}, (_, index) => (
          <li key={index} className="flex flex-col gap-2 rounded-lg border p-3">
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-5 w-3/4" />
            <Skeleton className="h-4 w-full" />
          </li>
        ))}
      </ul>
    </div>
  );
}

interface NoFeedProps {
  date: string;
  today: string;
}

/** No ingest run for the date (a weekend, a future date, or none yet). */
export function NoFeed({date, today}: NoFeedProps) {
  const fallback = feedFallbackDate(date, today);
  let reason = 'No ingest run exists for this date yet.';
  if (isWeekend(date)) {
    reason = 'US markets are closed on weekends.';
  } else if (date > today) {
    reason = 'This date is in the future.';
  }
  return (
    <section className="flex flex-col gap-2 py-6">
      <h2 className="text-lg font-semibold">
        No feed for {formatLongDate(date)}
      </h2>
      <p className="text-muted-foreground">{reason}</p>
      <p>
        <Link
          to={{
            pathname: '/news',
            search: feedSearch({date: fallback, dups: false, flagged: false}),
          }}
          className="font-medium underline underline-offset-4"
        >
          Go to {formatLongDate(fallback)}
        </Link>
      </p>
    </section>
  );
}

interface RunStatusProps {
  list: NewsList;
  filters: FeedFilters;
  today: string;
}

/**
 * The ingest run's state: the summary line when `DONE`, a notice while
 * `RUNNING`, an error panel when `FAILED` (the items below still show).
 */
export function RunStatus({list, filters, today}: RunStatusProps) {
  // What the run received, not what the filters show.
  const received = list.run?.rowsReceived ?? 0;
  const receivedText = `${received} ${received === 1 ? 'item' : 'items'}`;
  if (list.run?.status === 'RUNNING') {
    const subject =
      list.date === today ? "Today's feed" : 'The feed for this date';
    return (
      <Alert role="status">
        <AlertTitle>{subject} is still arriving</AlertTitle>
        <AlertDescription>
          {receivedText} received so far; the list updates every 30 seconds.
        </AlertDescription>
      </Alert>
    );
  }
  if (list.run?.status === 'FAILED') {
    return (
      <Alert variant="destructive">
        <AlertTitle>The ingest run for this date failed</AlertTitle>
        <AlertDescription>
          The feed may be incomplete: {receivedText} arrived before the failure.
          They are listed below.
        </AlertDescription>
      </Alert>
    );
  }
  return (
    <p role="status" className="text-sm text-muted-foreground">
      {feedSummary(list, filters)}
    </p>
  );
}

interface AiRunStatusProps {
  aiRun: AiRun | null;
}

/**
 * The date's AI run: its counts when `DONE`, progress while `RUNNING`, a
 * notice when `FAILED` or when it hasn't run.
 */
export function AiRunStatus({aiRun}: AiRunStatusProps) {
  const text = aiRunSummary(aiRun);
  if (aiRun?.status === 'FAILED') {
    return (
      <Alert role="status">
        <AlertTitle>The AI run failed</AlertTitle>
        <AlertDescription>{text}</AlertDescription>
      </Alert>
    );
  }
  return <p className="text-sm text-muted-foreground">{text}</p>;
}

interface RuleRunStatusProps {
  ruleRun: RuleRun | null;
}

/**
 * The date's rule-check run: its counts when `DONE`, progress while
 * `RUNNING`, a notice when `FAILED` or when the rules haven't run.
 */
export function RuleRunStatus({ruleRun}: RuleRunStatusProps) {
  const text = ruleRunSummary(ruleRun);
  if (ruleRun?.status === 'FAILED') {
    return (
      <Alert role="status">
        <AlertTitle>Rule checks failed</AlertTitle>
        <AlertDescription>{text}</AlertDescription>
      </Alert>
    );
  }
  return <p className="text-sm text-muted-foreground">{text}</p>;
}

interface VerifyRunStatusProps {
  verifyRun: VerifyRun | null;
}

/**
 * The date's AI verification: its verdict counts when `DONE`, progress
 * while queued or running, a notice when it failed or hasn't run.
 */
export function VerifyRunStatus({verifyRun}: VerifyRunStatusProps) {
  const text = verifyRunSummary(verifyRun);
  if (verifyRun?.status === 'FAILED') {
    return (
      <Alert role="status">
        <AlertTitle>The AI verification failed</AlertTitle>
        <AlertDescription>{text}</AlertDescription>
      </Alert>
    );
  }
  return <p className="text-sm text-muted-foreground">{text}</p>;
}
