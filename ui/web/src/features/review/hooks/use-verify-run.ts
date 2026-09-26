import {useQuery, useQueryClient} from '@tanstack/react-query';
import {useCallback, useEffect, useState} from 'react';

import {runEvents, getRuns, startRun} from '@/api/verify';
import {useSession} from '@/features/auth/session-context';
import {newsKeys} from '@/features/news/query-keys';

import {reviewKeys} from '../query-keys';
import {startRunErrorMessage} from '../review';

/** A run being followed through its events. */
export interface LiveRun {
  /** The feed date it verifies (a run of another date is not shown). */
  date: string;
  runId: number;
  status: 'starting' | 'running' | 'done' | 'failed';
  done: number;
  total: number;
  /** Items sent to review so far. */
  toReview: number;
  /** The last item's vendor id and verdict, for the live region. */
  last?: string;
  error?: string;
}

/**
 * The date's verify runs, and "Verify this date": it starts a run and
 * follows its server-sent events until the run ends, then refreshes the
 * runs, the queue and the news. Leaving the page stops following (the run
 * goes on in the worker).
 */
export function useVerifyRun(date: string) {
  const {client} = useSession();
  const queryClient = useQueryClient();
  const runs = useQuery({
    queryKey: reviewKeys.runs(date),
    queryFn: ({signal}) => getRuns(date, {client, signal}),
  });
  const [live, setLive] = useState<LiveRun | undefined>(undefined);
  const [failure, setFailure] = useState<
    {date: string; message: string} | undefined
  >(undefined);
  const [controllers] = useState(() => new Set<AbortController>());

  useEffect(
    () => () => {
      for (const controller of controllers) {
        controller.abort();
      }
    },
    [controllers],
  );

  // A new date: stop following the old one's run (its state is no longer
  // shown: `live` and `failure` are keyed by date).
  useEffect(() => {
    for (const controller of controllers) {
      controller.abort();
    }
  }, [date, controllers]);

  const refresh = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({queryKey: reviewKeys.runs(date)}),
      queryClient.invalidateQueries({queryKey: reviewKeys.queue(date)}),
      queryClient.invalidateQueries({queryKey: newsKeys.all}),
    ]);
  }, [queryClient, date]);

  const start = useCallback(async () => {
    const controller = new AbortController();
    controllers.add(controller);
    setFailure(undefined);
    let runId: number | undefined;
    try {
      const run = await startRun(date, {client, signal: controller.signal});
      runId = run.runId;
      setLive({
        date,
        runId,
        status: 'starting',
        done: 0,
        total: run.total,
        toReview: 0,
      });
      await refresh();
      for await (const event of runEvents(runId, {
        client,
        signal: controller.signal,
      })) {
        if (event.type === 'started') {
          setLive(
            run => run && {...run, status: 'running', total: event.total},
          );
        } else if (event.type === 'item') {
          setLive(
            run =>
              run && {
                ...run,
                status: 'running',
                done: event.done,
                total: event.total,
                toReview: run.toReview + (event.review ? 1 : 0),
                last: `${event.vendorItemId ?? `item ${event.newsId}`}: ${
                  event.failed ? 'failed' : (event.verdict ?? 'no verdict')
                }`,
              },
          );
        } else if (event.type === 'done') {
          setLive(run => run && {...run, status: 'done'});
        } else if (event.type === 'failed') {
          setLive(run => run && {...run, status: 'failed', error: event.error});
        }
      }
    } catch (caught: unknown) {
      if (controller.signal.aborted) {
        return;
      }
      if (runId === undefined) {
        setFailure({date, message: startRunErrorMessage(caught)});
      } else {
        // The run goes on in the worker; only following it failed.
        setLive(
          run =>
            run && {
              ...run,
              status: 'failed',
              error:
                "Lost the run's progress. The list below shows its latest state.",
            },
        );
      }
    } finally {
      controllers.delete(controller);
      if (!controller.signal.aborted) {
        await refresh();
      }
    }
  }, [client, controllers, date, refresh]);

  const shown = live?.date === date ? live : undefined;
  const following =
    shown !== undefined &&
    (shown.status === 'starting' || shown.status === 'running');
  return {
    runs,
    live: shown,
    error: failure?.date === date ? failure.message : undefined,
    start,
    following,
  };
}
