import type {Role} from '@/api/schemas/auth';
import type {AlertEvent} from '@/api/ops';
import type {Alert, ScorecardDay} from '@/api/schemas/ops';

/**
 * Production (increment 6): who sees the operations pages, the banner's
 * alert list, and the scorecard's numbers as text.
 */

/** Vendor scorecard, SLA panel and the operations banner. */
export const OPS_ROLES: readonly Role[] = ['ANALYST', 'ADMIN'];
/** Users, source reputation and LLM settings. */
export const ADMIN_ROLES: readonly Role[] = ['ADMIN'];

export function canSeeOps(role: Role | undefined): boolean {
  return role !== undefined && OPS_ROLES.includes(role);
}

export function isAdmin(role: Role | undefined): boolean {
  return role !== undefined && ADMIN_ROLES.includes(role);
}

/**
 * The firing alerts after one stream event, newest first: a snapshot
 * replaces the list; a `firing` event adds (or updates) its key, a
 * `resolved` one removes it.
 */
export function applyAlertEvent(current: Alert[], event: AlertEvent): Alert[] {
  if (event.type === 'snapshot') {
    return event.alerts.filter(alert => alert.status === 'firing');
  }
  const others = current.filter(alert => alert.key !== event.alert.key);
  if (event.alert.status === 'resolved') {
    return others;
  }
  return [event.alert, ...others];
}

/** 0.125 -> "12.5%", 0.2 -> "20%". */
export function percent(share: number): string {
  const value = Math.round(share * 1000) / 10;
  return `${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)}%`;
}

/** 0.0412 -> "$0.04", 12 -> "$12.00". */
export function usd(amount: number): string {
  return `$${amount.toFixed(2)}`;
}

/** Days oldest first, for a chart. */
export function chronological(days: readonly ScorecardDay[]): ScorecardDay[] {
  return [...days].sort((a, b) => a.date.localeCompare(b.date));
}

/** The chart's y range: at least the contract, rounded up to a ten. */
export function chartMax(days: readonly ScorecardDay[]): number {
  const top = Math.max(
    10,
    ...days.map(day => Math.max(day.received, day.billable, day.contracted)),
  );
  return Math.ceil(top / 10) * 10;
}
