import {useEffect, useRef, useState} from 'react';
import {useLocation} from 'react-router';

// The page sets its title in its own effect; wait a moment so a title that
// depends on quickly loaded data (the detail headline) is included.
const ANNOUNCE_DELAY_MS = 150;

/**
 * Tells screen readers which page opened after an in-app navigation (they
 * don't announce `document.title` changes in a single-page app). Silent on
 * the first page load, which the browser announces itself.
 */
export function RouteAnnouncer() {
  const {pathname} = useLocation();
  const lastPathname = useRef(pathname);
  const [message, setMessage] = useState('');

  useEffect(() => {
    // Also covers StrictMode's second effect run on the same path.
    if (pathname === lastPathname.current) {
      return undefined;
    }
    lastPathname.current = pathname;
    const timer = setTimeout(
      () => setMessage(document.title),
      ANNOUNCE_DELAY_MS,
    );
    return () => clearTimeout(timer);
  }, [pathname]);

  return (
    <p aria-live="polite" aria-atomic="true" className="sr-only">
      {message}
    </p>
  );
}
