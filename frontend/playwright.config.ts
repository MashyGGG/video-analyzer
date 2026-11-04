import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  retries: 0,
  failOnFlakyTests: true,
  timeout: 30_000,
  expect: { timeout: 7_000 },
  outputDir: "../.artifacts/playwright/functional-results",
  reporter: [
    ["list"],
    ["html", { outputFolder: "../.artifacts/playwright/functional-report", open: "never" }],
    ["json", { outputFile: "../.artifacts/playwright/functional.json" }],
  ],
  use: {
    baseURL: "http://127.0.0.1:17800",
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    serviceWorkers: "block",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium-desktop", testMatch: "**/*.ui.spec.ts", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } },
    { name: "chromium-mobile", testMatch: "**/*.ui.spec.ts", use: { ...devices["Pixel 7"] } },
    { name: "next-proxy-contract", testMatch: "**/*.proxy.spec.ts", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: [
    {
      command: "node tests/support/backend-fixture.mjs",
      url: "http://127.0.0.1:17801/health/live",
      reuseExistingServer: false,
      timeout: 20_000,
    },
    {
      command: "node scripts/start-e2e.mjs",
      url: "http://127.0.0.1:17800/health/live",
      reuseExistingServer: false,
      env: { API_INTERNAL_URL: "http://127.0.0.1:17801", NEXT_TELEMETRY_DISABLED: "1" },
      timeout: 60_000,
    },
  ],
});
