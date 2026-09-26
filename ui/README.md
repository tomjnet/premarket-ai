# premarket-ai web UI

The website that replaces the daily premarket news PDF: login, a filterable
news feed for a trading date and a news detail page.

The backend is built in parallel and isn't available yet. So the UI runs
against a **mock backend** in the browser (MSW, Mock Service Worker) that
serves the agreed JSON contract. Setting one environment variable,
`VITE_API_MODE=live`, switches to the real backend without a code change.

> Status: **increment 1 web UI complete (milestones M0–M5)**. Log in, read
> a trading date's news (filters in the URL, duplicates, running or failed
> runs, keyboard navigation), open an item in full with its source link, and
> go back to the feed with the filters kept. Every mock scenario is covered
> by unit tests and by browser tests in Chromium, and the
> [definition of done](#definition-of-done) is met.

## Contents
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Tasks](#tasks)
- [How to test](#how-to-test)
- [Definition of done](#definition-of-done)
- [Mock backend](#mock-backend)
- [Configuration](#configuration)
- [Project structure](#project-structure)
- [Tech stack](#tech-stack)
- [Coding standard](#coding-standard)
- [Troubleshooting](#troubleshooting)

## Prerequisites
- Ubuntu WSL with **Podman** and **make**. That's all.
- **No Node on the host.** Every npm, Vite and Vitest command runs in a
  `node:22-bookworm-slim` container through `make`. `node_modules` lives in
  the Podman volume `premarket-ai-web-node-modules`, not in the checkout.
- A desktop browser (Chrome, Edge or Firefox) for the dev server.

All commands below run from the repo root in WSL. From inside `ui/`, drop the
`-C ui`.

## Quick start
```bash
make -C ui install   # first time only: npm ci into the node_modules volume
make -C ui dev       # dev server with the mock backend
```
Open http://localhost:5173. Stop the server with Ctrl+C.

```bash
make -C ui check     # everything CI would run: lint, typecheck, test, build
```

## Tasks
Run `make -C ui help` for the list.

| Task | What it does |
|---|---|
| `install` | `npm ci` into the node_modules volume. Other tasks also install automatically when `package-lock.json` changed. |
| `dev` | Vite dev server on port 5173 (`--host 0.0.0.0`), mock mode by default. |
| `test` | Vitest (unit, component and contract tests) with coverage. |
| `test-watch` | Vitest in watch mode: re-runs tests on every save. Needs a terminal. |
| `typecheck` | `tsc` for the app, and for the Vite and Playwright configs and `e2e/`. |
| `lint` | ESLint with the gts config (Google TypeScript style) plus React Hooks and jsx-a11y rules, **zero warnings allowed**. |
| `fix` | gts fix: reformats and autofixes what it can. |
| `build` | Production build into `web/dist` (always live mode), then fails if any MSW code is in `dist/`. |
| `check` | `lint`, `typecheck`, `test`, `build`, stopping at the first failure. |
| `e2e` | Browser tests: Playwright drives Chromium against the dev server in mock mode (every scenario, axe with contrast, keyboard, 360 px). First run pulls a ~2.5 GB image. |
| `verify` | `check` and then `e2e`: the full definition of done. |
| `npm` | Any npm command in the container, for example `make -C ui npm ARGS="install zod"`. |
| `clean` | Removes `web/dist`, `web/coverage` and the node_modules volume. |

Variables you can override on the command line: `ENGINE` (default `podman`),
`PORT` (default `5173`), `VITE_API_MODE`, `VITE_API_BASE_URL`,
`VITE_MOCK_TOKEN_TTL_S`, `API_PROXY_TARGET`.

## How to test

### 1. Automated checks
```bash
make -C ui check
```
Pass criteria, in order:
1. `lint`: no output from ESLint (0 errors, 0 warnings).
2. `typecheck`: no output from `tsc`.
3. `test`: `Test Files  23 passed`, `Tests  200 passed`, and the coverage
   summary. This step fails if `src/api`, `src/features` or `src/lib` drop
   below 80 % line coverage.
4. `build`: `built in …ms` and no `MSW code found in dist/` line.

What the tests cover (component tests render the real app in React
StrictMode against the mock backend, as `make dev` does):

| Test file | Proves |
|---|---|
| `src/features/news/news-detail-page.test.tsx` | The item in full (headline with `[SYNTHETIC]`, exact ET and UTC times, body, vendor id, feed date); safe source link (`_blank`, `noopener noreferrer nofollow`, real host as text, "opens a different site" when the vendor domain differs); no link for `javascript:`; HTML-looking text stays text; duplicate info; ticker links; back link keeps the feed's filters and focus lands on the page; opened directly it goes to the item's date; 404 and malformed id (no request); server-error with Retry; contract-drift; slow; running (not arrived → 404); axe. |
| `src/features/news/detail.test.ts`, `src/lib/url.test.ts` | Id parsing, back-link target (router state re-parsed), body paragraphs, which URLs may become links. |
| `src/features/news/feed-page.test.tsx` | Today's feed newest first with "91 items · 9 duplicates hidden · updated 05:30 ET"; duplicates shown and marked; ticker chips (toggle) and Back; search 300 ms after the last key, Back undoes it, typing during a search keeps every key; ticker with Enter and an invalid-ticker message; a typed date makes one history entry; shared links fill the inputs; no matches; weekend, future date; every scenario (empty, running with real 30 s polling that stops at DONE, failed, server-error with Retry, contract-drift, expired-session, slow); `<script>` in vendor text stays text; `/`, `j`, `k`, Enter, and turning the shortcuts off; axe. |
| `src/features/news/feed.test.ts`, `hooks/hooks.test.ts` | URL filter parsing and round-trip, ticker rules, sorting, summary text, the "Go to" date, poll interval, row navigation, typing detection. |
| `src/features/auth/login-page.test.tsx` | Login with Enter goes back to `?next=`; `?next=` can't leave the site; wrong password: message, password cleared and focused; empty fields send nothing; the button is disabled while sending and a second Enter sends nothing; unreachable server message; a logged-in user skips the form; focus lands on the page after login; no axe issues. |
| `src/app/routes.test.tsx` | No session → login with `?next=`; a reload restores the session; notices, date, user and backend status in the shell (axe); backend unreachable; MOCK API tag and scenario switcher; logout (also when the request fails); expiry and a failed proactive refresh → login with "Your session expired"; the token is refreshed before it expires; backend down at start → Try again; 404, 403 and crash pages. |
| `src/features/auth/session.test.ts` | Refresh timing (no loop for short tokens); `?next=` safety; the tab's had-session flag. |
| `src/api/client.test.ts` | Bearer token sent; one shared refresh for concurrent `401`s (and no second refresh if another call already refreshed); exactly one retry with the new token; a failed refresh ends the session once; a refresh finishing after logout is dropped; network errors don't log you out; caller cancel is an `AbortError`; `HttpError`, `NetworkError` (offline and 15 s timeout) and `ContractError`. |
| `src/api/schemas/schemas.test.ts` | The contract example maps snake_case → camelCase; wrong types, unknown statuses, a count mismatch and time offsets are rejected. |
| `src/mocks/handlers/handlers.test.ts` | Every mock endpoint and every scenario returns what the contract says (raw `fetch`, checked against the schemas). |
| `src/mocks/data/generator.test.ts` | Same date → same items; 100 items with 9 duplicates on weekdays, none on weekends; duplicates point at real first copies; reserved domains only; the awkward items exist. |
| `src/lib/*.test.ts`, `src/app/query-client.test.ts` | Settings parsing, New York dates and times (DST included), scenario URLs, retry rules, error messages. |

Run only the tests, or keep them running while you edit (watch mode needs
the WSL copy, see [Troubleshooting](#troubleshooting)):
```bash
make -C ui test
make -C ui test-watch
```
The HTML coverage report is written to `web/coverage/index.html`.

### 2. Browser tests (real Chromium)
```bash
make -C ui e2e
```
Playwright starts the dev server in mock mode inside its container and runs
`web/e2e/app.spec.ts` in Chromium, with the page clock pinned to Friday
2026-09-25 09:00 ET (time then runs normally). Expected: `18 passed`. They check:
- the MSW service worker starts (`[MSW] Mocking enabled.`);
- every scenario (`default`, `empty`, `running`, `failed`, `slow`,
  `server-error`, `expired-session`, `logged-out`, `contract-drift`) and the
  footer switcher. `running` grows from 25 to 50 items after 30 s of page
  time; `expired-session` shows the real `401` → one refresh → `200` on the
  network; `slow` has no list after 1 s;
- axe, WCAG 2.2 A/AA **with colour contrast**, in light and dark mode, on
  login, feed, detail, 404 and the red error states (wrong password, failed
  run, server error);
- a keyboard-only walkthrough (Tab order from the skip link, login, `/` to
  search, `j`, Enter, back with the search kept);
- no horizontal scrolling at 360 px (with the 200+ character headline);
- vendor `<script>`/`<img onerror>` text stays inert (no dialog, no element).

On a failure, open the report `ui/web/coverage/e2e/report/index.html`, or the
trace printed in the output.

### 3. Manual check in the browser
```bash
make -C ui dev
```
Open http://localhost:5173 and go through these steps in order:

| # | Do | Expected |
|---|---|---|
| 1 | Open http://localhost:5173/news | You land on `/login?next=%2Fnews`. Yellow SIMULATION ribbon and the "Decision support only, not investment advice." banner at the top; the mock users hint under the form; footer: "Backend: ok", a MOCK API tag and the scenario switcher. DevTools console: `[MSW] Mocking enabled.` |
| 2 | Press Enter with empty fields | "Enter your username and password." Nothing is sent (Network tab). |
| 3 | Log in as `trader1` / `wrong` | "Wrong username or password.", the password is cleared and focused. |
| 4 | Log in as `trader1` / `demo` (keyboard only: Tab, type, Enter) | You are on `/news` with the header: "premarket-ai", "Today in New York: <date>", "Signed in as trader1", a TRADER badge and Log out. |
| 5 | Reload the page (F5) | You stay logged in ("Restoring your session…" flashes first). |
| 6 | Open http://localhost:5173/no-such-page | "Page not found" with a link back to the feed. |
| 7 | Click Log out | Back on the login page, no "session expired" notice. |
| 8 | Log in again, then in the footer pick `logged-out` and click **Apply (reloads)** | The reload can't restore the session: login page with "Your session expired. Please log in again." Pick `default` + Apply to go back. |
| 9 | Keyboard: reload, press Tab once | "Skip to main content" appears top left; Enter jumps into the page. |
| 10 | Dark mode (OS setting, or DevTools > Rendering > prefers-color-scheme) | The page turns dark; ribbon and banner stay readable. |
| 11 | DevTools device toolbar at 360 px wide | Nothing overflows horizontally; the header wraps. |
| 12 | Short tokens: `make -C ui dev VITE_MOCK_TOKEN_TTL_S=60`, log in, wait | Network tab: `POST /api/auth/refresh` about every 30 s; you stay logged in. |
| 13 | Live mode: `make -C ui dev VITE_API_MODE=live` (no backend running) | No mock hint or MOCK API tag; "Backend: unreachable"; logging in says "The server had a problem. Try again." |

Then the news feed (logged in as `trader1`, mock mode, scenario `default`):

| # | Do | Expected |
|---|---|---|
| 14 | Open http://localhost:5173/ | "News feed", today's date, "91 items · 9 duplicates hidden · updated 05:30 ET" (on a weekend: "No feed for …" with a link to Friday). Each row: time `HH:MM ET`, ticker buttons, headline link, source domain, excerpt. |
| 15 | Click a ticker button in a row | The URL gets `ticker=…`, only that ticker's items remain, the button looks pressed. Click it again: the filter is removed. Browser Back also undoes it. |
| 16 | Type `Zentrality` in the search box | About 300 ms after you stop typing, the URL gets `q=Zentrality` and "N matching items" (a few). Back removes the search. |
| 17 | Look for the item with `<script>` in the headline (search `Umbrix`) | The text `<script>alert("headline")</script>` is shown literally; no alert pops up. |
| 18 | Tick **Show duplicates** | 100 items; 9 rows have a dashed border and "Duplicate of VND-…". |
| 19 | Pick a date in the Date field (for example yesterday) | That date's feed; the URL has `date=…`. Pick a Saturday: "No feed for …" and "Go to Friday …". |
| 20 | Keyboard: press `/`, type, Esc, then click the page title and press `j`, `j`, `k`, Enter | `/` focuses search; `j`/`k` move a focus ring between headlines; Enter opens the item. "Turn off single-key shortcuts" disables them (remembered). |
| 21 | Footer: `running` + Apply | "Today's feed is still arriving", 25 items received; every 30 s 25 more arrive; after 90 s the normal summary. |
| 22 | Footer: `failed`, `empty`, `server-error`, `contract-drift`, `slow` + Apply (one at a time) | failed: red "The ingest run for this date failed" panel and the 40 items that arrived. empty: "No ingest run exists for this date yet." server-error: "The server had a problem. Try again." with Retry. contract-drift: "Unexpected response from the server." slow: skeleton rows for 2–3 s, then the list. Finish with `default` + Apply. |
| 23 | Copy the URL with filters into a new tab | The same view: date, ticker, search and duplicates restored from the URL. |

Then the detail page:

| # | Do | Expected |
|---|---|---|
| 24 | In the feed, search `Zentrality`, then click a headline | The item in full: headline (with `[SYNTHETIC]`), "Published <date>, HH:MM ET (YYYY-MM-DD HH:MM UTC)", ticker buttons, "Source: <domain> · <host>" link, the body in paragraphs ending "Generated by premarket-ai vendor-sim. Not real news.", then feed date, vendor item id, duplicate and synthetic lines. |
| 25 | Click the source link | It opens in a new tab (the `.example` site doesn't exist, so the tab shows an error: expected). |
| 26 | Click **Back to the feed** | The feed with `Zentrality` still in the search box and the same results. Browser Back works too. |
| 27 | Keyboard: in the feed press `j` then Enter; on the detail page press Tab | Enter opens the item; Tab starts from the top of the item (focus was moved to the page). |
| 28 | Search `Umbrix Robotics reports` and open it | The headline shows `<script>alert("headline")</script>` and the body shows `<img src=x onerror=…>` as text; nothing runs. |
| 29 | Search `Kalvimo` and open "opens new packaging plant" | "Source: pennyrocket.example (link not shown: not a web address)": the vendor sent a `javascript:` URL. |
| 30 | Search `halted` and open the Borealiq item | "Source: reuters-news.test (the link opens a different site) · pennyrocket.example". |
| 31 | Show duplicates, open a row marked "Duplicate of …" | "Duplicate: Yes, duplicate of VND-…". |
| 32 | Open http://localhost:5173/news/999 and http://localhost:5173/news/abc | "This item doesn't exist" with Back to the feed. |
| 33 | Open an item, then switch the footer scenario to `server-error` (Apply) | "Couldn't load this item", "The server had a problem. Try again." and a Retry button. Pick `default` + Apply: the page reloads and the item shows. |

You can also call the mock API directly from the DevTools console (F12 >
Console). Chrome may ask you to type `allow pasting` first. Paste:
```js
const auth = await fetch('/api/auth/login', {
  method: 'POST',
  body: new URLSearchParams({username: 'trader1', password: 'demo'}),
}).then(r => r.json());
const news = await fetch('/api/news?date=2026-09-24', {
  headers: {Authorization: `Bearer ${auth.access_token}`},
}).then(r => r.json());
console.log(auth.user, news.run.status, news.count, news.items[0].headline);
```
Expected: `{username: 'trader1', role: 'TRADER'} 'DONE' 91 '[SYNTHETIC] …'`.
The Network tab shows the calls as handled by the service worker.

To check a scenario, open the page with `?scenario=<name>` (for example
http://localhost:5173/?scenario=failed), paste the snippet again and compare
with the [scenario table](#scenarios). The choice is remembered for the tab;
open `?scenario=default` to go back.

### 4. The production bundle has no mocks
`make -C ui build` does this for you: the live build drops the mock code, the
build deletes the copied `mockServiceWorker.js`, and the task fails if
`mockServiceWorker`, `setupWorker` or `[MSW]` appears anywhere in `dist/`.
To see it yourself:
```bash
make -C ui build && ls ui/web/dist/assets
```
There is a single `index-*.js` and no `browser-*.js` chunk.

## Definition of done
```bash
make -C ui verify
```

| Requirement | How it is checked |
|---|---|
| `check` passes with zero lint warnings | `make -C ui check` (lint uses `--max-warnings=0`) |
| Coverage: 80 % lines in `src/api`, `src/features`, `src/lib` | enforced by `make -C ui test` (currently about 98 %) |
| Every mock scenario works in the browser | `make -C ui e2e` (all 9 scenarios in Chromium), plus the manual steps above |
| No mock code in the production build | `make -C ui build` fails if MSW is in `dist/` |
| Switching to the real backend needs no code change | `make -C ui dev VITE_API_MODE=live` (step 13) |
| Accessible (WCAG 2.2 AA) | axe with contrast in light and dark (`e2e`), vitest-axe on login, shell, feed, detail, "item doesn't exist", 403 and the mock-start page, keyboard walkthrough, 360 px |

## Mock backend
In mock mode, MSW answers every API call inside the browser (and inside
Vitest). The app code calls the real URLs with `fetch` and doesn't know it's
mocked.

**Users** (password `demo` for all): `trader1` (TRADER), `analyst1`
(ANALYST), `admin1` (ADMIN).

**Endpoints:** `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`,
`GET /news?date=&ticker=&q=&include_duplicates=`, `GET /news/{id}`,
`GET /health`, all under `/api`. Errors look like FastAPI's
(`{"detail": ...}`).

**Data:** a seeded generator, so the same date always gives the same items.
Each weekday has 100 items, 9 of them duplicates (exact copies, same-URL
copies and stale copies of the previous trading day). Weekends and future
dates have no feed. Every headline starts with `[SYNTHETIC]`, and every
source is a reserved `.example` or `.test` domain. Some items are awkward on
purpose (a 200+ character headline, Unicode, `<script>` text, "Ignore
previous instructions", a `javascript:` source URL, a source that claims one
outlet but links to another, an item without tickers),
to prove the UI renders untrusted text safely.

**Session:** browsers can't let the mock set a real `httpOnly` refresh
cookie, so the mock keeps the session itself: only the username, in the
tab's `sessionStorage`, so it survives a reload like a cookie would. The
app's access token is never stored. Access tokens expire after
`VITE_MOCK_TOKEN_TTL_S`.

### Scenarios
Pick one with `?scenario=<name>` in the page URL.

| Scenario | What happens |
|---|---|
| `default` | Normal day |
| `empty` | No ingest run: `run: null`, no items |
| `running` | Run still `RUNNING`: 25 more items (oldest first) every 30 s; after 90 s the whole day is `DONE` |
| `failed` | Run `FAILED` with the first 40 items |
| `slow` | Every call takes 2–3 s |
| `server-error` | `/news` and `/news/{id}` answer `500` |
| `expired-session` | The current access token is revoked: the next authenticated call answers `401`, one silent refresh gets a new token, then everything works |
| `logged-out` | Refresh answers `401`; logging in again still works |
| `contract-drift` | `/news` sends `count` and `/news/{id}` sends `id` as a string, so the UI must say "Unexpected response from the server" |

## Configuration
The settings are `VITE_*` variables (see `web/.env.example`). They end up in
the public bundle, so never put a secret in one. `make dev` always passes
them to Vite, so they win over any `.env` file: set them on the `make`
command line.

| Variable | Default | Meaning |
|---|---|---|
| `VITE_API_MODE` | `mock` in `make dev` | `mock`: MSW answers every API call in the browser. `live`: real HTTP calls. A production build is always live, whatever this says. |
| `VITE_API_BASE_URL` | `/api` | Base URL of the backend. |
| `VITE_MOCK_TOKEN_TTL_S` | `900` | Mock mode only: access-token lifetime in seconds. Set it low (for example `60`) to exercise the session refresh. |
| `API_PROXY_TARGET` | `http://host.containers.internal:8000` | Live dev mode only: where the Vite dev server forwards `/api/*`, with the `/api` prefix removed. |

Examples:
```bash
make -C ui dev VITE_API_MODE=live
make -C ui dev VITE_API_MODE=live API_PROXY_TARGET=http://host.containers.internal:9000
make -C ui dev PORT=5174
```

## Project structure
```
ui/
├── Makefile                  # task runner: every command runs in a Node 22 container
├── README.md                 # this file
└── web/                      # the React app
    ├── index.html
    ├── package.json          # exact versions, no ^ or ~ (.npmrc save-exact)
    ├── package-lock.json     # committed
    ├── .npmrc                # save-exact=true
    ├── .env.example          # VITE_* settings, documented
    ├── tsconfig.json         # app: strict, noUncheckedIndexedAccess, @/ alias
    ├── tsconfig.node.json    # vite.config.ts, playwright.config.ts, e2e/
    ├── vite.config.ts        # Vite + Vitest config, /api proxy for live mode
    ├── playwright.config.ts  # browser tests: Chromium against the dev server (mock mode)
    ├── e2e/                  # browser tests: app.spec.ts, helpers.ts
    ├── eslint.config.js      # gts + React Hooks + jsx-a11y + project rules
    ├── .prettierrc.js        # gts Prettier settings
    ├── components.json       # shadcn/ui settings (Radix base)
    ├── public/
    │   └── mockServiceWorker.js   # generated by `msw init`, dev only
    └── src/
        ├── main.tsx          # starts MSW in mock mode, then renders
        ├── index.css         # Tailwind + shadcn/ui theme (light and dark)
        ├── env.d.ts          # types of the VITE_* variables
        ├── app/              # app, routes, providers, query client, mock-start page
        ├── api/              # the backend contract
        │   ├── schemas/      #   zod schemas: the wire format and the UI types
        │   ├── client.ts     #   fetch wrapper: token, refresh, timeout, parsing
        │   ├── errors.ts     #   HttpError, NetworkError, ContractError, SessionExpiredError
        │   └── auth.ts, news.ts, health.ts   # one function per endpoint
        ├── components/
        │   ├── layout/       #   root layout, app shell, header, footer, notices, PageMain
        │   ├── pages/        #   403, 404 and crash pages
        │   ├── load-error.tsx #  shared "Couldn't load …" panel with Retry
        │   └── ui/           #   shadcn/ui components (generated)
        ├── features/
        │   ├── auth/         #   session context, login page, route guards
        │   └── news/         #   feed and detail pages, their components, hooks and pure logic
        ├── lib/              # env.ts, time.ts, url.ts, storage.ts, mock-scenarios.ts, utils.ts
        ├── mocks/            # the mock backend (never in the production build)
        │   ├── data/         #   seeded generator, companies, users, in-memory db
        │   ├── handlers/     #   MSW handlers per endpoint
        │   ├── scenarios.ts  #   the scenarios above
        │   └── browser.ts, page-setup.ts, node.ts
        └── test/             # Vitest setup, renderApp helper, axe check
```
Tests sit next to the code they test: `client.test.ts` beside `client.ts`.
Pure logic (`feed.ts`, `detail.ts`) is tested without React.

## Tech stack
Versions are pinned exactly in `web/package.json`.

| Area | Choice |
|---|---|
| Runtime | Node 22 in a container |
| Build | Vite 8, React 19, TypeScript 6 (`strict`) |
| Routing, server state | React Router 8 (library mode), TanStack Query 5 |
| Validation | zod 4 |
| UI | Tailwind CSS 4, shadcn/ui (Radix), lucide icons |
| Mocks | MSW 2 (browser in dev, Node in tests) |
| Tests | Vitest 5, jsdom, Testing Library, user-event, jest-dom, vitest-axe; Playwright 1.63 + axe-core for browser tests |
| Style | gts 7 (ESLint + Prettier, Google settings), React Hooks, jsx-a11y |

Add a shadcn/ui component:
```bash
make -C ui npm ARGS="exec -- shadcn add dialog"
make -C ui fix
```

## Coding standard
Google TypeScript Style Guide
(`docs/Google_TypeScript_Style_Guide_20260925.md` in the repo), enforced by
gts. On top of what gts checks:
- Named exports only (config files that need a default export say why).
- No `any`, no non-null assertions (`!`).
- Vendor text is untrusted: rendered as text, never as HTML
  (`dangerouslySetInnerHTML` is a lint error).
- Files are kebab-case: `news-row.tsx`.

## Troubleshooting
| Problem | Fix |
|---|---|
| Page says "The mock backend didn't start" | The browser refused to register the service worker. Use Chrome, Edge or Firefox on `http://localhost:5173` (not a private window with service workers blocked, and not an embedded/IDE preview browser). Or run in live mode. |
| Edits don't show up in the dev server or `test-watch` | File watching doesn't cross from Windows drives (`/mnt/c`, `/mnt/d`) into the container. Run from the WSL copy (`~/src/premarket-ai`), or restart the task. |
| `port 5173 already in use` | Another dev server is still running: `podman ps`, then `podman stop <id>`. Or use `make -C ui dev PORT=5174`. |
| Strange dependency errors | Reset the node_modules volume: `make -C ui clean && make -C ui install`. |
| `make -C ui dev` can't reach the backend in live mode | Check `API_PROXY_TARGET`. From inside the container the host is `host.containers.internal`, not `localhost`. |
| `make -C ui e2e` is slow the first time | It pulls `mcr.microsoft.com/playwright:v1.63.0-noble` (~2.5 GB) once. |
| An e2e test fails | Open `ui/web/coverage/e2e/report/index.html` in a browser: it shows the failing step, a screenshot and the trace. |
| The e2e report is gone | `make -C ui test` cleans `web/coverage/` (unit coverage lives there too). Run `make -C ui e2e` again. |
| `make -C ui e2e` says "Dependencies changed: run make -C ui install first" | The browser image doesn't install packages itself: run `make -C ui install` (or use `make -C ui verify`, which runs `check` first). |
