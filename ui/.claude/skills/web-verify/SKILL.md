---
name: web-verify
description: Verify web UI work before calling it done - lint, typecheck, tests with coverage, production build, no MSW in the bundle, and a manual pass over the mock scenarios. Use at the end of every milestone or feature slice, and whenever asked whether the UI works.
---

# Verifying the web UI

"Done" means these steps ran and passed. Report each one with the command
and a short excerpt of its output. If something fails, say which step, show
the error, and fix it or explain why it can't be fixed now.

## 1. Automated checks (all in the Node container)
```bash
make check
```
It runs, in order: `lint` (gts, zero warnings), `typecheck` (`tsc
--noEmit`), `test` (Vitest with coverage), `build` (live mode). If `check`
doesn't exist yet (milestone M0), run the tasks that do and add `check`.

Coverage: at least 80 % lines for `src/api`, `src/features` and `src/lib`.

## 2. No mocks in production
After `build`, search the output for MSW:
```bash
grep -rl "mockServiceWorker\|msw" web/dist || echo "no MSW in dist"
```
`dist/` must not contain MSW code. (`public/mockServiceWorker.js` is copied
into `dist/` by Vite; delete it from the build output in the build task, or
exclude it, and note which you chose in `PLAN.md`.)

## 3. Manual pass in the browser (mock mode)
```bash
make dev
```
Open http://localhost:5173 and check each scenario from `PLAN.md` 6.3
(`?scenario=<name>`). For each one, say what you saw. At least:
- SIMULATION ribbon and the compliance banner on every page, both themes.
- `default`: log in as `trader1` / `demo`, filter by ticker, search, toggle
  duplicates, open an item, go back with filters kept.
- `empty`, `running`, `failed`, `server-error`: the matching state, no crash.
- `expired-session`: the request succeeds after one silent refresh.
- `logged-out`: back to the login page with a notice.
- `contract-drift`: "Unexpected response from the server".
- Keyboard only: log in, move through the feed, open and leave an item.
- Width 360 px: nothing overflows horizontally.

If you can't open a browser in your environment, say so and list which of
these you could only check through tests.

## 4. Spec in sync
- `PLAN.md` matches what was built; new decisions are in the decision log.
- Any **[proposed]** contract change is listed under "Open questions".
