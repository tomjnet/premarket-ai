import {render} from '@testing-library/react';
import {userEvent} from '@testing-library/user-event';
import {StrictMode} from 'react';
import {RouterProvider, createMemoryRouter} from 'react-router';
import type {RouteObject} from 'react-router';

import {ApiClient} from '@/api/client';
import {Providers} from '@/app/providers';
import {createQueryClient} from '@/app/query-client';
import {routes} from '@/app/router';
import {db} from '@/mocks/data/db';

/**
 * Renders the real app (or `appRoutes`) at `path`, with a fresh API client
 * and query cache, against the MSW mock backend.
 */
export function renderApp(path = '/', appRoutes: RouteObject[] = routes) {
  const client = new ApiClient({baseUrl: '/api'});
  const queryClient = createQueryClient({retry: false});
  const router = createMemoryRouter(appRoutes, {initialEntries: [path]});
  const user = userEvent.setup();
  // StrictMode, as in main.tsx: effects run twice, like in dev.
  const view = render(
    <StrictMode>
      <Providers client={client} queryClient={queryClient}>
        <RouterProvider router={router} />
      </Providers>
    </StrictMode>,
  );
  return {...view, user, router, client, queryClient};
}

/**
 * Opens a mock session, as if `username` had logged in earlier: the app
 * restores it through the refresh cookie on start.
 */
export function withMockSession(username = 'trader1'): void {
  db.login(username, 'demo');
}
