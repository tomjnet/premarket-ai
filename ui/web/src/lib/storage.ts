/**
 * This tab's sessionStorage, or undefined where the browser blocks storage.
 * Only for small, non-secret per-tab flags; never for tokens.
 */
export function tabStorage(): Storage | undefined {
  try {
    return window.sessionStorage;
  } catch {
    return undefined;
  }
}

/**
 * This browser's localStorage, or undefined where it is blocked. Only for
 * UI preferences (for example keyboard shortcuts on/off); never for tokens.
 */
export function preferenceStorage(): Storage | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}
