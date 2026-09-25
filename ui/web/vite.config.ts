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
