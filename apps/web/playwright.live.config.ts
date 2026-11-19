import { defineConfig, devices } from "@playwright/test";

// Live checks against the real engine API (not the demo engine). Start the API
// first, from the repository root:
//   uvicorn apps.api.server:app --host 127.0.0.1 --port 8000
// then run: npm run test:live
const PORT = 5175;

export default defineConfig({
  testDir: "tests/live",
  outputDir: "../../tmp/live-test-results",
  // Eight workers queue on one API: ordinary parallel max 58.9 s; simulation ~66 s (rounded).
  timeout: 90_000,
  expect: { timeout: 20_000 },
  retries: 0,
  reporter: "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
    // USE-D7 hides synthetic test components by default; the live specs use the UAT ones (approved 2026-11-09).
    storageState: { cookies: [], origins: [{ origin: `http://127.0.0.1:${PORT}`, localStorage: [{ name: "rawibumi.showTestComponents", value: "1" }] }] }
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: {
    command: `npx vite --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: false,
    timeout: 60_000
  }
});
