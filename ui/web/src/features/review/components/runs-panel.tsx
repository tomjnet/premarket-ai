import type {VerifyRun} from '@/api/schemas/news';
import {LoadError} from '@/components/load-error';
import {Alert, AlertDescription, AlertTitle} from '@/components/ui/alert';
import {Button} from '@/components/ui/button';
import {verifyRunSummary} from '@/features/news/verdicts';
import {formatEtTime, formatLongDate, newYorkDateOf} from '@/lib/time';

import type {useVerifyRun} from '../hooks/use-verify-run';

interface RunsPanelProps {
  date: string;
  verify: ReturnType<typeof useVerifyRun>;
}

/**
 * The AI verification of the date: its latest run, and "Verify this date"
 * with the live progress of the run it starts (from the run's server-sent
 * events).
 */
export function RunsPanel({date, verify}: RunsPanelProps) {
  const latest: VerifyRun | undefined = verify.runs.data?.[0];
  const live = verify.live;
  const busy =
    verify.following ||
    latest?.status === 'QUEUED' ||
    latest?.status === 'RUNNING';
  return (
    <section
      aria-labelledby="runs-heading"
      className="flex flex-col gap-3 rounded-lg border p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="runs-heading" className="text-lg font-semibold">
          AI verification of {formatLongDate(date)}
        </h2>
        <Button onClick={() => void verify.start()} disabled={busy}>
          {busy ? 'Verification running…' : 'Verify this date'}
        </Button>
      </div>
      {verify.error !== undefined && (
        <Alert variant="destructive">
          <AlertTitle>Couldn't start the verification</AlertTitle>
          <AlertDescription>{verify.error}</AlertDescription>
        </Alert>
      )}
      {live !== undefined && <LiveProgress live={live} />}
      {verify.runs.isError ? (
        <LoadError
          title="Couldn't load the verify runs"
          error={verify.runs.error}
          onRetry={() => void verify.runs.refetch()}
        />
      ) : (
        <LatestRun run={latest} loading={verify.runs.isPending} />
      )}
    </section>
  );
}

function LiveProgress({
  live,
}: {
  live: NonNullable<RunsPanelProps['verify']['live']>;
}) {
  const percent =
    live.total === 0 ? 0 : Math.round((live.done / live.total) * 100);
  let text = `Verifying: ${live.done} of ${live.total} items, ${live.toReview} sent to review.`;
  if (live.status === 'starting') {
    text = 'Verification queued. Waiting for a worker…';
  } else if (live.status === 'done') {
    text = `Verification finished: ${live.done} items, ${live.toReview} sent to review.`;
  } else if (live.status === 'failed') {
    text = live.error ?? 'The verification failed.';
  }
  return (
    <div className="flex flex-col gap-1.5">
      {/* A native progress bar: no inline style (the site's CSP). */}
      <progress
        aria-label="Verification progress"
        value={live.done}
        max={Math.max(live.total, 1)}
        className="h-2 w-full accent-primary"
      >
        {percent}%
      </progress>
      {/* Read out once per change, not per item: the text only changes
          wording at the start and the end. */}
      <p aria-live="polite" className="text-sm">
        {text}
      </p>
      {live.last !== undefined && live.status === 'running' && (
        <p className="text-xs text-muted-foreground">
          Latest: <span className="font-mono">{live.last}</span>
        </p>
      )}
    </div>
  );
}

function LatestRun({
  run,
  loading,
}: {
  run: VerifyRun | undefined;
  loading: boolean;
}) {
  if (loading) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Loading the verify runs…
      </p>
    );
  }
  if (run === undefined) {
    return (
      <p className="text-sm text-muted-foreground">
        No verify run for this date yet.
      </p>
    );
  }
  const when = run.finishedAt ?? run.startedAt ?? run.requestedAt;
  return (
    <p className="text-sm text-muted-foreground">
      Latest run #{run.runId}
      {run.requestedBy === null ? '' : ` by ${run.requestedBy}`},{' '}
      <time dateTime={when}>
        {formatLongDate(newYorkDateOf(when))} {formatEtTime(when)} ET
      </time>
      : {verifyRunSummary(run)}
    </p>
  );
}
