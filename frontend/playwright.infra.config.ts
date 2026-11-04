import { defineConfig, devices } from "@playwright/test";

if (process.env.VA_E2E_INFRA !== "1") {
  throw new Error("Use python scripts/verify_a01_e2e.py: this suite stops services in the isolated video-analyzer-e2e project.");
}

export default defineConfig({
  testDir: "./tests/infra",
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  retries: 0,
  failOnFlakyTests: true,
  timeout: 90_000,
  expect: { timeout: 12_000 },
  outputDir: "../.artifacts/playwright/infra-results",
  reporter: [
    ["list"],
    ["html", { outputFolder: "../.artifacts/playwright/infra-report", open: "never" }],
    ["json", { outputFile: "../.artifacts/playwright/infra.json" }],
  ],
  use: {
    baseURL: "http://127.0.0.1:17810",
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    serviceWorkers: "block",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "real-compose-chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } }],
});
