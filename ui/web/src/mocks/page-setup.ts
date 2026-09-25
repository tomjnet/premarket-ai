import {scenarioFromPage} from '@/lib/mock-scenarios';
import {tabStorage} from '@/lib/storage';

import {db} from './data/db';
import type {SessionStore} from './data/db';
import {setScenario} from './scenarios';

/** Stand-in for the refresh cookie: which user's session is open. */
const MOCK_SESSION_KEY = 'premarket-ai.mock-session';

/**
 * Prepares the mock for this page load: the scenario from `?scenario=` or
 * this tab's saved choice, and the mock session, kept in sessionStorage so
 * it survives a reload like the real refresh cookie.
 */
export function prepareMockBackend(): void {
  // Storage can be blocked; the URL parameter still works then.
  const storage = tabStorage();
  setScenario(scenarioFromPage(window.location.search, storage));
  if (storage !== undefined) {
    db.sessionStore = storageSessionStore(storage);
  }
}

function storageSessionStore(storage: Storage): SessionStore {
  return {
    load: () => storage.getItem(MOCK_SESSION_KEY) ?? undefined,
    save: username => {
      if (username === undefined) {
        storage.removeItem(MOCK_SESSION_KEY);
      } else {
        storage.setItem(MOCK_SESSION_KEY, username);
      }
    },
  };
}
