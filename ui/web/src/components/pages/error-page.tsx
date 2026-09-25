import {useEffect} from 'react';
import {useRouteError} from 'react-router';

import {ComplianceNotices} from '@/components/layout/compliance-notices';
import {PageMain} from '@/components/layout/page-main';

import {StatusPage} from './status-page';

/**
 * Shown when a page crashes while rendering, instead of a blank screen. It
 * replaces the whole layout, so it renders the compliance notices itself.
 */
export function ErrorPage() {
  const error = useRouteError();
  useEffect(() => {
    console.error('Page crashed:', error);
  }, [error]);
  return (
    <div className="flex min-h-svh flex-col">
      <ComplianceNotices />
      <PageMain className="px-4">
        <StatusPage title="Something went wrong">
          This page hit an unexpected error. Reload the page to try again.
        </StatusPage>
      </PageMain>
    </div>
  );
}
