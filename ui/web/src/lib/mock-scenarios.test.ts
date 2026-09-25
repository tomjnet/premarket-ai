import {describe, expect, it} from 'vitest';

import {
  SCENARIO_STORAGE_KEY,
  scenarioFromPage,
  scenarioUrl,
} from './mock-scenarios';

function memoryStorage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
    values,
  };
}

describe('scenarioFromPage', () => {
  it('takes ?scenario= and remembers it for this tab', () => {
    const storage = memoryStorage();
    expect(scenarioFromPage('?scenario=failed', storage)).toBe('failed');
    expect(storage.values.get(SCENARIO_STORAGE_KEY)).toBe('failed');
  });

  it('falls back to the saved scenario, then to default', () => {
    const storage = memoryStorage({[SCENARIO_STORAGE_KEY]: 'slow'});
    expect(scenarioFromPage('', storage)).toBe('slow');
    expect(scenarioFromPage('', memoryStorage())).toBe('default');
    expect(scenarioFromPage('', undefined)).toBe('default');
  });

  it('ignores unknown names', () => {
    const storage = memoryStorage({[SCENARIO_STORAGE_KEY]: 'nope'});
    expect(scenarioFromPage('?scenario=%3Cscript%3E', storage)).toBe('default');
  });
});

describe('scenarioUrl', () => {
  it('sets ?scenario= and keeps the path and other parameters', () => {
    expect(
      scenarioUrl('http://localhost:5173/news?date=2026-09-24', 'failed'),
    ).toBe('http://localhost:5173/news?date=2026-09-24&scenario=failed');
    expect(scenarioUrl('http://localhost:5173/?scenario=slow', 'default')).toBe(
      'http://localhost:5173/?scenario=default',
    );
  });
});
