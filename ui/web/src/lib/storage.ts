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
