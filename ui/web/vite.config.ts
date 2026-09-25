import * as path from 'node:path';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import {defineConfig} from 'vitest/config';

// Where `make dev VITE_API_MODE=live` sends /api calls. The backend serves
// its routes at the root, so the /api prefix is stripped.
const apiProxyTarget = process.env.API_PROXY_TARGET ?? 'http://localhost:8000';

// Vite and Vitest require a default export from their config file.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {'@': path.resolve(import.meta.dirname, 'src')},
  },
  build: {
    rolldownOptions: {
      output: {
        // Libraries in their own chunk: an app release doesn't invalidate
        // the browser's cached copy of React, the router and friends.
        // Revisit when routes are lazy-loaded: this group would also pull
        // their libraries into the eager chunk.
        codeSplitting: {groups: [{name: 'vendor', test: /node_modules/}]},
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
        rewrite: url => url.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    // Tests run the app as `make dev` does: against the mock backend.
    env: {VITE_API_MODE: 'mock'},
    // Page tests render ~100 feed rows twice (StrictMode) in jsdom; 5 s
    // (the default) is too tight on a busy machine.
    testTimeout: 15_000,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/**/*.test.{ts,tsx}',
        'src/test/**',
        'src/components/ui/**',
        'src/main.tsx',
      ],
      reporter: ['text-summary', 'text', 'html'],
      thresholds: {
        'src/{api,features,lib}/**': {lines: 80},
      },
    },
  },
});
