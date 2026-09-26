import {Navigate, Outlet, useLocation} from 'react-router';

import type {Role} from '@/api/schemas/auth';
import {PageMain} from '@/components/layout/page-main';
import {useDocumentTitle} from '@/components/layout/use-document-title';
import {ForbiddenPage} from '@/components/pages/status-page';

import {useSession} from './session-context';

/**
 * Guards the pages behind login. While the session is being restored it
 * shows a status line; without a session it goes to `/login?next=<here>`.
 */
export function RequireAuth() {
  const {status} = useSession();
  const location = useLocation();
  if (status.kind === 'restoring') {
    return <RestoringSession />;
  }
  if (status.kind === 'anonymous') {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <Outlet />;
}

function RestoringSession() {
  useDocumentTitle('Restoring your session');
  return (
    <PageMain className="px-4 py-12">
      <p role="status" className="text-center text-muted-foreground">
        Restoring your session…
      </p>
    </PageMain>
  );
}

interface RequireRoleProps {
  roles: readonly Role[];
}

/**
 * Shows the 403 page to a user whose role isn't in `roles`. Place it inside
 * `AppShell` (so under `RequireAuth`): the 403 page keeps the header and
 * main landmark, and never shows while the session is restoring. The UI only
 * hides things; the backend enforces access.
 */
export function RequireRole({roles}: RequireRoleProps) {
  const {status} = useSession();
  const role =
    status.kind === 'authenticated' ? status.session.user.role : undefined;
  if (role === undefined || !roles.includes(role)) {
    return <ForbiddenPage />;
  }
  return <Outlet />;
}
