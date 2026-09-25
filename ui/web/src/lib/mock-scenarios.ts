/**
 * The mock scenario names and how a page load picks one. Shared by the mock
 * backend (src/mocks) and the footer's scenario switcher, which must not
 * import mock code.
 */
export const SCENARIOS = [
  'default',
  'empty',
  'running',
  'failed',
  'slow',
  'server-error',
  'expired-session',
  'logged-out',
  'contract-drift',
] as const;

export type ScenarioName = (typeof SCENARIOS)[number];

/** Remembers the scenario across reloads in one tab (mock mode only). */
export const SCENARIO_STORAGE_KEY = 'premarket-ai.mock-scenario';

export function isScenarioName(value: unknown): value is ScenarioName {
  return SCENARIOS.some(name => name === value);
}

/**
 * The scenario for this page load: `?scenario=` wins, then the one saved in
 * this tab, then `default`. A valid `?scenario=` is saved for later loads.
 */
export function scenarioFromPage(
  search: string,
  storage: Pick<Storage, 'getItem' | 'setItem'> | undefined,
): ScenarioName {
  const fromUrl = new URLSearchParams(search).get('scenario');
  if (isScenarioName(fromUrl)) {
    storage?.setItem(SCENARIO_STORAGE_KEY, fromUrl);
    return fromUrl;
  }
  const saved = storage?.getItem(SCENARIO_STORAGE_KEY);
  return isScenarioName(saved) ? saved : 'default';
}

/** The current page's URL with `?scenario=` set, for the switcher's reload. */
export function scenarioUrl(href: string, name: ScenarioName): string {
  const url = new URL(href);
  url.searchParams.set('scenario', name);
  return url.toString();
}
