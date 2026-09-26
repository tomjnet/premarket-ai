import {useQuery} from '@tanstack/react-query';
import {useState} from 'react';

import {getBudget} from '@/api/ops';
import type {Alert} from '@/api/schemas/ops';
import {Button} from '@/components/ui/button';
import {useSession} from '@/features/auth/session-context';
import {formatEtTime} from '@/lib/time';

import {useAlerts} from '../hooks/use-alerts';
import {canSeeOps, percent} from '../ops';

/** How often the budget banner checks the spend. */
const BUDGET_REFRESH_MS = 5 * 60_000;

const SEVERITY_CLASS: Record<Alert['severity'], string> = {
  critical: 'border-red-700 bg-red-50 text-red-950',
  warning: 'border-amber-600 bg-amber-50 text-amber-950',
  info: 'border-border bg-muted text-foreground',
};

/**
 * The banners under the header (increment 6):
 *
 * - "Cloud budget reached, running local": every role, when the month's
 *   cloud spend reached the cap (analysts and admins also see 80%).
 * - Operations alerts (ANALYST, ADMIN): the SLA checks, Grafana's rules
 *   and the budget, live from the server. "Hide" hides one for this page
 *   visit only; it comes back if it fires again.
 */
export function OpsBanners() {
  const {status, client} = useSession();
  const role =
    status.kind === 'authenticated' ? status.session.user.role : undefined;
  const ops = canSeeOps(role);
  const budget = useQuery({
    queryKey: ['budget'],
    queryFn: ({signal}) => getBudget({client, signal}),
    enabled: role !== undefined,
    refetchInterval: BUDGET_REFRESH_MS,
    // A missing budget only hides the banner.
    retry: false,
  });
  const alerts = useAlerts(ops);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const shown = alerts.filter(alert => !hidden.has(alert.id));
  const spend = budget.data;
  const budgetBanner =
    spend !== undefined && (spend.reached || (ops && spend.warning));

  if (!budgetBanner && shown.length === 0) {
    return null;
  }
  return (
    <section aria-label="Operations" className="flex flex-col gap-2 px-4 pt-3">
      {budgetBanner && spend !== undefined && (
        <p
          role="status"
          className="rounded-md border border-amber-600 bg-amber-50 px-3 py-2 text-sm text-amber-950"
        >
          {spend.reached
            ? 'Cloud budget reached, running local.'
            : `Cloud budget at ${percent(spend.share)} this month.`}
        </p>
      )}
      {shown.length > 0 && (
        <ul aria-label="Operations alerts" className="flex flex-col gap-2">
          {shown.map(alert => (
            <li
              key={alert.key}
              className={`flex flex-wrap items-start justify-between gap-2 rounded-md border px-3 py-2 text-sm ${SEVERITY_CLASS[alert.severity]}`}
            >
              <div className="flex flex-col gap-0.5">
                <p className="font-medium">
                  <span className="uppercase">{alert.severity}</span>:{' '}
                  {alert.title}
                </p>
                {alert.detail !== '' && <p>{alert.detail}</p>}
                <p className="text-xs">
                  {alert.source},{' '}
                  <time dateTime={alert.at}>{formatEtTime(alert.at)}</time>
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  setHidden(current => new Set([...current, alert.id]))
                }
                aria-label={`Hide: ${alert.title}`}
              >
                Hide
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
