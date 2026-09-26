import {useLayoutEffect, useRef} from 'react';
import type {ReactNode} from 'react';

import {cn} from '@/lib/utils';

// Focus moves only in answer to the user (login, logout, a clicked link):
// on a fresh page load the skip link must stay the first Tab stop.
let userHasInteracted = false;
function markInteracted() {
  userHasInteracted = true;
}
if (typeof document !== 'undefined') {
  document.addEventListener('keydown', markInteracted, true);
  document.addEventListener('pointerdown', markInteracted, true);
}

interface PageMainProps {
  /** Changes on navigation (the path); focus is re-checked then. */
  focusKey?: string;
  className?: string;
  children: ReactNode;
}

/**
 * The page's `<main id="main">`, the skip link's target. After navigation,
 * if the focused element disappeared (the Log in button, a clicked link),
 * focus moves here instead of falling back to the top of the document.
 */
export function PageMain({focusKey, className, children}: PageMainProps) {
  const ref = useRef<HTMLElement>(null);
  // A layout effect: focus moves in the same commit as the new page, before
  // anyone (or any test) can see the page without it.
  useLayoutEffect(() => {
    const active = document.activeElement;
    if (userHasInteracted && (active === null || active === document.body)) {
      ref.current?.focus();
    }
  }, [focusKey]);
  return (
    <main
      id="main"
      ref={ref}
      tabIndex={-1}
      className={cn('flex-1 outline-none', className)}
    >
      {children}
    </main>
  );
}
