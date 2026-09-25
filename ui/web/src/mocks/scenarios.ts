import type {ScenarioName} from '@/lib/mock-scenarios';

const SLOW_MIN_MS = 2000;
const SLOW_MAX_MS = 3000;

const state: {active: ScenarioName; expireNextCall: boolean} = {
  active: 'default',
  expireNextCall: false,
};

export function activeScenario(): ScenarioName {
  return state.active;
}

export function setScenario(name: ScenarioName): void {
  state.active = name;
  state.expireNextCall = name === 'expired-session';
}

/**
 * `expired-session`: true exactly once, for the next authenticated call,
 * which then answers 401 so the client has to refresh.
 */
export function takeForcedExpiry(): boolean {
  const expire = state.expireNextCall;
  state.expireNextCall = false;
  return expire;
}

/** Extra latency for every call: 2–3 s in `slow`, none otherwise. */
export function scenarioLatencyMs(random: () => number = Math.random): number {
  if (state.active !== 'slow') {
    return 0;
  }
  return SLOW_MIN_MS + Math.round(random() * (SLOW_MAX_MS - SLOW_MIN_MS));
}
