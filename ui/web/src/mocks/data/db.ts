import type {TokenResponseWire} from '@/api/schemas/auth';
import type {NewsDetailWire, Verdict} from '@/api/schemas/news';
import type {
  AdminSourceWire,
  AdminUserWire,
  AlertWire,
  CloudSwitches,
} from '@/api/schemas/ops';
import {ENV} from '@/lib/env';
import {todayInNewYork} from '@/lib/time';

import {emptyDay, generateDay, parseItemId} from './generator';
import type {GeneratedDay} from './generator';
import {MOCK_PASSWORD, MOCK_USERS, mockAdminUsers, mockSources} from './users';

/** How fast the mock "model" writes: about 25 tokens a second. */
const CHAT_TOKEN_DELAY_MS = 40;
/** How long the mock verify run takes per item. */
const RUN_ITEM_MS = 150;
/** How long each step of a mock brief takes (increment 5). */
const BRIEF_STEP_MS = 400;

/** A brief written with `POST /briefs` (increment 5). */
export interface StartedBrief {
  briefId: number;
  date: string;
  edition: 'morning' | 'refresh';
  requestedBy: string;
  /** Epoch ms: its steps come every `briefStepMs` from here. */
  startedAt: number;
}

/** An analyst's decision on a review task (`POST /review/{id}`). */
export interface ReviewRecord {
  action: 'approve' | 'override';
  /** The analyst's verdict (override only). */
  verdict: Verdict | null;
  comment: string;
  reviewer: string;
  decidedAt: string;
}

/** A verify run started with `POST /runs`. */
export interface StartedRun {
  runId: number;
  date: string;
  requestedBy: string;
  /** Epoch ms: the run progresses one item every `runItemMs` from here. */
  startedAt: number;
}

interface AccessToken {
  username: string;
  expiresAt: number;
}

/**
 * Where the mock keeps its stand-in for the refresh cookie (the username of
 * the session). The browser uses sessionStorage so the session survives a
 * reload, like a real cookie; tests keep it in memory.
 */
export interface SessionStore {
  load(): string | undefined;
  save(username: string | undefined): void;
}

function memorySessionStore(): SessionStore {
  let username: string | undefined;
  return {
    load: () => username,
    save: value => {
      username = value;
    },
  };
}

/**
 * The mock backend's state. MSW can't set real httpOnly cookies, so the
 * refresh-cookie session lives here (one browser, one session); the client
 * code is the same in mock and live mode.
 */
export class MockDb {
  tokenTtlS = ENV.mockTokenTtlS;
  // Late-bound, so tests that fake Date (vi.useFakeTimers) move this clock.
  now: () => number = () => Date.now();
  today: () => string = () => todayInNewYork();
  sessionStore: SessionStore = memorySessionStore();
  /** Pause between two streamed answer tokens of `POST /chat`. */
  chatTokenDelayMs = CHAT_TOKEN_DELAY_MS;
  /** Users with a question being answered (one at a time each). */
  readonly chatsInFlight = new Set<string>();
  /** Answered questions (`date|question`): the semantic cache stand-in. */
  readonly chatCache = new Set<string>();
  /** Watchlists by username (`PUT /me/watchlist`). */
  readonly watchlists = new Map<
    string,
    {tickers: string[]; sectors: string[]}
  >();
  /** Briefs written with `POST /briefs` in this session, oldest first. */
  readonly startedBriefs: StartedBrief[] = [];
  /** Pause between two progress events of a brief being written. */
  briefStepMs = BRIEF_STEP_MS;
  /** Pause between two items of a started verify run. */
  runItemMs = RUN_ITEM_MS;
  /** Review decisions by task id (the reviewed item's id). */
  readonly reviews = new Map<number, ReviewRecord>();
  /** Verify runs started in this session, oldest first. */
  readonly startedRuns: StartedRun[] = [];
  /** Increment 6: the operations banner's events, oldest first. */
  readonly alerts: AlertWire[] = [];
  /** This month's cloud spend and cap (`GET /llm/budget`). */
  cloudSpendUsd = 0;
  cloudCapUsd = 20;
  /** The admin page's users, sources and cloud switches. */
  readonly adminUsers = new Map<string, AdminUserWire>();
  readonly sources = new Map<string, AdminSourceWire>();
  cloudSwitches: CloudSwitches = {enabled: true, judge: true, brief: true};
  private runCounter = 0;
  private readonly accessTokens = new Map<string, AccessToken>();
  private tokenCounter = 0;
  private readonly days = new Map<string, GeneratedDay>();
  private readonly runStarts = new Map<string, number>();

  /** Back to a fresh start: no session, no tokens, default settings. */
  reset(): void {
    this.tokenTtlS = ENV.mockTokenTtlS;
    this.now = () => Date.now();
    this.today = () => todayInNewYork();
    this.sessionStore = memorySessionStore();
    this.chatTokenDelayMs = CHAT_TOKEN_DELAY_MS;
    this.chatsInFlight.clear();
    this.chatCache.clear();
    this.watchlists.clear();
    this.startedBriefs.length = 0;
    this.briefStepMs = BRIEF_STEP_MS;
    this.runItemMs = RUN_ITEM_MS;
    this.reviews.clear();
    this.startedRuns.length = 0;
    this.runCounter = 0;
    this.accessTokens.clear();
    this.runStarts.clear();
    this.alerts.length = 0;
    this.cloudSpendUsd = 0;
    this.cloudCapUsd = 20;
    this.cloudSwitches = {enabled: true, judge: true, brief: true};
    this.seedAdmin();
  }

  /** The admin page's starting users and sources. */
  seedAdmin(): void {
    this.adminUsers.clear();
    for (const user of mockAdminUsers()) {
      this.adminUsers.set(user.username, user);
    }
    this.sources.clear();
    for (const source of mockSources()) {
      this.sources.set(source.domain, source);
    }
  }

  /** A token response for a right password, undefined otherwise. */
  login(username: string, password: string): TokenResponseWire | undefined {
    const user = MOCK_USERS.find(candidate => candidate.username === username);
    if (user === undefined || password !== MOCK_PASSWORD) {
      return undefined;
    }
    this.sessionStore.save(username);
    return this.issueToken(username);
  }

  /** A new token for the session "cookie", undefined without one. */
  refresh(): TokenResponseWire | undefined {
    const username = this.sessionStore.load();
    const known = MOCK_USERS.some(user => user.username === username);
    if (username === undefined || !known) {
      return undefined;
    }
    return this.issueToken(username);
  }

  logout(): void {
    this.sessionStore.save(undefined);
    this.accessTokens.clear();
  }

  /** Makes an access token invalid, as if it had expired. */
  revokeToken(token: string): void {
    this.accessTokens.delete(token);
  }

  /** The user of a valid, unexpired access token. */
  userForToken(token: string): string | undefined {
    const entry = this.accessTokens.get(token);
    if (entry === undefined || entry.expiresAt <= this.now()) {
      return undefined;
    }
    return entry.username;
  }

  /** The feed of a date. Dates after today in New York have no run yet. */
  day(date: string): GeneratedDay {
    if (date > this.today()) {
      return emptyDay(date);
    }
    let day = this.days.get(date);
    if (day === undefined) {
      day = generateDay(date);
      this.days.set(date, day);
    }
    return day;
  }

  /** One item by id, if its date has a feed. */
  item(id: number): NewsDetailWire | undefined {
    const parsed = parseItemId(id);
    if (parsed === undefined) {
      return undefined;
    }
    return this.day(parsed.date).items.find(item => item.id === id);
  }

  /**
   * When the `running` scenario first showed `date` (epoch ms): the run's
   * items arrive with time from then on.
   */
  runningSince(date: string): number {
    let since = this.runStarts.get(date);
    if (since === undefined) {
      since = this.now();
      this.runStarts.set(date, since);
    }
    return since;
  }

  /** Starts a verify run of `date` for `username`. */
  startRun(date: string, username: string): StartedRun {
    this.runCounter += 1;
    const run = {
      runId: this.runCounter,
      date,
      requestedBy: username,
      startedAt: this.now(),
    };
    this.startedRuns.push(run);
    return run;
  }

  /** Starts writing a brief of `date` (ids after the generated ones). */
  startBrief(
    date: string,
    edition: 'morning' | 'refresh',
    username: string,
  ): StartedBrief {
    const brief = {
      briefId: 900_000 + this.startedBriefs.length + 1,
      date,
      edition,
      requestedBy: username,
      startedAt: this.now(),
    };
    this.startedBriefs.push(brief);
    return brief;
  }

  /** The runs started for `date`, newest first. */
  runsOf(date: string): StartedRun[] {
    return this.startedRuns.filter(run => run.date === date).reverse();
  }

  private issueToken(username: string): TokenResponseWire {
    this.tokenCounter += 1;
    const token = `mock.${username}.${this.tokenCounter}`;
    this.accessTokens.set(token, {
      username,
      expiresAt: this.now() + this.tokenTtlS * 1000,
    });
    const user = MOCK_USERS.find(candidate => candidate.username === username);
    if (user === undefined) {
      throw new Error(`Unknown mock user ${username}`);
    }
    return {
      access_token: token,
      token_type: 'bearer',
      expires_in: this.tokenTtlS,
      user,
    };
  }
}

/** The one mock database the handlers share. */
export const db = new MockDb();
db.seedAdmin();
