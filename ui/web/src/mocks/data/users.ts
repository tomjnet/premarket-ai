import type {AuthUser} from '@/api/schemas/auth';
import type {AdminSourceWire, AdminUserWire} from '@/api/schemas/ops';

/** The mock password of every seeded user. */
export const MOCK_PASSWORD = 'demo';

/** The seeded users (the login page lists them in mock mode). */
export const MOCK_USERS: readonly AuthUser[] = [
  {username: 'trader1', role: 'TRADER'},
  {username: 'analyst1', role: 'ANALYST'},
  {username: 'admin1', role: 'ADMIN'},
];

const SEEDED_AT = '2026-09-01T12:00:00Z';

/** The admin page's users (increment 6): the seeded ones, all active. */
export function mockAdminUsers(): AdminUserWire[] {
  return MOCK_USERS.map(user => ({
    username: user.username,
    role: user.role,
    disabled: false,
    created_at: SEEDED_AT,
    updated_at: SEEDED_AT,
  }));
}

/** A few domains of the source reputation list. */
export function mockSources(): AdminSourceWire[] {
  return [
    ['acme-market-wire.example', 'trusted', 0.9, 'The lab vendor wire'],
    ['pennyrocket.example', 'blocked', 0.05, 'Pump-and-dump site'],
    ['reuters-news.test', 'low', 0.1, 'Lookalike of a real outlet'],
    ['sec.gov', 'trusted', 1, 'Primary source'],
  ].map(([domain, tier, reputation, note]) => ({
    domain: domain as string,
    tier: tier as AdminSourceWire['tier'],
    reputation: reputation as number,
    note: note as string,
    updated_at: SEEDED_AT,
  }));
}
