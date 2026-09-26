import {useCallback, useEffect, useState} from 'react';

import {todayBrief, writeBrief} from '@/api/brief';
import {HttpError} from '@/api/errors';
import type {Brief, BriefEdition, BriefMeta} from '@/api/schemas/brief';
import {useSession} from '@/features/auth/session-context';

import {briefErrorMessage} from '../brief';

/** What the page shows of one date's brief. */
export interface BriefView {
  /** The date (a view of another date is not shown). */
  date: string;
  phase: 'loading' | 'writing' | 'done' | 'missing' | 'failed';
  meta?: BriefMeta;
  /** The writer's last progress line, while it is written. */
  progress?: string;
  brief?: Brief;
  error?: string;
}

/**
 * The date's brief from `GET /briefs/today` (server-sent events): at once
 * when it is written, or its progress and then the brief while it is
 * being written. `write` (ANALYST, ADMIN) queues a new edition and follows
 * it. Leaving the page or the date stops the stream.
 */
export function useTodayBrief(date: string) {
  const {client} = useSession();
  const [view, setView] = useState<BriefView>({date, phase: 'loading'});
  const [writeError, setWriteError] = useState<
    {date: string; message: string} | undefined
  >(undefined);
  // Bumped to read the stream again (after "Write the brief now").
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const set = (next: Omit<BriefView, 'date'>) => setView({date, ...next});
    void (async () => {
      let meta: BriefMeta | undefined;
      let progress: string | undefined;
      try {
        for await (const event of todayBrief(date, {
          client,
          signal: controller.signal,
        })) {
          if (event.type === 'brief') {
            meta = event.data;
            if (meta.status === 'QUEUED' || meta.status === 'RUNNING') {
              set({phase: 'writing', meta, progress: 'Waiting to start'});
            }
          } else if (event.type === 'status') {
            progress = event.detail;
            set({phase: 'writing', meta, progress});
          } else if (event.type === 'sections') {
            progress = `${event.verified} verified stories chosen, ${event.unconfirmed} to watch`;
            set({phase: 'writing', meta, progress});
          } else if (event.type === 'done') {
            set({phase: 'done', meta: event.data, brief: event.data});
            return;
          } else {
            set({phase: 'failed', meta, error: event.detail});
            return;
          }
        }
        set({
          phase: 'failed',
          meta,
          error: 'The brief stopped before it finished. Reload the page.',
        });
      } catch (error: unknown) {
        if (controller.signal.aborted) {
          return;
        }
        const missing = error instanceof HttpError && error.status === 404;
        set({
          phase: missing ? 'missing' : 'failed',
          error: briefErrorMessage(error, date),
        });
      }
    })();
    return () => controller.abort();
  }, [client, date, generation]);

  const write = useCallback(
    async (edition: BriefEdition) => {
      setWriteError(undefined);
      try {
        await writeBrief(date, edition, {client});
        setGeneration(value => value + 1);
      } catch (error: unknown) {
        setWriteError({date, message: briefErrorMessage(error, date)});
      }
    },
    [client, date],
  );

  const shown: BriefView = view.date === date ? view : {date, phase: 'loading'};
  return {
    view: shown,
    write,
    writeError: writeError?.date === date ? writeError.message : undefined,
  };
}
