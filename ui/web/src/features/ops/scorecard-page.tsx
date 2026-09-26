import {useQuery} from '@tanstack/react-query';
import {useState} from 'react';

import {errorMessage} from '@/api/errors';
import {
  getSchedule,
  getScorecard,
  getScorecardCsv,
  getScorecardSummary,
} from '@/api/ops';
import type {ScorecardDay} from '@/api/schemas/ops';
import {useDocumentTitle} from '@/components/layout/use-document-title';
import {LoadError} from '@/components/load-error';
import {Badge} from '@/components/ui/badge';
import {Button} from '@/components/ui/button';
import {Skeleton} from '@/components/ui/skeleton';
import {useSession} from '@/features/auth/session-context';
import {formatEtTime, formatLongDate, todayInNewYork} from '@/lib/time';

import {chartMax, chronological, percent, usd} from './ops';

/** The trend's length (the plan's 30-day view). */
export const SCORECARD_DAYS = 30;

/**
 * `/scorecard` (ANALYST, ADMIN): today's schedule and SLA checks, and what
 * the vendor really delivers: billable items (unique VERIFIED or
 * UNVERIFIED) against the contract, day by day, with a CSV export and the
 * weekly summary.
 */
export function ScorecardPage() {
  useDocumentTitle('Vendor scorecard');
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">Vendor scorecard</h1>
        <p className="text-muted-foreground">
          What the vendor delivers against its contract. Billable items are
          unique items that are VERIFIED or UNVERIFIED. FAKE, MISLEADING and
          duplicates don't count.
        </p>
      </div>
      <SlaPanel />
      <ScorecardSection />
    </div>
  );
}

function SlaPanel() {
  const {client} = useSession();
  const today = todayInNewYork();
  const schedule = useQuery({
    queryKey: ['schedule', today],
    queryFn: ({signal}) => getSchedule(today, {client, signal}),
  });
  return (
    <section aria-labelledby="sla-heading" className="flex flex-col gap-2">
      <h2 id="sla-heading" className="text-lg font-semibold">
        Today's schedule, {formatLongDate(today)}
      </h2>
      {schedule.isError && (
        <LoadError
          title="Couldn't load today's schedule"
          error={schedule.error}
          onRetry={() => void schedule.refetch()}
        />
      )}
      {schedule.isPending && <Skeleton className="h-16 w-full" />}
      {schedule.data !== undefined && (
        <>
          <p>
            {schedule.data.slaChecked === 0
              ? 'No SLA checks yet today (demo mode, or not a trading day).'
              : schedule.data.slaGreen
                ? `Every SLA green (${schedule.data.slaChecked} checks).`
                : 'An SLA was breached today.'}
          </p>
          {schedule.data.items.length > 0 && (
            <table className="w-full text-left text-sm">
              <caption className="sr-only">
                Today's scheduled jobs and SLA checks
              </caption>
              <thead>
                <tr className="border-b">
                  <th scope="col" className="py-1 pr-3">
                    Started (ET)
                  </th>
                  <th scope="col" className="py-1 pr-3">
                    Job
                  </th>
                  <th scope="col" className="py-1 pr-3">
                    Status
                  </th>
                  <th scope="col" className="py-1">
                    Detail
                  </th>
                </tr>
              </thead>
              <tbody>
                {schedule.data.items.map(run => (
                  <tr key={`${run.job}-${run.startedAt}`} className="border-b">
                    <td className="py-1 pr-3">
                      <time dateTime={run.startedAt}>
                        {formatEtTime(run.startedAt)}
                      </time>
                    </td>
                    <td className="py-1 pr-3">{run.job}</td>
                    <td className="py-1 pr-3">
                      <Badge
                        variant={
                          run.status === 'FAILED' || run.status === 'BREACHED'
                            ? 'destructive'
                            : 'secondary'
                        }
                      >
                        {run.status}
                      </Badge>
                    </td>
                    <td className="py-1">{run.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}

function ScorecardSection() {
  const {client} = useSession();
  const scorecard = useQuery({
    queryKey: ['scorecard', SCORECARD_DAYS],
    queryFn: ({signal}) => getScorecard(SCORECARD_DAYS, {client, signal}),
  });
  return (
    <section aria-labelledby="days-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="days-heading" className="text-lg font-semibold">
          Last {SCORECARD_DAYS} days
        </h2>
        <CsvButton />
      </div>
      {scorecard.isError && (
        <LoadError
          title="Couldn't load the scorecard"
          error={scorecard.error}
          onRetry={() => void scorecard.refetch()}
        />
      )}
      {scorecard.isPending && <Skeleton className="h-48 w-full" />}
      {scorecard.data !== undefined && scorecard.data.days.length === 0 && (
        <p>No scorecard yet. It is counted after each day's market open.</p>
      )}
      {scorecard.data !== undefined && scorecard.data.days.length > 0 && (
        <>
          <p>
            <strong>{scorecard.data.averageBillable}</strong> billable items a
            day on average, against <strong>{scorecard.data.contracted}</strong>{' '}
            contracted.
          </p>
          <TrendChart days={scorecard.data.days} />
          <DaysTable days={scorecard.data.days} />
        </>
      )}
      <WeeklySummary />
    </section>
  );
}

function CsvButton() {
  const {client} = useSession();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | undefined>(undefined);

  async function download() {
    setBusy(true);
    setProblem(undefined);
    try {
      const csv = await getScorecardCsv(SCORECARD_DAYS, {client});
      const url = URL.createObjectURL(new Blob([csv], {type: 'text/csv'}));
      const link = document.createElement('a');
      link.href = url;
      link.download = 'vendor-scorecard.csv';
      link.click();
      URL.revokeObjectURL(url);
    } catch (error: unknown) {
      setProblem(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      {problem !== undefined && (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      )}
      <Button
        variant="outline"
        size="sm"
        onClick={() => void download()}
        disabled={busy}
      >
        {busy ? 'Preparing…' : 'Download CSV'}
      </Button>
    </div>
  );
}

const CHART_W = 600;
const CHART_H = 180;
const PAD = 24;

function points(
  days: readonly ScorecardDay[],
  value: (day: ScorecardDay) => number,
  max: number,
): string {
  const step = days.length > 1 ? (CHART_W - 2 * PAD) / (days.length - 1) : 0;
  return days
    .map((day, i) => {
      const x = PAD + i * step;
      const y = CHART_H - PAD - (value(day) / max) * (CHART_H - 2 * PAD);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
}

/** Received and billable items per day, and the contract line. */
function TrendChart({days}: {days: readonly ScorecardDay[]}) {
  const ordered = chronological(days);
  const first = ordered[0];
  const last = ordered.at(-1);
  if (first === undefined || last === undefined) {
    return null;
  }
  const max = chartMax(ordered);
  const contractY =
    CHART_H - PAD - (first.contracted / max) * (CHART_H - 2 * PAD);
  return (
    <figure className="flex flex-col gap-1">
      <svg
        viewBox={`0 0 ${CHART_W} ${CHART_H}`}
        className="h-auto w-full max-w-3xl"
        role="img"
        aria-labelledby="trend-title"
      >
        <title id="trend-title">
          Received and billable items per day against the contract
        </title>
        <line
          x1={PAD}
          x2={CHART_W - PAD}
          y1={contractY}
          y2={contractY}
          className="stroke-muted-foreground"
          strokeDasharray="6 4"
        />
        <polyline
          points={points(ordered, day => day.received, max)}
          fill="none"
          className="stroke-sky-700"
          strokeWidth={2}
        />
        <polyline
          points={points(ordered, day => day.billable, max)}
          fill="none"
          className="stroke-emerald-700"
          strokeWidth={3}
        />
      </svg>
      <figcaption className="text-xs text-muted-foreground">
        Blue: items received. Green: billable items. Dashed: the contract (
        {first.contracted} a day). {first.date} to {last.date}.
      </figcaption>
    </figure>
  );
}

function DaysTable({days}: {days: readonly ScorecardDay[]}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Vendor scorecard by day</caption>
        <thead>
          <tr className="border-b">
            {[
              'Date',
              'Received',
              'Unique',
              'Duplicates',
              'FAKE',
              'MISLEADING',
              'Stale',
              'Injection',
              'Overrides',
              'Billable',
              'Cloud cost',
            ].map(name => (
              <th key={name} scope="col" className="py-1 pr-3">
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {days.map(day => (
            <tr key={day.date} className="border-b">
              <th scope="row" className="py-1 pr-3 font-normal">
                {day.date}
              </th>
              <td className="py-1 pr-3">{day.received}</td>
              <td className="py-1 pr-3">{day.unique}</td>
              <td className="py-1 pr-3">
                {day.duplicates} ({percent(day.rates.duplicate)})
              </td>
              <td className="py-1 pr-3">
                {day.fake} ({percent(day.rates.fake)})
              </td>
              <td className="py-1 pr-3">
                {day.misleading} ({percent(day.rates.misleading)})
              </td>
              <td className="py-1 pr-3">{day.stale}</td>
              <td className="py-1 pr-3">{day.injection}</td>
              <td className="py-1 pr-3">
                {day.overridden}/{day.reviewed}
              </td>
              <td className="py-1 pr-3 font-medium">
                {day.billable} / {day.contracted}
              </td>
              <td className="py-1 pr-3">{usd(day.cloudCostUsd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function WeeklySummary() {
  const {client} = useSession();
  const summary = useQuery({
    queryKey: ['scorecard', 'summary'],
    queryFn: ({signal}) => getScorecardSummary({client, signal}),
  });
  return (
    <section aria-labelledby="summary-heading" className="flex flex-col gap-2">
      <h2 id="summary-heading" className="text-lg font-semibold">
        Weekly summary
      </h2>
      {summary.isError && (
        <LoadError
          title="Couldn't write the weekly summary"
          error={summary.error}
          onRetry={() => void summary.refetch()}
        />
      )}
      {summary.isPending && (
        <div aria-busy="true">
          <p role="status" className="sr-only">
            Writing the weekly summary…
          </p>
          <Skeleton className="h-20 w-full" />
        </div>
      )}
      {summary.data !== undefined && (
        <>
          <p className="whitespace-pre-line">{summary.data.text}</p>
          <p className="text-xs text-muted-foreground">
            {summary.data.source === 'llm'
              ? `Written by ${summary.data.model} with the vendor-scorecard skill`
              : 'Built from the numbers'}
            {summary.data.lastDate !== null &&
              `, ${summary.data.days} days to ${summary.data.lastDate}`}
            .
          </p>
        </>
      )}
    </section>
  );
}
