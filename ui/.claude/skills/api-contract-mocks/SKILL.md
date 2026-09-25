---
name: api-contract-mocks
description: Add or change a backend endpoint, field or error in the web UI, contract-first. Use whenever the UI needs data it doesn't get yet, a response shape changes, a new mock scenario is needed, or a schema/contract error shows up. Covers zod schemas, the API client, MSW handlers, seeded fixtures and contract tests.
---

# Contract-first API changes (zod + MSW)

The backend isn't built yet. The UI and the backend agree on JSON through the
contract in `PLAN.md` section 5. In code, that contract is the zod schemas
in `web/src/api/schemas/`. Everything else follows from them.

## The order is fixed
1. **Plan.** Is the endpoint or field in `PLAN.md` section 5?
   - Yes: go on.
   - No: add it there first, marked **[proposed]**, with a JSON example, and
     add a line to "Open questions for the backend team". Only then write code.
2. **Schema** (`src/api/schemas/<area>.ts`):
   - Describe the **wire format** (snake_case) exactly: required vs optional
     vs nullable matter. `null` and a missing key are different things.
   - `.transform()` to the camelCase UI model in the same schema. Export the
     inferred types: `export type NewsItem = z.output<typeof newsItemSchema>`
     (UI model) and, if a handler needs it, the `z.input` wire type.
   - Enums are `z.enum([...])`. Dates and times are strings validated with a
     regex or `z.iso.datetime()` (zod 4), converted in the UI, never `Date`
     in the schema output.
3. **API function** (`src/api/<area>.ts`): calls `client.ts` with the path,
   query and schema. It returns the parsed UI model. No React here.
4. **Mock data** (`src/mocks/data/`): extend the seeded generator so the new
   field has realistic values, including edge cases (empty, very long,
   Unicode, `null` when the contract allows it). Same seed → same output.
5. **Handler** (`src/mocks/handlers/<area>.ts`): read from the in-memory db,
   honour query parameters exactly like the contract says, return the
   FastAPI-style errors (`{"detail": ...}`), and respect the active scenario.
6. **Tests**:
   - Contract: the handler's response for each scenario passes the schema.
   - Mapping: one wire example → the expected UI model.
   - Client: errors map to the right UI error type.
7. **UI**: only now use it in a hook and a component.

## Rules
- The client parses **every** response. A parse failure throws a
  `ContractError` with the endpoint and the zod issue path; the UI shows
  "Unexpected response from the server" and logs the details.
- Handlers use the same URL builder as the client (`VITE_API_BASE_URL`), so a
  path typo fails in tests, not in production.
- MSW can't set `httpOnly` cookies. The mock keeps the refresh session in its
  in-memory db; the client code must not know the difference.
- A new failure mode gets a scenario in `src/mocks/scenarios.ts` and a row in
  `PLAN.md` section 6.3.
- Never import from `src/mocks` in app code, except the one guarded dynamic
  import in `main.tsx`.

## Example: adding an optional field
Plan says `GET /news` items gain `"language": "en"` **[proposed]**, nullable.

```ts
// src/api/schemas/news.ts (gts formatting: single quotes, arrowParens avoid)
const newsItemWireSchema = z.object({
  // ...existing fields
  language: z.string().nullable().optional(),
});

export const newsItemSchema = newsItemWireSchema.transform(item => ({
  // ...existing mapping
  language: item.language ?? null,
}));
```
Then: generator sets `language` (mostly `"en"`, a few `null`), the handler
passes it through, a contract test checks both values, and only then a
component shows it.
