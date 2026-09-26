import {useCallback, useEffect, useState} from 'react';

import {askNews} from '@/api/chat';
import type {ChatDone, ChatSources} from '@/api/schemas/chat';
import {useSession} from '@/features/auth/session-context';

import {chatErrorMessage} from '../chat';

/** One question and its answer. Kept in memory only, never stored. */
export interface ChatTurn {
  id: number;
  question: string;
  /** The feed date whose vendor items the answer may cite. */
  date: string;
  status: 'answering' | 'done' | 'failed' | 'cancelled';
  /** The numbered sources, once the `sources` event arrived. */
  sources?: ChatSources;
  /** The text streamed so far (replaced by `done.answer` at the end). */
  streamed: string;
  done?: ChatDone;
  /** What went wrong, for a failed turn. */
  error?: string;
}

const STOPPED_EARLY = 'The answer stopped before it finished. Try again.';

/**
 * "Ask the News": the conversation of this page visit, one question at a
 * time. `ask` streams the answer into the latest turn; `cancel` stops it.
 */
export function useAskNews() {
  const {client} = useSession();
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  // The one answer in flight, if any; a Set so unmount can abort it.
  const [inFlight] = useState(() => new Set<AbortController>());
  const [nextId] = useState(() => ({value: 1}));

  // Leaving the page stops the answer (and frees the server's slot).
  useEffect(
    () => () => {
      for (const controller of inFlight) {
        controller.abort();
      }
    },
    [inFlight],
  );

  const ask = useCallback(
    async (question: string, date: string): Promise<void> => {
      if (inFlight.size > 0) {
        return;
      }
      const controller = new AbortController();
      inFlight.add(controller);
      const id = nextId.value;
      nextId.value += 1;
      const update = (change: (turn: ChatTurn) => ChatTurn) =>
        setTurns(all =>
          all.map(turn => (turn.id === id ? change(turn) : turn)),
        );
      setTurns(all => [
        ...all,
        {id, question, date, status: 'answering', streamed: ''},
      ]);
      let finished = false;
      try {
        const events = askNews(
          {question, date},
          {client, signal: controller.signal},
        );
        for await (const event of events) {
          if (event.type === 'sources') {
            update(turn => ({...turn, sources: event.data}));
          } else if (event.type === 'token') {
            update(turn => ({...turn, streamed: turn.streamed + event.text}));
          } else if (event.type === 'done') {
            finished = true;
            update(turn => ({...turn, status: 'done', done: event.data}));
            break;
          } else {
            finished = true;
            // The streamed text is dropped: only a checked answer is shown.
            update(turn => ({
              ...turn,
              status: 'failed',
              streamed: '',
              error: event.detail,
            }));
            break;
          }
        }
        if (!finished) {
          update(turn => ({
            ...turn,
            status: 'failed',
            streamed: '',
            error: STOPPED_EARLY,
          }));
        }
      } catch (error: unknown) {
        if (controller.signal.aborted) {
          update(turn => ({...turn, status: 'cancelled', streamed: ''}));
        } else {
          update(turn => ({
            ...turn,
            status: 'failed',
            streamed: '',
            error: chatErrorMessage(error),
          }));
        }
      } finally {
        inFlight.delete(controller);
      }
    },
    [client, inFlight, nextId],
  );

  const cancel = useCallback(() => {
    for (const controller of inFlight) {
      controller.abort();
    }
  }, [inFlight]);

  const answering = turns.some(turn => turn.status === 'answering');
  return {turns, ask, cancel, answering};
}
