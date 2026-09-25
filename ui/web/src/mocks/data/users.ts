import type {AuthUser} from '@/api/schemas/auth';

/** The mock password of every seeded user. */
export const MOCK_PASSWORD = 'demo';

/** The seeded users (the login page lists them in mock mode). */
export const MOCK_USERS: readonly AuthUser[] = [
  {username: 'trader1', role: 'TRADER'},
  {username: 'analyst1', role: 'ANALYST'},
  {username: 'admin1', role: 'ADMIN'},
];
