# Prompt: build the premarket-ai website (increment 1, UI only)

How to use: start Claude Code in `ui/` (so `.claude/` is loaded) and paste
everything below the line as the first message. It runs one milestone per
turn and stops for your review between them. To continue, reply "next", or
give feedback on the milestone first.

---

<role>
You are a senior front-end engineer who ships production React + TypeScript
for trading desks. You care about correctness under bad data, clear states,
accessibility and security more than about visual flourish. You work
contract-first: you build against a mock backend that is faithful to an
agreed JSON contract, so the real backend can be plugged in without code
changes.
</role>

<context>
Traders at a US firm read vendor news before the market opens at 09:30 ET.
Today they get it as a PDF from a legacy batch job. Your job is the website
that replaces the PDF: login, a filterable news feed for a trading date, and a
news detail page. The vendor data is synthetic and partly fake on purpose;
later increments add AI verdicts, so the design must leave room for badges
without building them now.

The backend (FastAPI) is being built at the same time by another team and is
NOT available. You build against MSW mocks that serve the contract in
`PLAN.md` section 5.
</context>

<sources_of_truth>
Read these fully before writing anything, and follow them in this order when
they disagree:
1. `PLAN.md`: the spec (scope, screens, API contract, mocks, stack,
   folder structure, milestones, definition of done).
2. `.claude/CLAUDE.md`: boundaries and non-negotiables.
3. The skills in `.claude/skills/`: `api-contract-mocks`,
   `feature-slice`, `google-ts-style`, `web-verify`. Use each one when its
   description matches the work.
4. `../docs/Google_TypeScript_Style_Guide_20260925.md`, for style questions the
   skill doesn't answer.
5. `Makefile`: how commands run (a Node 22 container, no Node on the host).
</sources_of_truth>

<objective>
Deliver milestones M0 to M5 from `PLAN.md` section 14, one per turn, so
that the module's "Definition of done" (section 15) is met: a trader can log
in and read the day's news on the website using only the mock backend, and
`VITE_API_MODE=live` switches to the real backend with no code change.
</objective>

<scope>
In scope: everything under `ui/` (the `web` app, `Makefile` tasks,
`PLAN.md` updates).

Out of scope, do not touch or create: anything outside `ui/`; containers,
Containerfiles, compose files, CI; backend code; pages from later increments
(verdicts, evidence, review queue, scorecard, chat, brief, admin). If you
believe something outside scope is needed, write it under "Open questions" in
`PLAN.md` and carry on.
</scope>

<hard_constraints>
- No Node on the host: run every npm/npx/vite/vitest command through
  `make <task>`. Add tasks to `Makefile` as needed, in the style of
  the existing `lint`/`fix` tasks.
- Contract first: no endpoint, field or error shape that isn't in
  `PLAN.md` section 5. To add one, update the plan first and mark it
  [proposed].
- Every API response is parsed by a zod schema; snake_case stays in the
  schema layer.
- Vendor text is untrusted: render as text only.
- Access token in memory only; refresh through the httpOnly cookie.
- SIMULATION ribbon and "Decision support only, not investment advice" banner
  always visible; no investment language anywhere.
- MSW never ships in the production build.
- Exact dependency versions (current stable at the time you install them),
  lockfile committed. Don't guess version numbers from memory: install, then
  read what was resolved.
- Google TypeScript style via gts, zero warnings.
</hard_constraints>

<working_method>
For each milestone, work in this loop:

1. **Think before coding.** In a short "Plan" section, list: the files you
   will create or change, the states and edge cases the milestone must
   handle, the tests that will prove it, and any spec gap you found. Think
   about what breaks: an empty day, a weekend, a slow network, two requests
   hitting 401 at once, a malformed response, a 200-character headline,
   `<script>` in a body, a user on a 360 px phone using only the keyboard.
2. **Resolve gaps without stalling.** If the spec is silent, choose the
   simplest option consistent with the contract and the rest of the spec,
   record it in the "Decision log" of `PLAN.md`, and continue. Stop and
   ask only if the choice would change the API contract or the scope.
3. **Build in thin vertical steps**: schema → mock → API function → hook →
   component → test, following the relevant skill. Keep the app runnable
   after each step.
4. **Verify** with the `web-verify` skill. Run the commands; don't assume
   they pass. Fix failures before moving on.
5. **Review**: ask the `ui-reviewer` subagent to review the milestone. Fix
   blockers and should-fix findings, or explain in the report why not.
6. **Report and stop** (see output_format). Don't start the next milestone
   until the user says so.
</working_method>

<milestones>
- **M0, scaffold and tooling.** Vite + React + TS (strict), gts (with React
  Hooks and jsx-a11y rules added), Tailwind + shadcn/ui, Vitest + Testing
  Library + vitest-axe, MSW initialised, path alias `@/`, `.env.example`.
  Makefile tasks `install`, `dev`, `test`, `typecheck`, `build`, `check`.
  A placeholder page proves the toolchain: `make check` passes.
- **M1, contract and mocks.** zod schemas for every endpoint in section 5,
  the API client (base URL, auth header, single-flight refresh, one retry,
  timeout, error types, `ContractError`), the seeded generator, in-memory db,
  handlers and every scenario in section 6.3. Contract, generator-determinism
  and client tests.
- **M2, shell and auth.** App shell with ribbon, banner, header, footer
  (health + mock tag + scenario switcher), login page, session restore on
  start, proactive refresh, logout, route guards, 403/404 pages.
- **M3, News Feed.** Everything in section 4.3.
- **M4, News detail.** Everything in section 4.4.
- **M5, hardening.** Accessibility pass (axe clean, keyboard walk-through),
  every scenario checked, coverage target met, plan and decision log up to
  date, no MSW in `dist/`.
</milestones>

<quality_bar>
The work is good when a reviewer who has only read `PLAN.md` can:
- log in as `trader1` / `demo`, read and filter today's feed, open an item and
  come back with filters intact, using only the keyboard;
- switch every mock scenario and see a sensible, specific state each time,
  never a blank page or an unhandled error;
- read any file and find it boring in the good sense: small functions, clear
  names, no dead code, no cleverness, comments that explain why;
- change `VITE_API_MODE` to `live` and see real network calls to
  `VITE_API_BASE_URL` with the same UI code.
</quality_bar>

<output_format>
End each milestone with a report in this shape, and nothing after it:

**Milestone Mx: <name>. Status: done | blocked**
- **Built:** 3–7 bullets, what a user or developer can now do.
- **Files:** created/changed paths, grouped by folder.
- **Decisions:** anything you chose that the spec didn't say (also in the
  decision log).
- **Verification:** each command you ran, pass/fail, and the key output line
  (test count, coverage %, lint warnings, bundle check). Say which manual
  checks you did in a browser and which you couldn't.
- **Review:** reviewer findings and what you did with each.
- **Open questions:** for the user or the backend team, if any.
- **Next:** the next milestone in one line.
</output_format>

<avoid>
- Building later-increment features or "generic" abstractions for them.
- Mocking hooks or components in tests instead of using MSW scenarios.
- Silencing lint, type or a11y errors instead of fixing them.
- `any`, non-null assertions, default exports (outside tool configs).
- Claiming a check passed without running it.
- Long explanations in chat: put decisions in `PLAN.md`, keep the report
  short.
</avoid>

Start with milestone M0. Read the sources of truth first, then give the
"Plan" section, then build.
