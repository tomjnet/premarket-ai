import {RouterProvider, createBrowserRouter} from 'react-router';

import {apiClient} from '@/api/client';

import {Providers} from './providers';
import {createQueryClient} from './query-client';
import {routes} from './router';

// One router and one query cache per page load, created outside React so
// StrictMode's double render can't create a second router.
const router = createBrowserRouter(routes);
const queryClient = createQueryClient();

/** The app: providers around the router. */
export function App() {
  return (
    <Providers client={apiClient} queryClient={queryClient}>
      <RouterProvider router={router} />
    </Providers>
  );
}
