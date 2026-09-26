import {useEffect, useState} from 'react';

import {alertStream} from '@/api/ops';
import type {Alert} from '@/api/schemas/ops';
import {useSession} from '@/features/auth/session-context';

import {applyAlertEvent} from '../ops';

/** Wait before reconnecting after the stream ended or broke. */
export const RECONNECT_MS = 5_000;

/**
 * The firing alerts, live: follows `GET /alerts/stream` while `enabled`,
 * and reconnects after `RECONNECT_MS` when the server ends the stream (it
 * does every hour) or it breaks.
 */
export function useAlerts(enabled: boolean): Alert[] {
  const {client} = useSession();
  const [alerts, setAlerts] = useState<Alert[]>([]);

  useEffect(() => {
    if (!enabled) {
      return undefined;
    }
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function follow(): Promise<void> {
      try {
        for await (const event of alertStream({
          client,
          signal: controller.signal,
        })) {
          setAlerts(current => applyAlertEvent(current, event));
        }
      } catch {
        // Broken or refused: try again later (the banner is best effort).
      }
      if (!controller.signal.aborted) {
        timer = setTimeout(() => void follow(), RECONNECT_MS);
      }
    }

    void follow();
    return () => {
      controller.abort();
      if (timer !== undefined) {
        clearTimeout(timer);
      }
    };
  }, [client, enabled]);

  return enabled ? alerts : [];
}
