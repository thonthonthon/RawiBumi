import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests/scale", outputDir: "../../tmp/scale-results", timeout: 120_000, workers: 1, reporter: "list",
  use: { baseURL: "http://127.0.0.1:5177", viewport: { width: 1440, height: 900 }, trace: "retain-on-failure",
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {} },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: { command: "npx vite --mode demo --host 127.0.0.1 --port 5177 --strictPort", url: "http://127.0.0.1:5177", reuseExistingServer: false }
});
