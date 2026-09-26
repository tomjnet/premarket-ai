import {z} from 'zod';

import {isIsoDate} from '@/lib/time';

import {roleSchema} from './auth';

/**
 * Production (increment 6): the operations banner (`GET /alerts`, `GET
 * /alerts/stream`), the cloud budget (`GET /llm/budget`), the scheduler's
 * day (`GET /schedule`), the vendor scorecard (`GET /vendor/scorecard`,
 * `.csv`, `/summary`) and the ADMIN pages (`/admin/users`,
 * `/admin/sources`, `/admin/llm`).
 */

const isoDateSchema = z.string().refine(isIsoDate, 'Expected YYYY-MM-DD');
const utcDateTimeSchema = z.iso.datetime();

// --- alerts and budget -------------------------------------------------------

export const alertSeveritySchema = z.enum(['info', 'warning', 'critical']);
export type AlertSeverity = z.infer<typeof alertSeveritySchema>;

/** Wire format of one alert (an event of the Redis Stream `alerts`). */
export const alertWireSchema = z.object({
  id: z.string().regex(/^\d+-\d+$/),
  key: z.string().min(1),
  title: z.string().min(1),
  severity: alertSeveritySchema,
  status: z.enum(['firing', 'resolved']),
  detail: z.string(),
  source: z.enum(['scheduler', 'grafana', 'budget']),
  at: utcDateTimeSchema,
});

export type AlertWire = z.infer<typeof alertWireSchema>;
export type Alert = AlertWire;

/** `GET /alerts`: the alerts firing now, newest first. */
export const alertListSchema = z
  .object({
    count: z.number().int().nonnegative(),
    items: z.array(alertWireSchema),
  })
  .refine(list => list.count === list.items.length, {
    message: 'count must equal the number of items',
    path: ['count'],
  })
  .transform(list => list.items);

/** The `snapshot` event of `GET /alerts/stream`. */
export const alertSnapshotWireSchema = z.object({
  items: z.array(alertWireSchema),
});

/** Wire format of `GET /llm/budget`. */
export const budgetWireSchema = z.object({
  spent_usd: z.number().nonnegative(),
  cap_usd: z.number().nonnegative(),
  share: z.number().nonnegative(),
  warning: z.boolean(),
  reached: z.boolean(),
});

export type BudgetWire = z.infer<typeof budgetWireSchema>;

function toBudget(wire: BudgetWire) {
  return {
    spentUsd: wire.spent_usd,
    capUsd: wire.cap_usd,
    share: wire.share,
    warning: wire.warning,
    reached: wire.reached,
  };
}

export const budgetSchema = budgetWireSchema.transform(toBudget);
export type Budget = ReturnType<typeof toBudget>;

// --- the scheduler's day -----------------------------------------------------

export const scheduleStatusSchema = z.enum([
  'RUNNING',
  'DONE',
  'FAILED',
  'SKIPPED',
  'OK',
  'BREACHED',
]);

export const scheduleRunWireSchema = z.object({
  job: z.string().min(1),
  run_mode: z.enum(['production', 'demo', 'manual']),
  status: scheduleStatusSchema,
  started_at: utcDateTimeSchema,
  finished_at: utcDateTimeSchema.nullable(),
  detail: z.string(),
});

/** Wire format of `GET /schedule`. */
export const scheduleWireSchema = z.object({
  date: isoDateSchema,
  items: z.array(scheduleRunWireSchema),
  sla_checked: z.number().int().nonnegative(),
  sla_green: z.boolean(),
});

export type ScheduleWire = z.infer<typeof scheduleWireSchema>;

function toSchedule(wire: ScheduleWire) {
  return {
    date: wire.date,
    slaChecked: wire.sla_checked,
    slaGreen: wire.sla_green,
    items: wire.items.map(run => ({
      job: run.job,
      runMode: run.run_mode,
      status: run.status,
      startedAt: run.started_at,
      finishedAt: run.finished_at,
      detail: run.detail,
    })),
  };
}

export const scheduleSchema = scheduleWireSchema.transform(toSchedule);
export type Schedule = ReturnType<typeof toSchedule>;
export type ScheduleRun = Schedule['items'][number];

// --- the vendor scorecard ----------------------------------------------------

const count = z.number().int().nonnegative();
const share = z.number().min(0);

export const scorecardDayWireSchema = z.object({
  feed_date: isoDateSchema,
  received: count,
  unique_items: count,
  duplicates: count,
  dup_url: count,
  dup_exact: count,
  dup_near: count,
  dup_paraphrase: count,
  stale: count,
  verified: count,
  unverified: count,
  misleading: count,
  fake: count,
  failed: count,
  pending_review: count,
  injection: count,
  avg_corroboration: z.number().nonnegative(),
  reviewed: count,
  overridden: count,
  billable: count,
  contracted: count,
  cloud_cost_usd: z.number().nonnegative(),
  rates: z.object({
    duplicate_rate: share,
    stale_rate: share,
    fake_rate: share,
    misleading_rate: share,
    override_rate: share,
    billable_vs_contract: share,
  }),
  computed_at: utcDateTimeSchema,
});

export type ScorecardDayWire = z.infer<typeof scorecardDayWireSchema>;

/** Wire format of `GET /vendor/scorecard` (days newest first). */
export const scorecardWireSchema = z
  .object({
    count,
    items: z.array(scorecardDayWireSchema),
    average_billable: z.number().nonnegative(),
    contracted: count,
  })
  .refine(list => list.count === list.items.length, {
    message: 'count must equal the number of items',
    path: ['count'],
  });

export type ScorecardWire = z.infer<typeof scorecardWireSchema>;

function toScorecardDay(wire: ScorecardDayWire) {
  return {
    date: wire.feed_date,
    received: wire.received,
    unique: wire.unique_items,
    duplicates: wire.duplicates,
    duplicatesByType: {
      url: wire.dup_url,
      exact: wire.dup_exact,
      near: wire.dup_near,
      paraphrase: wire.dup_paraphrase,
    },
    stale: wire.stale,
    verified: wire.verified,
    unverified: wire.unverified,
    misleading: wire.misleading,
    fake: wire.fake,
    pendingReview: wire.pending_review,
    injection: wire.injection,
    avgCorroboration: wire.avg_corroboration,
    reviewed: wire.reviewed,
    overridden: wire.overridden,
    billable: wire.billable,
    contracted: wire.contracted,
    cloudCostUsd: wire.cloud_cost_usd,
    rates: {
      duplicate: wire.rates.duplicate_rate,
      stale: wire.rates.stale_rate,
      fake: wire.rates.fake_rate,
      misleading: wire.rates.misleading_rate,
      override: wire.rates.override_rate,
      billableVsContract: wire.rates.billable_vs_contract,
    },
  };
}

export const scorecardSchema = scorecardWireSchema.transform(wire => ({
  days: wire.items.map(toScorecardDay),
  averageBillable: wire.average_billable,
  contracted: wire.contracted,
}));

export type Scorecard = z.infer<typeof scorecardSchema>;
export type ScorecardDay = Scorecard['days'][number];

/** Wire format of `GET /vendor/scorecard/summary`. */
export const scorecardSummaryWireSchema = z.object({
  text: z.string(),
  source: z.enum(['llm', 'fallback']),
  model: z.string(),
  days: count,
  last_date: isoDateSchema.nullable(),
});

export const scorecardSummarySchema = scorecardSummaryWireSchema.transform(
  wire => ({
    text: wire.text,
    source: wire.source,
    model: wire.model,
    days: wire.days,
    lastDate: wire.last_date,
  }),
);

export type ScorecardSummary = z.infer<typeof scorecardSummarySchema>;

// --- admin -------------------------------------------------------------------

/** Login names the backend accepts. */
export const USERNAME = /^[a-z][a-z0-9_.-]{0,63}$/;
export const PASSWORD_MIN_CHARS = 12;
export const PASSWORD_MAX_CHARS = 256;
/** A lower-case host name. */
export const DOMAIN = /^([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;
export const TIERS = ['trusted', 'neutral', 'low', 'blocked'] as const;
export const tierSchema = z.enum(TIERS);
export type Tier = z.infer<typeof tierSchema>;

export const adminUserWireSchema = z.object({
  username: z.string().regex(USERNAME),
  role: roleSchema,
  disabled: z.boolean(),
  created_at: utcDateTimeSchema,
  updated_at: utcDateTimeSchema,
});

export type AdminUserWire = z.infer<typeof adminUserWireSchema>;

function toAdminUser(wire: AdminUserWire) {
  return {
    username: wire.username,
    role: wire.role,
    disabled: wire.disabled,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
  };
}

export const adminUserSchema = adminUserWireSchema.transform(toAdminUser);
export type AdminUser = ReturnType<typeof toAdminUser>;

export const adminUserListSchema = z
  .object({count, items: z.array(adminUserWireSchema)})
  .transform(list => list.items.map(toAdminUser));

export const adminSourceWireSchema = z.object({
  domain: z.string().min(1),
  tier: tierSchema,
  reputation: z.number().min(0).max(1),
  note: z.string(),
  updated_at: utcDateTimeSchema,
});

export type AdminSourceWire = z.infer<typeof adminSourceWireSchema>;

function toAdminSource(wire: AdminSourceWire) {
  return {
    domain: wire.domain,
    tier: wire.tier,
    reputation: wire.reputation,
    note: wire.note,
    updatedAt: wire.updated_at,
  };
}

export const adminSourceSchema = adminSourceWireSchema.transform(toAdminSource);
export type AdminSource = ReturnType<typeof toAdminSource>;

export const adminSourceListSchema = z
  .object({count, items: z.array(adminSourceWireSchema)})
  .transform(list => list.items.map(toAdminSource));

export const cloudSwitchesSchema = z.object({
  enabled: z.boolean(),
  judge: z.boolean(),
  brief: z.boolean(),
});

export type CloudSwitches = z.infer<typeof cloudSwitchesSchema>;

/** Wire format of `GET /admin/llm`. */
export const adminLlmWireSchema = z.object({
  hw_profile: z.string(),
  main_model: z.string(),
  embed_model: z.string(),
  guard_model: z.string(),
  vector_store: z.string(),
  judge_cloud_model: z.string(),
  brief_model: z.string(),
  cloud: cloudSwitchesSchema,
  budget: budgetWireSchema,
});

export type AdminLlmWire = z.infer<typeof adminLlmWireSchema>;

function toAdminLlm(wire: AdminLlmWire) {
  return {
    hwProfile: wire.hw_profile,
    mainModel: wire.main_model,
    embedModel: wire.embed_model,
    guardModel: wire.guard_model,
    vectorStore: wire.vector_store,
    judgeCloudModel: wire.judge_cloud_model,
    briefModel: wire.brief_model,
    cloud: wire.cloud,
    budget: toBudget(wire.budget),
  };
}

export const adminLlmSchema = adminLlmWireSchema.transform(toAdminLlm);
export type AdminLlm = ReturnType<typeof toAdminLlm>;
