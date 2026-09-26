import {Outlet, useLocation} from 'react-router';

import {AppFooter} from './app-footer';
import {AppHeader} from './app-header';
import {ComplianceNotices} from './compliance-notices';
import {PageMain} from './page-main';
import {RouteAnnouncer} from './route-announcer';

/**
 * Every page: skip link, compliance notices and footer. Each page (or the
 * app shell) renders its own `PageMain`.
 */
export function RootLayout() {
  return (
    <div className="flex min-h-svh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:ring-2 focus:ring-ring"
      >
        Skip to main content
      </a>
      <ComplianceNotices />
      <RouteAnnouncer />
      <div className="flex flex-1 flex-col">
        <Outlet />
      </div>
      <AppFooter />
    </div>
  );
}

/**
 * Pages for a logged-in user: the header above the page content. Routes
 * that need a role (`RequireRole`) go inside it, so the 403 page keeps the
 * header and the main landmark.
 */
export function AppShell() {
  const {pathname} = useLocation();
  return (
    <>
      <AppHeader />
      <PageMain focusKey={pathname} className="px-4 py-6">
        <Outlet />
      </PageMain>
    </>
  );
}
