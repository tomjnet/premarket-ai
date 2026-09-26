import {useState} from 'react';
import {Link, NavLink} from 'react-router';

import {Badge} from '@/components/ui/badge';
import {Button} from '@/components/ui/button';
import {useSession} from '@/features/auth/session-context';
import {formatLongDate, todayInNewYork} from '@/lib/time';

/** The current page's link is marked by weight and underline, not colour. */
function navLinkClass({isActive}: {isActive: boolean}): string {
  return isActive
    ? 'font-semibold underline underline-offset-4'
    : 'underline-offset-4 hover:underline';
}

/**
 * Product name, today in New York (the feed's default date), the main
 * navigation and the user.
 */
export function AppHeader() {
  const {status, logout} = useSession();
  const [loggingOut, setLoggingOut] = useState(false);
  const today = todayInNewYork();
  const user =
    status.kind === 'authenticated' ? status.session.user : undefined;

  function handleLogout() {
    setLoggingOut(true);
    // The session is cleared even if the request fails; the route guard then
    // shows the login page.
    logout().catch(() => setLoggingOut(false));
  }

  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <Link to="/" className="text-lg font-semibold">
          premarket-ai
        </Link>
        <p className="text-sm text-muted-foreground">
          Today in New York:{' '}
          <time dateTime={today}>{formatLongDate(today)}</time>
        </p>
        {user !== undefined && (
          <nav aria-label="Main">
            <ul className="flex gap-3 text-sm">
              <li>
                <NavLink to="/news" className={navLinkClass}>
                  News feed
                </NavLink>
              </li>
              <li>
                <NavLink to="/chat" className={navLinkClass}>
                  Ask the News
                </NavLink>
              </li>
            </ul>
          </nav>
        )}
      </div>
      {user !== undefined && (
        <section
          aria-label="Signed-in user"
          className="flex items-center gap-2 text-sm"
        >
          <span>
            Signed in as <strong>{user.username}</strong>
          </span>
          <Badge variant="secondary">{user.role}</Badge>
          <Button
            variant="outline"
            size="sm"
            onClick={handleLogout}
            disabled={loggingOut}
          >
            {loggingOut ? 'Logging out…' : 'Log out'}
          </Button>
        </section>
      )}
    </header>
  );
}
