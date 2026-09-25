---
name: feature-slice
description: Build one page or feature of the web UI end to end (route, data hook, components, every UI state, tests, a11y). Use when starting any page or visible feature from PLAN.md, such as login, the news feed, filters or the news detail page.
---

# Building a feature slice

A slice is one user-visible capability, done completely: route, data,
components, all states, tests. Finish one slice before starting the next.

## 1. Read before you write
- The feature's section in `PLAN.md` (screens, behavior, contract).
- The endpoints it uses in section 5. If data is missing, stop and use the
  `api-contract-mocks` skill first.
- Write down, in your working notes, the list of **states** the feature can
  be in. At minimum: loading, empty, error (network / 5xx / contract),
  success; plus anything feature-specific (for example `RUNNING` and
  `FAILED` ingest runs, 404, 403, session expired).

## 2. Layout of a slice (`src/features/<feature>/`)
```
<feature>/
├── <name>-page.tsx          # route component: reads params, composes pieces
├── <name>-page.test.tsx
├── hooks/use-<thing>.ts     # TanStack Query hook: key, fetcher, options
├── components/<part>.tsx    # presentational, props in, JSX out
└── <helper>.ts              # pure logic (URL filters, grouping), unit tested
```
- **Pages** own routing and data. **Components** get data through props and
  don't fetch. Pure logic lives in plain functions, not in components.
- Query keys are arrays built by one function per feature
  (`newsKeys.list(filters)`), so invalidation is predictable.
- Filter and view state that a user might share goes in the URL
  (`useSearchParams`), parsed and validated by a pure function with defaults.

## 3. States, done properly
- Loading: skeletons shaped like the content, not a spinner in the middle.
- Empty: say why and what to do next ("No feed for Saturday, September 26.
  Go to Friday").
- Error: plain message, a Retry button (`refetch`), no stack traces. A
  `ContractError` says "Unexpected response from the server".
- Success: content. Background refetches don't flash the skeleton.

## 4. Accessibility and UX
- Semantic HTML first (`main`, `nav`, `h1`–`h3`, `ul`/`li`, `button` vs `a`).
- Every input has a visible label. Focus is visible and moves sensibly after
  navigation and after errors.
- Don't rely on color alone. Contrast 4.5:1. Test narrow (360 px) and wide.
- Keyboard shortcuts never fire while typing in an input.

## 5. Tests (Testing Library + MSW, next to the file)
- Test what the user sees and does: roles, labels and text, not class names
  or component internals.
- One test per state, driven by the mock scenarios (`server.use(...)` or the
  scenario helper), not by mocking hooks.
- The URL is part of the behavior: assert it after filtering.
- Add an axe check for each page.
- Untrusted text: a fixture with `<script>` / HTML in it renders as text.

## 6. Finish
- Run the `web-verify` skill.
- Update `PLAN.md` if behavior differs from the spec (and say why in the
  decision log).
