import {describe, expect, it} from 'vitest';

import {
  forgetHadSession,
  hadSession,
  proactiveRefreshDelayMs,
  rememberHadSession,
  safeNextPath,
} from './session';

describe('proactiveRefreshDelayMs', () => {
  it('refreshes about 60 s before a normal token expires', () => {
    expect(proactiveRefreshDelayMs(900_000)).toBe(840_000);
  });

  it('waits at least half the lifetime of a short token (no loop)', () => {
    expect(proactiveRefreshDelayMs(60_000)).toBe(30_000);
    expect(proactiveRefreshDelayMs(2_000)).toBe(1_000);
  });

  it('refreshes right away when the token already expired', () => {
    expect(proactiveRefreshDelayMs(-5_000)).toBe(0);
  });
});

describe('safeNextPath', () => {
  it('keeps a path on this site, with its query', () => {
    expect(safeNextPath('/news?date=2026-09-24&ticker=AAPL')).toBe(
      '/news?date=2026-09-24&ticker=AAPL',
    );
  });

  it('falls back to / for anything else', () => {
    for (const next of [
      null,
      '',
      'news',
      'https://evil.example/',
      '//evil.example',
      '/\\evil.example',
      '/\t/evil.example',
      '/\n/evil.example',
      '/news\\..\\x',
      'javascript:alert(1)',
      '/login?next=/news',
    ]) {
      expect(safeNextPath(next)).toBe('/');
    }
  });
});

describe('had-session flag', () => {
  it('is remembered for the tab and can be forgotten', () => {
    expect(hadSession()).toBe(false);
    rememberHadSession();
    expect(hadSession()).toBe(true);
    forgetHadSession();
    expect(hadSession()).toBe(false);
  });
});
