# premarket-ai web (`ui/`)

You are working on the front end only: `web` (React + Vite + TypeScript)
and `Makefile`. `PLAN.md` is the spec. Read it before any work, follow
it, and update it (including its "Decision log") when a decision changes.

Claude Code is started in `ui/`, so every path in these files is relative to
`ui/` (`PLAN.md`, `web/src/...`, `make <task>`). The repo's shared docs are
one level up (`../docs/`).

## Boundaries
- Change files only under `ui/`. The backend, containers, compose files, CI
  and the repo root belong to other people. If the UI needs something from
  them, add it to "Open questions" in `PLAN.md`.
- The backend doesn't exist yet. The UI talks to the **MSW mock backend**,
  which serves the contract in `PLAN.md` section 5. Never invent an
  endpoint or field the plan doesn't list; propose it in the plan first.

## Environment
- There is **no Node on the host**. Run everything through `make <task>`
  (a Node 22 container, `ENGINE ?= podman`). Never run `npm`/`npx` directly
  and never suggest installing Node on the host.
- Add a Makefile task when a new command is needed, in the style of the
  existing `lint`/`fix` tasks.

## Non-negotiables
- **Contract first:** a change to what the UI sends or receives starts in the
  zod schemas (`src/api/schemas`), then fixtures and handlers, then the UI.
  Use the `api-contract-mocks` skill.
- **Untrusted vendor text:** render as text. Never `dangerouslySetInnerHTML`.
- **Tokens:** access token in memory only; refresh via the `httpOnly` cookie.
  Never `localStorage`/`sessionStorage` for tokens.
- **Compliance:** the SIMULATION ribbon and the "Decision support only, not
  investment advice" banner are always visible. No investment language (buy,
  sell, hold, price target, recommendation) anywhere in the UI.
- **No MSW in production builds.** Mocks load only when
  `VITE_API_MODE === "mock"`.
- **Style:** Google TypeScript Style Guide, enforced by gts. Use the
  `google-ts-style` skill.

## How to work
- Build one milestone of `PLAN.md` section 14 at a time, and use the
  `feature-slice` skill for each page or feature.
- Before calling any work done, use the `web-verify` skill and report what
  you ran and what it printed. If a check fails, say so; don't hide it.
- After a milestone, ask the `ui-reviewer` subagent for a review and fix what
  it finds (or explain why not).
- Prefer small, boring, readable code. No abstractions for features that
  aren't in this increment.
