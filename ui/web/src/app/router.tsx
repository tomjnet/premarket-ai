import type {RouteObject} from 'react-router';

import {AppShell, RootLayout} from '@/components/layout/root-layout';
import {ErrorPage} from '@/components/pages/error-page';
import {NotFoundPage} from '@/components/pages/status-page';
import {LoginPage} from '@/features/auth/login-page';
import {RequireAuth, RequireRole} from '@/features/auth/require-auth';
import {ChatPage} from '@/features/chat/chat-page';
import {FeedPage} from '@/features/news/feed-page';
import {NewsDetailPage} from '@/features/news/news-detail-page';
import {REVIEW_ROLES} from '@/features/review/review';
import {ReviewPage} from '@/features/review/review-page';

/**
 * The route tree. Everything but `/login` needs a session; a page that needs
 * a role wraps its route in `RequireRole` (the review queue: ANALYST and
 * ADMIN).
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
              {
                element: <RequireRole roles={REVIEW_ROLES} />,
                children: [{path: 'review', element: <ReviewPage />}],
              },
              {path: '*', element: <NotFoundPage />},
            ],
          },
        ],
      },
    ],
  },
];
