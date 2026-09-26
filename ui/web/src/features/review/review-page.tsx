import {useState} from 'react';
import {useNavigate, useSearchParams} from 'react-router';

import {useDocumentTitle} from '@/components/layout/use-document-title';
import {LoadError} from '@/components/load-error';
import {Input} from '@/components/ui/input';
import {Label} from '@/components/ui/label';
import {Skeleton} from '@/components/ui/skeleton';
import {formatLongDate, isIsoDate, todayInNewYork} from '@/lib/time';

import {ReviewTaskCard} from './components/review-task-card';
import {RunsPanel} from './components/runs-panel';
import {useDecideReview, useReviewQueue} from './hooks/use-review-queue';
import {useVerifyRun} from './hooks/use-verify-run';
import {reviewDate} from './review';

/**
 * `/review` (ANALYST, ADMIN): the items the AI wasn't sure about, highest
 * market impact first, with Approve / Change verdict; and the date's AI
 * verification with "Verify this date". The date is in the URL (`?date=`).
 */
export function ReviewPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const today = todayInNewYork();
  const date = reviewDate(searchParams, today);
  useDocumentTitle(`Review queue, ${formatLongDate(date)}`);
  const queue = useReviewQueue(date);
  const decide = useDecideReview(date);
  const verify = useVerifyRun(date);
  const [announcement, setAnnouncement] = useState('');

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">Review queue</h1>
        <p className="text-muted-foreground">
          Items the AI wasn't sure about. Approve its verdict, or change it and
          say why. Your decisions become labeled examples for the next
          evaluation.
        </p>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="review-date">Date</Label>
        <Input
          id="review-date"
          type="date"
          min="2020-01-01"
          max={today}
          value={date}
          onChange={event => {
            const next = event.target.value;
            if (isIsoDate(next) && next <= today) {
              void navigate({pathname: '/review', search: `?date=${next}`});
            }
          }}
          className="w-40"
        />
      </div>
      <RunsPanel date={date} verify={verify} />
      <p aria-live="polite" className="sr-only">
        {announcement}
      </p>
      <section aria-labelledby="queue-heading" className="flex flex-col gap-3">
        <h2 id="queue-heading" className="text-lg font-semibold">
          Waiting for review
          {queue.data !== undefined && ` (${queue.data.length})`}
        </h2>
        {queue.isError && (
          <LoadError
            title="Couldn't load the review queue"
            error={queue.error}
            onRetry={() => void queue.refetch()}
          />
        )}
        {queue.isPending && (
          <div aria-busy="true" className="flex flex-col gap-3">
            <p role="status" className="sr-only">
              Loading the review queue…
            </p>
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        )}
        {queue.data !== undefined && queue.data.length === 0 && (
          <p className="py-4">
            Nothing waiting for review on {formatLongDate(date)}.
          </p>
        )}
        {queue.data !== undefined && queue.data.length > 0 && (
          <ul aria-label="Review tasks" className="flex flex-col gap-3">
            {queue.data.map(task => (
              <ReviewTaskCard
                key={task.id}
                task={task}
                onDecide={async decision => {
                  const decided = await decide.mutateAsync({
                    id: task.id,
                    decision,
                  });
                  setAnnouncement(
                    decided.status === 'OVERRIDDEN'
                      ? `Verdict changed for ${decided.vendorItemId}.`
                      : `Verdict approved for ${decided.vendorItemId}.`,
                  );
                }}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
