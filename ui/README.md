# premarket-ai web UI

The website that replaces the daily premarket news PDF: login, a filterable
news feed for a trading date and a news detail page.

The backend is built in parallel and isn't available yet. So the UI runs
against a **mock backend** in the browser (MSW, Mock Service Worker) that
serves the agreed JSON contract. Setting one environment variable,
`VITE_API_MODE=live`, switches to the real backend without a code change.

> Status: **milestone M0 (scaffold and tooling)**. The app is a placeholder
> page that proves the toolchain. Login, the feed and the detail page come in
> the next milestones.

## Contents
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Tasks](#tasks)
- [How to test](#how-to-test)
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
| `typecheck` | `tsc` for the app and for `vite.config.ts`. |
| `lint` | ESLint with the gts config (Google TypeScript style) plus React Hooks and jsx-a11y rules, **zero warnings allowed**. |
| `fix` | gts fix: reformats and autofixes what it can. |
| `build` | Production build into `web/dist` (always live mode), then fails if any MSW code is in `dist/`. |
| `check` | `lint`, `typecheck`, `test`, `build`, stopping at the first failure. |
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
3. `test`: `Test Files  4 passed`, and the coverage summary. This step
   fails if `src/api`, `src/features` or `src/lib` drop below 80 % line
   coverage.
4. `build`: `built in …ms` and no `MSW code found in dist/` line.

Run only the tests, or keep them running while you edit (watch mode needs
the WSL copy, see [Troubleshooting](#troubleshooting)):
```bash
make -C ui test
make -C ui test-watch
```
The HTML coverage report is written to `web/coverage/index.html`.

### 2. Manual check in the browser (M0)
```bash
make -C ui dev
```
Open http://localhost:5173 and check:

| Check | Expected |
|---|---|
| The page loads | Yellow "SIMULATION: synthetic vendor data" ribbon at the top, the heading "premarket-ai", the line "Decision support only, not investment advice." and "API mode: mock". |
| Mock backend started | DevTools console shows `[MSW] Mocking enabled.` |
| Keyboard only | Press Tab: the "Show toolchain" button gets a visible focus ring. Press Enter: the list appears and the button reads "Hide toolchain". |
| Dark mode | Switch the OS (or DevTools > Rendering > prefers-color-scheme) to dark: the page turns dark. |
| Narrow screen | DevTools device toolbar at 360 px wide: no horizontal scrollbar. |
| Live mode | Stop the server, run `make -C ui dev VITE_API_MODE=live`: the page shows "API mode: live" and the console has no MSW line. |
| Mock start failure | In a browser that blocks service workers, the page says "The mock backend didn't start" instead of staying blank. |

### 3. The production bundle has no mocks
`make -C ui build` does this for you: the live build drops the mock code, the
build deletes the copied `mockServiceWorker.js`, and the task fails if
`mockServiceWorker`, `setupWorker` or `[MSW]` appears anywhere in `dist/`.
To see it yourself:
```bash
make -C ui build && ls ui/web/dist/assets
```
There is a single `index-*.js` and no `browser-*.js` chunk.

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
    ├── tsconfig.node.json    # vite.config.ts
    ├── vite.config.ts        # Vite + Vitest config, /api proxy for live mode
    ├── eslint.config.js      # gts + React Hooks + jsx-a11y + project rules
    ├── .prettierrc.js        # gts Prettier settings
    ├── components.json       # shadcn/ui settings (Radix base)
    ├── public/
    │   └── mockServiceWorker.js   # generated by `msw init`, dev only
    └── src/
        ├── main.tsx          # starts MSW in mock mode, then renders
        ├── index.css         # Tailwind + shadcn/ui theme (light and dark)
        ├── env.d.ts          # types of the VITE_* variables
        ├── app/              # the app (M0: placeholder page)
        ├── components/ui/    # shadcn/ui components (generated)
        ├── lib/              # small shared helpers (cn for class names)
        ├── mocks/            # MSW: browser worker, Node server, handlers
        └── test/             # Vitest setup and test helpers (axe)
```
Tests sit next to the code they test: `app.test.tsx` beside `app.tsx`.
Later milestones add `src/api/` (contract schemas and API client) and
`src/features/` (auth and news).

## Tech stack
Versions are pinned exactly in `web/package.json`.

| Area | Choice |
|---|---|
| Runtime | Node 22 in a container |
| Build | Vite 8, React 19, TypeScript 6 (`strict`) |
| UI | Tailwind CSS 4, shadcn/ui (Radix), lucide icons |
| Mocks | MSW 2 (browser in dev, Node in tests) |
| Tests | Vitest 5, jsdom, Testing Library, user-event, jest-dom, vitest-axe |
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
