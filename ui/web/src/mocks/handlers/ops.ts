import {HttpResponse, http} from 'msw';

import type {Role} from '@/api/schemas/auth';
import {
  DOMAIN,
  PASSWORD_MAX_CHARS,
  PASSWORD_MIN_CHARS,
  TIERS,
  USERNAME,
} from '@/api/schemas/ops';
import type {
  AdminLlmWire,
  AdminSourceWire,
  AdminUserWire,
  AlertWire,
  ScheduleWire,
  ScorecardDayWire,
} from '@/api/schemas/ops';
import type {ValidationIssue} from '@/api/schemas/errors';
import {apiUrl} from '@/lib/env';
import {addDays, isWeekend} from '@/lib/time';

import {db} from '../data/db';
import {MOCK_USERS} from '../data/users';

import {
  notFound,
  rejectUnauthenticated,
  requestUser,
  scenarioLatency,
  validationError,
} from './common';

/**
 * Production (increment 6): the budget, the operations alerts and their
 * stream, the scheduler's day, the vendor scorecard, and the ADMIN pages.
 */

const CONTRACTED = 100;
const ROLES: readonly Role[] = ['TRADER', 'ANALYST', 'ADMIN'];

function roleOf(request: Request): Role | undefined {
  const username = requestUser(request);
  return MOCK_USERS.find(user => user.username === username)?.role;
}

/** `403` unless the caller has one of `roles`. */
function forbiddenUnless(
  request: Request,
  roles: readonly Role[],
): Response | undefined {
  const role = roleOf(request);
  return role !== undefined && roles.includes(role)
    ? undefined
    : HttpResponse.json({detail: 'Forbidden'}, {status: 403});
}

function guard(request: Request, roles: readonly Role[]): Response | undefined {
  return rejectUnauthenticated(request) ?? forbiddenUnless(request, roles);
}

const OPS: readonly Role[] = ['ANALYST', 'ADMIN'];
const ADMIN: readonly Role[] = ['ADMIN'];

function nowZ(): string {
  return new Date(db.now()).toISOString().replace(/\.\d+Z$/, 'Z');
}

/** The firing alerts: the latest event of each key, if firing. */
function activeAlerts(): AlertWire[] {
  const latest = new Map<string, AlertWire>();
  for (const alert of db.alerts) {
    latest.set(alert.key, alert);
  }
  return [...latest.values()]
    .filter(alert => alert.status === 'firing')
    .reverse();
}

/** Adds an alert event to the mock stream (tests and the dev console). */
export function pushAlert(
  alert: Omit<AlertWire, 'id' | 'at'> & {at?: string},
): AlertWire {
  const event = {
    ...alert,
    id: `${db.now()}-${db.alerts.length}`,
    at: alert.at ?? nowZ(),
  };
  db.alerts.push(event);
  return event;
}

function budgetWire() {
  const share = db.cloudCapUsd > 0 ? db.cloudSpendUsd / db.cloudCapUsd : 1;
  return {
    spent_usd: db.cloudSpendUsd,
    cap_usd: db.cloudCapUsd,
    share: Math.round(share * 10_000) / 10_000,
    warning: share >= 0.8,
    reached: share >= 1,
  };
}

/** A day's scorecard, counted from the generated feed. */
function scorecardDay(date: string): ScorecardDayWire | undefined {
  const items = db.day(date).items;
  if (items.length === 0) {
    return undefined;
  }
  const unique = items.filter(item => !item.is_dup);
  const count = (list: typeof items, test: (i: (typeof items)[0]) => boolean) =>
    list.filter(test).length;
  const verified = count(unique, item => item.verdict === 'VERIFIED');
  const unverified = count(unique, item => item.verdict === 'UNVERIFIED');
  const misleading = count(unique, item => item.verdict === 'MISLEADING');
  const fake = count(unique, item => item.verdict === 'FAKE');
  const duplicates = items.length - unique.length;
  const reviewed = count(
    unique,
    item =>
      item.review_status === 'APPROVED' || item.review_status === 'OVERRIDDEN',
  );
  const overridden = count(unique, item => item.review_status === 'OVERRIDDEN');
  const share = (part: number, whole: number) =>
    whole === 0 ? 0 : Math.round((part / whole) * 10_000) / 10_000;
  const stale = count(items, item => item.reason_codes.includes('STALE'));
  const billable = verified + unverified;
  return {
    feed_date: date,
    received: items.length,
    unique_items: unique.length,
    duplicates,
    dup_url: count(items, item => item.dup_type === 'url'),
    dup_exact: count(items, item => item.dup_type === 'exact'),
    dup_near: count(items, item => item.dup_type === 'near'),
    dup_paraphrase: count(items, item => item.dup_type === 'paraphrase'),
    stale,
    verified,
    unverified,
    misleading,
    fake,
    failed: 0,
    pending_review: count(unique, item => item.review_status === 'PENDING'),
    injection: count(items, item =>
      item.reason_codes.includes('INJECTION_ATTEMPT'),
    ),
    avg_corroboration: 1.2,
    reviewed,
    overridden,
    billable,
    contracted: CONTRACTED,
    cloud_cost_usd: 0.04,
    rates: {
      duplicate_rate: share(duplicates, items.length),
      stale_rate: share(stale, items.length),
      fake_rate: share(fake, unique.length),
      misleading_rate: share(misleading, unique.length),
      override_rate: share(overridden, reviewed),
      billable_vs_contract: share(billable, CONTRACTED),
    },
    computed_at: `${date}T13:35:00Z`,
  };
}

/** The scorecard days up to today, newest first. */
function scorecardDays(days: number): ScorecardDayWire[] {
  const found: ScorecardDayWire[] = [];
  let date = db.today();
  for (let back = 0; back < days * 2 && found.length < days; back += 1) {
    if (!isWeekend(date)) {
      const day = scorecardDay(date);
      if (day !== undefined) {
        found.push(day);
      }
    }
    date = addDays(date, -1);
  }
  return found;
}

function daysParam(request: Request, fallback: number): number | Response {
  const raw = new URL(request.url).searchParams.get('days');
  const days = raw === null ? fallback : Number(raw);
  if (!Number.isInteger(days) || days < 1 || days > 90) {
    return validationError({
      loc: ['query', 'days'],
      msg: 'Input should be between 1 and 90',
      type: 'less_than_equal',
    });
  }
  return days;
}

function scheduleWire(date: string): ScheduleWire {
  if (isWeekend(date)) {
    return {date, items: [], sla_checked: 0, sla_green: false};
  }
  const at = (time: string) => `${date}T${time}Z`;
  const items = (
    [
      [
        'pipeline',
        'DONE',
        '10:00:00',
        '10:48:12',
        'rules DONE; enrich DONE; verify DONE (86/86)',
      ],
      ['sla-ingest', 'OK', '10:15:00', '10:15:00', 'ingest run DONE'],
      [
        'sla-backlog',
        'OK',
        '10:30:00',
        '10:30:00',
        '12 verify jobs queued (limit 50), run RUNNING',
      ],
      ['sla-verify', 'OK', '11:00:00', '11:00:00', 'verify run DONE (86/86)'],
      ['brief', 'DONE', '11:15:00', '11:16:40', 'morning brief published'],
      [
        'sla-brief',
        'OK',
        '11:30:00',
        '11:30:00',
        'morning brief DONE, published 07:16 ET',
      ],
    ] satisfies [string, string, string, string, string][]
  ).map(([job, status, started, finished, detail]) => ({
    job,
    run_mode: 'production' as const,
    status: status as ScheduleWire['items'][0]['status'],
    started_at: at(started),
    finished_at: at(finished),
    detail,
  }));
  return {date, items, sla_checked: 4, sla_green: true};
}

function csvOf(days: ScorecardDayWire[]): string {
  const columns = [
    'feed_date',
    'received',
    'unique_items',
    'duplicates',
    'fake',
    'misleading',
    'billable',
    'contracted',
  ] as const;
  const rows = [...days]
    .reverse()
    .map(day => columns.map(column => String(day[column])).join(','));
  return [columns.join(','), ...rows].join('\n') + '\n';
}

async function readJson(request: Request): Promise<Record<string, unknown>> {
  try {
    const body = (await request.json()) as unknown;
    return typeof body === 'object' && body !== null
      ? (body as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

function bodyIssue(msg: string, field: string): ValidationIssue {
  return {loc: ['body', field], msg, type: 'value_error'};
}

function llmWire(): AdminLlmWire {
  return {
    hw_profile: 'gpu4gb',
    main_model: 'main-gpu4gb',
    embed_model: 'embed-gpu4gb',
    guard_model: 'guard-gpu4gb',
    vector_store: 'pgvector',
    judge_cloud_model: '',
    brief_model: 'cloud-openai',
    cloud: db.cloudSwitches,
    budget: budgetWire(),
  };
}

export const opsHandlers = [
  http.get(apiUrl('/llm/budget'), async ({request}) => {
    await scenarioLatency();
    return rejectUnauthenticated(request) ?? HttpResponse.json(budgetWire());
  }),

  http.get(apiUrl('/alerts'), async ({request}) => {
    await scenarioLatency();
    const denied = guard(request, OPS);
    if (denied !== undefined) {
      return denied;
    }
    const items = activeAlerts();
    return HttpResponse.json({count: items.length, items});
  }),

  // The snapshot, then the stream ends (the app reconnects, like after the
  // server's hourly end).
  http.get(apiUrl('/alerts/stream'), async ({request}) => {
    await scenarioLatency();
    const denied = guard(request, OPS);
    if (denied !== undefined) {
      return denied;
    }
    const last = db.alerts.at(-1)?.id ?? '0-0';
    const body = `id: ${last}\nevent: snapshot\ndata: ${JSON.stringify({items: activeAlerts()})}\n\n`;
    return new HttpResponse(body, {
      headers: {'Content-Type': 'text/event-stream'},
    });
  }),

  http.get(apiUrl('/schedule'), async ({request}) => {
    await scenarioLatency();
    const denied = guard(request, OPS);
    if (denied !== undefined) {
      return denied;
    }
    const date = new URL(request.url).searchParams.get('date') ?? db.today();
    return HttpResponse.json(scheduleWire(date));
  }),

  http.get(apiUrl('/vendor/scorecard'), async ({request}) => {
    await scenarioLatency();
    const denied = guard(request, OPS);
    if (denied !== undefined) {
      return denied;
    }
    const days = daysParam(request, 30);
    if (days instanceof Response) {
      return days;
    }
    const items = scorecardDays(days);
    const average =
      items.length === 0
        ? 0
        : Math.round(
            (items.reduce((sum, day) => sum + day.billable, 0) / items.length) *
              10,
          ) / 10;
    return HttpResponse.json({
      count: items.length,
      items,
      average_billable: average,
      contracted: CONTRACTED,
    });
  }),

  http.get(apiUrl('/vendor/scorecard.csv'), async ({request}) => {
    await scenarioLatency();
    const denied = guard(request, OPS);
    if (denied !== undefined) {
      return denied;
    }
    const days = daysParam(request, 30);
    if (days instanceof Response) {
      return days;
    }
    return new HttpResponse(csvOf(scorecardDays(days)), {
      headers: {'Content-Type': 'text/csv; charset=utf-8'},
    });
  }),

  http.get(apiUrl('/vendor/scorecard/summary'), async ({request}) => {
    await scenarioLatency();
    const denied = guard(request, OPS);
    if (denied !== undefined) {
      return denied;
    }
    const days = scorecardDays(7);
    const billable =
      days.reduce((sum, day) => sum + day.billable, 0) /
      Math.max(days.length, 1);
    return HttpResponse.json({
      text: `This week the vendor delivered ${billable.toFixed(0)} billable items a day against ${CONTRACTED} contracted.`,
      source: 'llm',
      model: 'main-gpu4gb',
      days: days.length,
      last_date: days[0]?.feed_date ?? null,
    });
  }),

  http.get(apiUrl('/admin/users'), async ({request}) => {
    await scenarioLatency();
    const denied = guard(request, ADMIN);
    if (denied !== undefined) {
      return denied;
    }
    const items = [...db.adminUsers.values()].sort((a, b) =>
      a.username.localeCompare(b.username),
    );
    return HttpResponse.json({count: items.length, items});
  }),

  http.post(apiUrl('/admin/users'), async ({request}) => {
    await scenarioLatency();
    const denied = guard(request, ADMIN);
    if (denied !== undefined) {
      return denied;
    }
    const body = await readJson(request);
    const {username, role, password} = body;
    if (typeof username !== 'string' || !USERNAME.test(username)) {
      return validationError(bodyIssue('Invalid username', 'username'));
    }
    if (typeof role !== 'string' || !ROLES.includes(role as Role)) {
      return validationError(bodyIssue('Invalid role', 'role'));
    }
    if (
      typeof password !== 'string' ||
      password.length < PASSWORD_MIN_CHARS ||
      password.length > PASSWORD_MAX_CHARS
    ) {
      return validationError(bodyIssue('Invalid password', 'password'));
    }
    if (db.adminUsers.has(username)) {
      return HttpResponse.json(
        {detail: 'The username is taken'},
        {status: 409},
      );
    }
    const user: AdminUserWire = {
      username,
      role: role as Role,
      disabled: false,
      created_at: nowZ(),
      updated_at: nowZ(),
    };
    db.adminUsers.set(username, user);
    return HttpResponse.json(user, {status: 201});
  }),

  http.post(apiUrl('/admin/users/:username'), async ({request, params}) => {
    await scenarioLatency();
    const denied = guard(request, ADMIN);
    if (denied !== undefined) {
      return denied;
    }
    const username = String(params.username);
    const found = db.adminUsers.get(username);
    if (found === undefined) {
      return notFound();
    }
    const body = await readJson(request);
    const role =
      typeof body.role === 'string' ? (body.role as Role) : undefined;
    const disabled =
      typeof body.disabled === 'boolean' ? body.disabled : undefined;
    if (
      username === requestUser(request) &&
      (disabled === true || (role !== undefined && role !== 'ADMIN'))
    ) {
      return HttpResponse.json(
        {detail: "You can't disable or demote your own account"},
        {status: 409},
      );
    }
    const changed: AdminUserWire = {
      ...found,
      role: role ?? found.role,
      disabled: disabled ?? found.disabled,
      updated_at: nowZ(),
    };
    db.adminUsers.set(username, changed);
    return HttpResponse.json(changed);
  }),

  http.get(apiUrl('/admin/sources'), async ({request}) => {
    await scenarioLatency();
    const denied = guard(request, ADMIN);
    if (denied !== undefined) {
      return denied;
    }
    const query = new URL(request.url).searchParams.get('q') ?? '';
    const items = [...db.sources.values()]
      .filter(source => source.domain.includes(query))
      .sort((a, b) => a.domain.localeCompare(b.domain));
    return HttpResponse.json({count: items.length, items});
  }),

  http.post(apiUrl('/admin/sources'), async ({request}) => {
    await scenarioLatency();
    const denied = guard(request, ADMIN);
    if (denied !== undefined) {
      return denied;
    }
    const body = await readJson(request);
    const {domain, tier, reputation, note} = body;
    if (typeof domain !== 'string' || !DOMAIN.test(domain)) {
      return validationError(bodyIssue('Invalid domain', 'domain'));
    }
    if (
      typeof tier !== 'string' ||
      !(TIERS as readonly string[]).includes(tier)
    ) {
      return validationError(bodyIssue('Invalid tier', 'tier'));
    }
    if (typeof reputation !== 'number' || reputation < 0 || reputation > 1) {
      return validationError(bodyIssue('Invalid score', 'reputation'));
    }
    const source: AdminSourceWire = {
      domain,
      tier: tier as AdminSourceWire['tier'],
      reputation,
      note: typeof note === 'string' ? note : '',
      updated_at: nowZ(),
    };
    db.sources.set(domain, source);
    return HttpResponse.json(source);
  }),

  http.get(apiUrl('/admin/llm'), async ({request}) => {
    await scenarioLatency();
    return guard(request, ADMIN) ?? HttpResponse.json(llmWire());
  }),

  http.post(apiUrl('/admin/llm'), async ({request}) => {
    await scenarioLatency();
    const denied = guard(request, ADMIN);
    if (denied !== undefined) {
      return denied;
    }
    const body = await readJson(request);
    const next = {...db.cloudSwitches};
    for (const name of ['enabled', 'judge', 'brief'] as const) {
      const value = body[name];
      if (typeof value === 'boolean') {
        next[name] = value;
      }
    }
    db.cloudSwitches = next;
    return HttpResponse.json(llmWire());
  }),
];
