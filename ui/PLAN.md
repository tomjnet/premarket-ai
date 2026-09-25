# premarket-ai web: plan for the UI module

This is the spec for `web`, the website that replaces the daily PDF. It
covers the front end only. The backend (`ai-api`) is built in parallel by
another team, so the UI is built **contract-first against mocks**: the JSON
below is the agreement, and a mock backend in the browser serves it until the
real API is ready.

Update this file when a decision changes, and log it in "Decision log".

---

## 1. Why this module exists
Traders read the vendor news before the US market opens (09:30 ET). Today they
get it as a PDF produced by a legacy batch job. This increment gives them a
**website** with the same news, easier to scan, filter and search. The PDF
keeps running in parallel until the website has proven itself.

**Done when:** a trader can log in and read today's news on the website
instead of the PDF, using only the mock backend, and the same build works
against the real backend by changing one environment variable.

## 2. Scope

### In scope (this increment)
- Login and logout, with the session kept alive by a refresh cookie.
- **News Feed** for one trading date: filters (date, ticker, text search,
  include duplicates), loading/empty/error states.
- **News detail**: the full item with its source link.
- App shell: header, user menu, the **SIMULATION ribbon** and the
  **"Decision support only, not investment advice"** banner.
- Role-aware routing (TRADER and ADMIN in this increment; ANALYST exists in the
  type so later pages slot in).
- A **mock backend** (MSW) with deterministic data and switchable scenarios.
- Unit, component and contract tests; Google TypeScript style via gts.

### Out of scope (later increments; design so they fit, don't build them)
| Later feature | What to keep in mind now |
|---|---|
| Verdict badges (VERIFIED / UNVERIFIED / MISLEADING / FAKE) and reason codes | The feed row has a badge area; `NewsItem` will gain optional fields |
| Rule badges (FAKE COMPANY, DUPLICATE ×N, STALE, SPOOFED SOURCE) | Same badge area |
| Evidence drill-down, Review Queue, Vendor Scorecard, Ask the News chat, streamed brief, Admin | Feature folders and routes are added per feature; nothing shared is built "just in case" |
| Server-sent events (brief, chat, alerts) | The API client is plain `fetch`, so an SSE helper can sit next to it later |
| Container image, compose service, CI | Not part of this module's work |

## 3. Users and roles
| Role | This increment | Seeded user (mock password: `demo`) |
|---|---|---|
| TRADER | Feed, detail | `trader1` |
| ANALYST | Same as TRADER for now | `analyst1` |
| ADMIN | Same as TRADER for now (admin pages come later) | `admin1` |

The role comes from the login/refresh response. The UI only uses it to hide
things; the backend enforces it.

## 4. Screens and behavior

### 4.1 App shell (every page)
- **SIMULATION ribbon**, always visible, never dismissible:
  "SIMULATION: synthetic vendor data".
- **Compliance banner**: "Decision support only, not investment advice."
  Visible on every authenticated page.
- Header: product name, current trading date, user menu (username, role,
  logout).
- Footer: backend status from `GET /health` (ok / unreachable), and in mock
  mode a "MOCK API" tag plus the scenario switcher (section 6.3).

### 4.2 Login (`/login`)
- Username and password, submit with Enter, clear error on 401
  ("Wrong username or password"), disabled button while sending.
- In mock mode only, a hint lists the seeded users.
- After login, go back to the page the user first asked for (default `/`).
- No self-signup, no "forgot password".

### 4.3 News Feed (`/` and `/news?date=…&ticker=…&q=…&dups=1`)
- Default date: today's date in America/New_York. On a weekend or when no
  ingest run exists for the date, show "No feed for <date>" with a link to the
  previous trading date that has one (the mock knows NYSE weekends; holidays
  can be ignored in the mock).
- **Filter state lives in the URL** (shareable, back button works). Text
  search is debounced (300 ms).
- Ingest run status for the date:
  - `DONE`: normal list, with "N items · M duplicates hidden · updated HH:MM ET".
  - `RUNNING`: "Today's feed is still arriving", poll every 30 s.
  - `FAILED`: an error panel; the page still shows whatever the API returned.
- Each row: published time (ET, `HH:MM`), tickers as chips (click = filter by
  that ticker), headline (links to the detail page), source domain, excerpt,
  and a reserved badge area (empty in this increment).
- Duplicates are **hidden by default**, matching the PDF. "Show duplicates"
  includes them, dimmed, with "Duplicate of <vendor_item_id>".
- Sorted newest first. No paging: a day is about 100 items.
- Keyboard: `/` focuses search, `j`/`k` move between rows, Enter opens.

### 4.4 News detail (`/news/:id`)
- Headline, published time (ET and UTC on hover), tickers, source domain and
  an external link to `source_url`, full body, feed date, vendor item id,
  duplicate info.
- Back link keeps the feed's filters.
- 404 → "This item doesn't exist" with a link back to the feed.

### 4.5 Other routes
- `403` page for a role that can't see a route, `404` for unknown routes.
- Session expired (refresh fails) → back to `/login?next=…` with a notice.

## 5. API contract v0 (wire format)
The backend is FastAPI. JSON on the wire is **snake_case**; the UI converts it
to camelCase in one place (the schema layer), so no snake_case reaches
components. All times are ISO 8601 UTC (`Z`). Dates are `YYYY-MM-DD`.

Fields marked **[proposed]** are not in the backend plan yet. The UI builds
them, and they are raised with the backend team (see "Open questions").

Base URL: `VITE_API_BASE_URL` (default `/api`). In live dev mode the Vite dev
server proxies `/api` to the backend.

### 5.1 Auth
`POST /auth/login`, OAuth2 password flow, `application/x-www-form-urlencoded`:
```
username=trader1&password=demo
```
`200`:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 900,
  "user": { "username": "trader1", "role": "TRADER" }
}
```
`user` is **[proposed]** (otherwise the UI would decode the JWT). The response
also sets the refresh cookie: `httpOnly; Secure; SameSite=Strict`.
`401`: `{"detail": "Incorrect username or password"}`.

`POST /auth/refresh` (no body; sends the cookie, `credentials: "include"`):
`200` with the same body as login, or `401` when there is no valid session.

`POST /auth/logout`: `204`, clears the cookie.

Token rules in the browser:
- The access token is kept **in memory only** (never `localStorage`,
  `sessionStorage` or a readable cookie).
- On app start, call `/auth/refresh` once to restore the session.
- Refresh about 60 s before `expires_in` runs out, and once more on a `401`,
  then retry the request once. Concurrent 401s share **one** refresh call.
- If refresh fails, clear the session and go to `/login?next=…`.

### 5.2 News
`GET /news?date=2026-09-24&ticker=AAPL&q=earnings&include_duplicates=false`
(`ticker`, `q` and `include_duplicates` are optional; `q` and
`include_duplicates` are **[proposed]**):
```json
{
  "date": "2026-09-24",
  "run": {
    "run_id": 42,
    "status": "DONE",
    "started_at": "2026-09-24T09:30:02Z",
    "finished_at": "2026-09-24T09:30:05Z",
    "rows_received": 100,
    "dups": 9
  },
  "count": 91,
  "items": [
    {
      "id": 1234,
      "vendor_item_id": "acme-20260924-0007",
      "feed_date": "2026-09-24",
      "headline": "[SYNTHETIC] Apple expands buyback by $10 billion",
      "excerpt": "NEW YORK, September 24 (Acme Market Wire) -- Apple Inc said on...",
      "source_url": "https://acme-market-wire.example/2026/09/24/apple-buyback",
      "source_domain": "acme-market-wire.example",
      "published_at": "2026-09-24T08:12:00Z",
      "tickers": ["AAPL"],
      "synthetic": true,
      "is_dup": false,
      "dup_of": null
    }
  ]
}
```
- `run` is `null` when no ingest run exists for the date; `status` is
  `RUNNING | DONE | FAILED`. `run` is **[proposed]** on this endpoint.
- `excerpt` is **[proposed]**: at most 280 characters of the body, plain text.
- `count` is the number of items returned.

`GET /news/{id}`: the same item plus `"body": "..."` (plain text, may contain
newlines). `404`: `{"detail": "Not found"}`.

### 5.3 Health
`GET /health`: `200 {"status": "ok"}`.

### 5.4 Errors (FastAPI defaults)
- `401` `{"detail": "Not authenticated"}` with `WWW-Authenticate: Bearer`.
- `403` `{"detail": "Forbidden"}`, `404` `{"detail": "Not found"}`.
- `422` `{"detail": [{"loc": ["query", "date"], "msg": "...", "type": "..."}]}`.
- `5xx`: any body; the UI shows a generic error with a retry button.
- Network failure / timeout (15 s): the same generic error.

### 5.5 How the contract is kept honest
- **zod schemas are the single source of truth** in the UI: TypeScript types
  are inferred from them, and they convert snake_case to camelCase.
- Every response is parsed with its schema. A mismatch is a visible error
  ("Unexpected response from the server") plus a console error naming the
  endpoint and the failing path, so contract drift is caught on the first
  call to the real backend.
- Every mock fixture and every mock handler response is validated by the
  same schemas in tests.
- When the backend's OpenAPI exists, compare it with these schemas (see "Open
  questions").

## 6. Mock backend

### 6.1 Tool
**MSW (Mock Service Worker) v2.** The same handlers run in the browser (dev)
and in Node (Vitest), so the app code calls real URLs with `fetch` and has no
idea it's mocked. MSW is never included in the production build: it is
started from a dynamic import guarded by `VITE_API_MODE === "mock"`.

### 6.2 Data
- A **seeded, deterministic generator** (same date → same items, every run),
  shaped like the vendor feed:
  - About 100 items per trading date, 9 of them duplicates (exact copies, URL
    copies and stale copies of earlier days), `dup_of` pointing at the first
    copy.
  - Headlines start with `[SYNTHETIC]`, `synthetic: true`, and the body ends
    with "Generated by premarket-ai vendor-sim. Not real news."
  - Bodies start with a dateline: `NEW YORK, September 24 (Acme Market Wire) --`.
  - Real companies from a fixed list of ~20 large US companies; some items use
    invented companies and tickers. **Source domains are only `*.example` or
    `*.test`**, never a real outlet.
  - A few items carry awkward content on purpose: very long headlines,
    Unicode, HTML-looking text (`<script>`), and "ignore previous
    instructions" text. They test that the UI renders untrusted text safely.
  - Weekends have no run (`run: null`, no items).
- An in-memory "database" the handlers read from, with the seeded users and a
  session store that simulates the refresh cookie (MSW can't set real
  `httpOnly` cookies, so the mock keeps the session itself; the client code
  is the same in both modes).
- Access tokens from the mock expire after `VITE_MOCK_TOKEN_TTL_S` (default
  900) so the refresh path can be exercised quickly.

### 6.3 Scenarios
Selected with `?scenario=<name>` or the footer switcher (remembered in
`sessionStorage`, mock mode only):

| Scenario | Behavior |
|---|---|
| `default` | Normal day |
| `empty` | `run: null`, no items |
| `running` | `status: RUNNING`, items appear over successive polls |
| `failed` | `status: FAILED`, partial items |
| `slow` | 2–3 s latency on every call |
| `server-error` | `/news` returns `500` |
| `expired-session` | the next call returns `401`, then refresh works |
| `logged-out` | refresh returns `401` |
| `contract-drift` | `/news` returns a field with the wrong type, to show the schema error |

## 7. Tech stack
Pin **exact** versions in `package.json` (no `^`/`~`) with the current stable
release at scaffold time, and commit `package-lock.json`.

| Area | Choice |
|---|---|
| Runtime | Node 22 LTS, inside a container (no Node on the host) |
| Build | Vite, React, TypeScript (`strict`, `noUncheckedIndexedAccess`) |
| Routing | React Router (library mode) |
| Server state | TanStack Query |
| Validation | zod |
| UI | Tailwind CSS + shadcn/ui (Radix), lucide icons |
| Mocks | MSW v2 |
| Tests | Vitest, jsdom, Testing Library (+ user-event), vitest-axe |
| Style | gts (ESLint + Prettier, Google settings) plus React Hooks and jsx-a11y rules |

No global state library: server state is TanStack Query, filter state is the
URL, the session is a small React context.

## 8. Folder structure (`web`)
```
web/
├── index.html
├── package.json / package-lock.json
├── tsconfig.json (+ tsconfig.node.json)
├── vite.config.ts          # also Vitest config; /api proxy for live mode
├── eslint.config.js / .prettierrc.js   # from gts init, plus React rules
├── components.json         # shadcn/ui
├── .env.example            # VITE_API_MODE, VITE_API_BASE_URL, VITE_MOCK_TOKEN_TTL_S
├── public/mockServiceWorker.js         # generated by `msw init`
└── src/
    ├── main.tsx            # starts MSW in mock mode, then renders
    ├── app/                # app.tsx, router.tsx, providers.tsx, query-client.ts
    ├── api/
    │   ├── schemas/        # zod: auth.ts, news.ts, errors.ts (the contract)
    │   ├── client.ts       # fetch wrapper: base URL, token, refresh, errors, parsing
    │   ├── auth.ts         # login, refresh, logout
    │   └── news.ts         # getNews, getNewsItem
    ├── mocks/
    │   ├── browser.ts / node.ts
    │   ├── handlers/       # auth.ts, news.ts, health.ts
    │   ├── data/           # generator.ts, companies.ts, users.ts, db.ts
    │   └── scenarios.ts
    ├── features/
    │   ├── auth/           # session context, login page, route guards
    │   └── news/           # feed page, detail page, components/, hooks/
    ├── components/
    │   ├── layout/         # app shell, simulation ribbon, compliance banner
    │   └── ui/             # shadcn/ui components (generated)
    ├── lib/                # time.ts (ET formatting, trading dates), env.ts
    └── test/               # setup.ts, render helpers
```
Tests sit next to the code: `feed-page.test.tsx` beside `feed-page.tsx`.

## 9. Conventions
- **Style:** Google TypeScript Style Guide
  (`../docs/Google_TypeScript_Style_Guide_20260925.md`), enforced by gts. See
  the `google-ts-style` skill for the rules gts doesn't check.
- **Files:** kebab-case (`news-row.tsx`). Named exports only; the only default
  exports are config files whose tool requires one (`vite.config.ts`).
- **Components:** function components, props typed with an `interface`, no
  `React.FC`. One component per file unless a helper is private to it.
- **Data access:** components never call `fetch`. They use hooks in
  `features/*/hooks`, which use `api/`, which uses `client.ts`.
- **Time:** stored and sent in UTC, shown in America/New_York with `Intl`.
  "Today" means today in New York, not in the browser's zone.
- **Text:** plain, short, sentence case. No investment language anywhere
  (buy, sell, hold, target price, recommendation).

## 10. Security and compliance
- Vendor text is **untrusted**: render it as text only. No
  `dangerouslySetInnerHTML`, no Markdown rendering of vendor content.
- External links: `target="_blank" rel="noopener noreferrer nofollow"`, and
  only `http:`/`https:` URLs are rendered as links.
- Tokens: section 5.1. No secrets in the bundle; only `VITE_*` variables
  that are safe to be public.
- The SIMULATION ribbon and the compliance banner can't be hidden or removed
  by any setting.
- The `[SYNTHETIC]` headline prefix is shown as delivered, never stripped.

## 11. Accessibility and UX quality
- WCAG 2.2 AA: labelled inputs, visible focus, 4.5:1 contrast, no information
  by color alone, keyboard reachable everything, skip-to-content link.
- Every data view has loading (skeleton), empty, error (with retry) and
  success states.
- Works from 360 px wide to desktop; the feed becomes cards on narrow screens.
- Respects `prefers-color-scheme` (light and dark) and
  `prefers-reduced-motion`.

## 12. Testing
| Layer | What | Tool |
|---|---|---|
| Contract | every fixture and handler response passes its schema; snake → camel mapping | Vitest |
| Unit | time helpers (ET, trading dates, weekends), URL filter parsing, generator determinism | Vitest |
| API client | token attach, single-flight refresh on concurrent 401s, retry once, logout on failed refresh, schema errors | Vitest + MSW |
| Components/pages | login flow, feed states per scenario, filters in URL, duplicates toggle, detail 404, untrusted text rendered inert | Testing Library + MSW |
| Accessibility | axe on login, feed and detail | vitest-axe |

Coverage target: 80 % lines for `src/api`, `src/features` and `src/lib`.

## 13. Tasks (`make <task>`, all inside a Node 22 container)
The Makefile already has `lint` and `fix`. Add:

| Task | Runs |
|---|---|
| `install` | `npm ci` (node_modules in the named volume) |
| `dev` | Vite on port 5173 (`--host 0.0.0.0`), mock mode by default |
| `test` | `vitest run --coverage` |
| `typecheck` | `tsc --noEmit` |
| `build` | `tsc` + `vite build` (live mode, no MSW) |
| `check` | `lint`, `typecheck`, `test`, `build` |

`npm` commands are only ever run through these tasks, never on the host.

## 14. Milestones
| # | Milestone | Done when |
|---|---|---|
| M0 | Scaffold + tooling | `make check` passes on an empty app; gts, Tailwind, shadcn/ui, Vitest and MSW are wired |
| M1 | Contract + mocks | schemas, generator, handlers and scenarios exist; contract tests pass |
| M2 | Shell + auth | ribbon, banner, login/logout, refresh, guards, 403/404 |
| M3 | News Feed | filters in URL, all run states, duplicates toggle, keyboard nav |
| M4 | News detail | detail page, 404, back-with-filters |
| M5 | Hardening | a11y pass, every scenario checked by hand, coverage target met |

## 15. Definition of done (module)
- `make check` passes with zero lint warnings.
- Every scenario in 6.3 was opened in the browser and behaves as described.
- The production build contains no MSW code (checked in the build output).
- Switching `VITE_API_MODE=live` needs no code change.
- This file is up to date, including the decision log.

## 16. Open questions for the backend team
1. Add `user` to the login and refresh responses? (section 5.1)
2. Add `run`, `excerpt`, `q` and `include_duplicates` to `GET /news`? (5.2)
3. Publish the FastAPI OpenAPI document so the UI can check its zod schemas
   against it (or generate types from it) once the backend exists.

## 17. Decision log
| Date | Decision | Why |
|---|---|---|
| 2026-09-25 | Build against MSW mocks, contract in zod | UI work doesn't wait for the backend; drift is caught by schema parsing |
| 2026-09-25 | Wire format snake_case, UI model camelCase, mapped in schemas | FastAPI default on the wire, Google TS naming in code |
| 2026-09-25 | Duplicates hidden by default | Same content as the PDF traders know |
| 2026-09-25 | No paging in the feed | About 100 items per day |
