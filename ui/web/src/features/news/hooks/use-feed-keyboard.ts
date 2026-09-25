import {useCallback, useEffect, useState} from 'react';
import type {RefObject} from 'react';

import {preferenceStorage} from '@/lib/storage';

const NON_TEXT_INPUTS = ['checkbox', 'radio', 'button', 'submit', 'reset'];
const SHORTCUTS_KEY = 'premarket-ai.feed-shortcuts';

/**
 * Single-key shortcuts on or off, remembered in this browser. WCAG 2.2
 * SC 2.1.4 requires a way to turn them off (speech input can type them).
 */
export function useShortcutsPreference() {
  const [enabled, setEnabled] = useState(
    () => preferenceStorage()?.getItem(SHORTCUTS_KEY) !== 'off',
  );
  const toggle = useCallback(() => {
    setEnabled(current => {
      preferenceStorage()?.setItem(SHORTCUTS_KEY, current ? 'off' : 'on');
      return !current;
    });
  }, []);
  return {enabled, toggle};
}

/** True while the user types, so single-key shortcuts must not fire. */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  if (target.isContentEditable) {
    return true;
  }
  if (target instanceof HTMLInputElement) {
    return !NON_TEXT_INPUTS.includes(target.type);
  }
  return (
    target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement
  );
}

/**
 * The row to move to: `delta` from `current` (-1 when no row has focus),
 * kept inside the list. -1 when there are no rows.
 */
export function nextRowIndex(
  current: number,
  delta: 1 | -1,
  count: number,
): number {
  if (count === 0) {
    return -1;
  }
  if (current < 0) {
    return 0;
  }
  return Math.min(count - 1, Math.max(0, current + delta));
}

/**
 * Feed shortcuts: `/` focuses the search, `j`/`k` move to the next/previous
 * row's headline link (Enter then opens it). Rows are `[data-feed-row]`
 * elements inside `listRef`, each with an `a[data-row-link]`. Off when
 * `enabled` is false.
 */
export function useFeedKeyboard(
  listRef: RefObject<HTMLElement | null>,
  searchRef: RefObject<HTMLInputElement | null>,
  enabled: boolean,
): void {
  useEffect(() => {
    if (!enabled) {
      return undefined;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (
        event.defaultPrevented ||
        event.ctrlKey ||
        event.metaKey ||
        event.altKey ||
        isTypingTarget(event.target)
      ) {
        return;
      }
      if (event.key === '/') {
        event.preventDefault();
        searchRef.current?.focus();
        return;
      }
      if (event.key !== 'j' && event.key !== 'k') {
        return;
      }
      const rows = Array.from(
        listRef.current?.querySelectorAll<HTMLElement>('[data-feed-row]') ?? [],
      );
      const current = rows.findIndex(row =>
        row.contains(document.activeElement),
      );
      const next = nextRowIndex(
        current,
        event.key === 'j' ? 1 : -1,
        rows.length,
      );
      const link = rows[next]?.querySelector<HTMLElement>('a[data-row-link]');
      if (link === null || link === undefined) {
        return;
      }
      event.preventDefault();
      link.focus();
      // jsdom has no scrollIntoView.
      if (typeof link.scrollIntoView === 'function') {
        link.scrollIntoView({block: 'nearest'});
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [listRef, searchRef, enabled]);
}
