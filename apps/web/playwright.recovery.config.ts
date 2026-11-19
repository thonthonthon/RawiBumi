import { defineConfig, devices } from "@playwright/test";

/** HTTP recovery tests intercept transport responses; no real engine is required. */
export default defineConfig({
  testDir: "tests/recovery", outputDir: "../../tmp/recovery-results", timeout: 30_000, reporter: "list",
  use: { baseURL: "http://127.0.0.1:5176", viewport: { width: 1440, height: 900 }, trace: "retain-on-failure",
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {} },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: { command: "npx vite --host 127.0.0.1 --port 5176 --strictPort", url: "http://127.0.0.1:5176", reuseExistingServer: false }
});
