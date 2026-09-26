// gts (Google TypeScript style) plus the React Hooks and jsx-a11y rules.
// `npm run lint` runs ESLint with this config and --max-warnings=0.
import gts from 'gts';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import reactHooks from 'eslint-plugin-react-hooks';
import {defineConfig} from 'eslint/config';

// ESLint requires a default export from its config file.
export default defineConfig([
  {ignores: ['dist/', 'coverage/', 'public/mockServiceWorker.js']},
  ...gts,
  {
    // gts treats its config files as CommonJS; this package is ESM.
    files: ['eslint.config.js', '.prettierrc.js'],
    languageOptions: {sourceType: 'module'},
  },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      reactHooks.configs.flat.recommended,
      jsxA11y.flatConfigs.recommended,
    ],
    languageOptions: {
      parserOptions: {
        // gts points at ./tsconfig.json only; vite.config.ts lives in the
        // node project.
        project: ['./tsconfig.json', './tsconfig.node.json'],
        tsconfigRootDir: import.meta.dirname,
        ecmaFeatures: {jsx: true},
      },
    },
    rules: {
      // Style guide: handle the case instead of asserting non-null.
      '@typescript-eslint/no-non-null-assertion': 'error',
      '@typescript-eslint/consistent-type-imports': 'error',
      // `const {body, ...rest} = item` is the plain way to drop a field.
      '@typescript-eslint/no-unused-vars': [
        'error',
        {ignoreRestSiblings: true},
      ],
      'no-restricted-syntax': [
        'error',
        {
          selector: 'ExportDefaultDeclaration',
          message: 'Use named exports (Google TypeScript style).',
        },
        {
          selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
          message: 'Vendor text is untrusted: render it as text.',
        },
      ],
    },
  },
  {
    // Tool configs whose tool requires a default export.
    files: ['vite.config.ts', 'playwright.config.ts'],
    rules: {'no-restricted-syntax': 'off'},
  },
]);
