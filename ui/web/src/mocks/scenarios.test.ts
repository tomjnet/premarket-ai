import {describe, expect, it} from 'vitest';

import {
  activeScenario,
  scenarioLatencyMs,
  setScenario,
  takeForcedExpiry,
} from './scenarios';

describe('scenario state', () => {
  it('expires the session exactly once in expired-session', () => {
    setScenario('expired-session');
    expect(activeScenario()).toBe('expired-session');
    expect(takeForcedExpiry()).toBe(true);
    expect(takeForcedExpiry()).toBe(false);
  });

  it('adds 2–3 s of latency only in slow', () => {
    expect(scenarioLatencyMs(() => 0.5)).toBe(0);
    setScenario('slow');
    expect(scenarioLatencyMs(() => 0)).toBe(2000);
    expect(scenarioLatencyMs(() => 0.999)).toBe(2999);
  });
});
