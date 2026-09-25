---
name: google-ts-style
description: Google TypeScript Style Guide rules for the web UI, what gts enforces and what review must catch, adapted for React. Use when writing or reviewing any .ts/.tsx file under ui/web, or when a lint error from gts needs fixing.
---

# Google TypeScript style for `web`

The full guide is `../docs/Google_TypeScript_Style_Guide_20260925.md` (generated,
don't edit). Search it when a rule here isn't enough. gts (`make lint`,
`make fix`) enforces formatting and many rules; the rest is on you.

## Checked by gts (just run it)
Formatting (Prettier: 2 spaces, single quotes, 80 columns, trailing commas),
`const`/`let` only, `===`, no unused variables, many `@typescript-eslint`
rules. Fix with `make fix`, then read the diff.

## Not checked by tooling: apply these yourself
**Modules and exports**
- Named exports only. No `export default`, except where a tool requires it
  (`vite.config.ts`, `eslint.config.js`). Say so in a one-line comment there.
- ES modules only. No `namespace`, no `require`.
- `import type {...}` for type-only imports.
- Import paths are relative inside a feature; `@/` alias for `src/`.

**Types**
- No `any`. Use `unknown` and narrow it (zod does this at the API boundary).
- No non-null assertions (`!`) to silence the compiler; handle the case.
- Prefer `interface` for object shapes (props included); `type` for unions,
  mapped types and `z.infer` results.
- Don't annotate what inference already makes obvious; do annotate exported
  function return types.
- Use `undefined` for "not set" in UI code; `null` only where the wire
  contract has it (converted at the schema layer where sensible).
- No enums: use string-literal unions (`'TRADER' | 'ANALYST' | 'ADMIN'`),
  derived from zod where possible.

**Naming**
- `UpperCamelCase`: components, types, interfaces, classes.
- `lowerCamelCase`: variables, functions, hooks (`useNewsFeed`), props.
- `CONSTANT_CASE`: module-level constants that are deeply immutable.
- No `I` prefix on interfaces, no `_` prefix/suffix, no Hungarian notation.
- Acronyms as words: `apiBaseUrl`, `newsId`, `HttpError`.
- Files: kebab-case (`news-row.tsx`).

**Functions and classes**
- Function declarations for named functions and components; arrow functions
  for callbacks.
- Classes only where they fit (error types). `private`/`readonly` modifiers,
  not `#private`.
- Error classes extend `Error` and set `name`.

**Comments**
- JSDoc (`/** ... */`) on every exported symbol that isn't obvious from its
  name and type. Say *why*, not *what*.
- No commented-out code. `// TODO(username): ...` only with an owner.

**Control flow**
- Always braces for `if`/`for`/`while`.
- `for...of` for arrays; no `for...in` on arrays.
- Throw only `Error` objects. Catch `unknown` and narrow it.

## React adaptations (project rules, not from the guide)
- Function components with a typed props `interface`; no `React.FC`.
- Hooks rules are enforced by `eslint-plugin-react-hooks`; don't disable them.
- `eslint-plugin-jsx-a11y` findings are real bugs; fix, don't suppress.
- An `eslint-disable` needs a comment on the same line saying why.
