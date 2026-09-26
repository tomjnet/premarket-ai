import {defineConfig, devices} from '@playwright/test';

const PORT = 5174;

// Playwright requires a default export from its config file.
export default defineConfig({
  testDir: './e2e',
  // coverage/ is already gitignored.
  outputDir: './coverage/e2e/results',
  reporter: [
    ['list'],
    ['html', {outputFolder: './coverage/e2e/report', open: 'never'}],
  ],
  fullyParallel: true,
  retries: 0,
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: 'retain-on-failure',
  },
  projects: [{name: 'chromium', use: {...devices['Desktop Chrome']}}],
  // The app in mock mode with the default settings (as `make dev`).
  webServer: {
    command: `npx vite --port ${PORT} --strictPort`,
    port: PORT,
    env: {VITE_API_MODE: 'mock'},
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
