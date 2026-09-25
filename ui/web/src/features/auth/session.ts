import {tabStorage} from '@/lib/storage';

/** Pure session rules, kept out of React so they are easy to test. */

const REFRESH_MARGIN_MS = 60_000;

/**
 * When to refresh a token that expires in `remainingMs`: about 60 s before
 * it expires, but never sooner than half-way, so a short token lifetime
 * (a 60 s mock TTL, for example) can't cause a refresh loop.
 */
export function proactiveRefreshDelayMs(remainingMs: number): number {
  return Math.max(0, remainingMs - REFRESH_MARGIN_MS, remainingMs / 2);
}

/**
 * The `?next=` target after login, if it is a path on this site. Anything
 * else (`https://evil.example`, `//evil.example`, `javascript:`) becomes `/`,
 * so the login page can't be used as an open redirect.
 */
export function safeNextPath(next: string | null): string {
  if (
    next === null ||
    !next.startsWith('/') ||
    next.startsWith('//') ||
    next.startsWith('/login') ||
    [...next].some(isUnsafeChar)
  ) {
    return '/';
  }
  return next;
}

/**
 * URL parsers drop tabs and newlines and read `\` as `/`, so `/\t/evil` or
 * `/\evil` would become `//evil`: such characters are rejected outright.
 */
function isUnsafeChar(char: string): boolean {
  const code = char.charCodeAt(0);
  return code < 0x20 || code === 0x7f || char === '\\';
}

// "This tab had a session": lets a failed restore on reload say "your
// session expired" instead of silently showing the login form. Holds no
// token or user data.
const HAD_SESSION_KEY = 'premarket-ai.had-session';

export function rememberHadSession(): void {
  tabStorage()?.setItem(HAD_SESSION_KEY, '1');
}

export function forgetHadSession(): void {
  tabStorage()?.removeItem(HAD_SESSION_KEY);
}

export function hadSession(): boolean {
  return tabStorage()?.getItem(HAD_SESSION_KEY) === '1';
}
