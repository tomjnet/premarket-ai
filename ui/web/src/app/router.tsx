import type {RouteObject} from 'react-router';

import {AppShell, RootLayout} from '@/components/layout/root-layout';
import {ErrorPage} from '@/components/pages/error-page';
import {NotFoundPage} from '@/components/pages/status-page';
import {AdminPage} from '@/features/admin/admin-page';
import {LoginPage} from '@/features/auth/login-page';
import {RequireAuth, RequireRole} from '@/features/auth/require-auth';
import {BriefPage} from '@/features/brief/brief-page';
import {ChatPage} from '@/features/chat/chat-page';
import {FeedPage} from '@/features/news/feed-page';
import {NewsDetailPage} from '@/features/news/news-detail-page';
import {ADMIN_ROLES, OPS_ROLES} from '@/features/ops/ops';
import {ScorecardPage} from '@/features/ops/scorecard-page';
import {REVIEW_ROLES} from '@/features/review/review';
import {ReviewPage} from '@/features/review/review-page';
import {WatchlistPage} from '@/features/watchlist/watchlist-page';

/**
 * The route tree. Everything but `/login` needs a session; a page that needs
 * a role wraps its route in `RequireRole` (the review queue and the vendor
 * scorecard: ANALYST and ADMIN; administration: ADMIN).
 */
export const routes: RouteObject[] = [
  {
    element: <RootLayout />,
    errorElement: <ErrorPage />,
    children: [
      {path: '/login', element: <LoginPage />},
      {
        element: <RequireAuth />,
        children: [
          {
            element: <AppShell />,
            children: [
              {index: true, element: <FeedPage />},
              {path: 'news', element: <FeedPage />},
              {path: 'news/:id', element: <NewsDetailPage />},
              {path: 'chat', element: <ChatPage />},
              {path: 'brief', element: <BriefPage />},
              {path: 'watchlist', element: <WatchlistPage />},
              {
                element: <RequireRole roles={REVIEW_ROLES} />,
                children: [{path: 'review', element: <ReviewPage />}],
              },
              {
                element: <RequireRole roles={OPS_ROLES} />,
                children: [{path: 'scorecard', element: <ScorecardPage />}],
              },
              {
                element: <RequireRole roles={ADMIN_ROLES} />,
                children: [{path: 'admin', element: <AdminPage />}],
              },
              {path: '*', element: <NotFoundPage />},
            ],
          },
        ],
      },
    ],
  },
];
