import {QueryClientProvider} from '@tanstack/react-query';
import type {QueryClient} from '@tanstack/react-query';
import type {ReactNode} from 'react';

import type {ApiClient} from '@/api/client';
import {SessionProvider} from '@/features/auth/session-context';

interface ProvidersProps {
  client: ApiClient;
  queryClient: QueryClient;
  children: ReactNode;
}

/** Server state (TanStack Query) and the session, for the app and tests. */
export function Providers({client, queryClient, children}: ProvidersProps) {
  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider client={client}>{children}</SessionProvider>
    </QueryClientProvider>
  );
}
