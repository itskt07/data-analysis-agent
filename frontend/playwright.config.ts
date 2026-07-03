import { defineConfig, devices } from '@playwright/test'

/**
 * E2E config for the Data Analysis Agent frontend.
 *
 * The static export is served same-origin by FastAPI at /app/. The suite runs
 * against the real running app on port 8001 (launched by the orchestrator via
 * `uv run python -m src`). Override with PLAYWRIGHT_BASE_URL if needed.
 */
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:8001'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  use: {
    baseURL,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
