import { test, expect } from "@playwright/test";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";

const exec = promisify(execFile);
const root = path.resolve(__dirname, "../../..");
const api = "http://127.0.0.1:17811";
async function compose(...args: string[]) {
  await exec("docker", ["compose", "-p", "video-analyzer-e2e", ...args], { cwd: root, timeout: 40_000 });
}

test.beforeEach(async ({ page, request }) => {
  await expect.poll(async () => (await request.get(`${api}/api/v1/health/ready`)).status()).toBe(200);
  await page.clock.install({ time: new Date("2026-11-04T00:00:00Z") });
  await page.clock.pauseAt(new Date("2026-11-04T00:00:01Z"));
});

test("real browser -> Next -> FastAPI -> database/Redis, models remain unavailable", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "基础服务已就绪" })).toBeVisible();
  for (const name of ["本地 API", "数据库", "Redis"]) {
    await expect(page.locator(".service").filter({ has: page.getByRole("heading", { name, exact: true }) }).getByText("正常", { exact: true })).toBeVisible();
  }
  await expect(page.getByText("本地模型尚未配置，视频分析暂未开放。")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "基础服务已就绪" })).toBeVisible();
  expect(errors).toEqual([]);
  await testInfo.attach("real-infrastructure-desktop", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
});

for (const service of ["postgres", "redis", "api"] as const) {
  test(`actual ${service} outage appears in browser and recovers on polling`, async ({ page, request }, testInfo) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "基础服务已就绪" })).toBeVisible();
    try {
      await compose("stop", service);
      const proxy = await request.get("/api/health");
      expect(proxy.status()).toBe(503);
      const data = await proxy.json();
      expect(data.api_available).toBe(service !== "api");
      expect((await request.get("/health/live")).status()).toBe(200);
      await page.clock.runFor(15_000);
      await expect(page.getByRole("heading", { name: "部分服务暂不可用" })).toBeVisible();
      const card = page.locator(".service").filter({ has: page.getByRole("heading", { name: service === "postgres" ? "数据库" : service === "redis" ? "Redis" : "本地 API", exact: true }) });
      await expect(card.getByText("暂不可用", { exact: true })).toBeVisible();
      await testInfo.attach(`real-${service}-outage`, { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
    } finally {
      await compose("start", service);
      await expect.poll(async () => {
        try { return (await request.get(`${api}/api/v1/health/ready`)).status(); }
        catch { return 0; }
      }, { timeout: 30_000 }).toBe(200);
    }
    await page.clock.runFor(15_000);
    await expect(page.getByRole("heading", { name: "基础服务已就绪" })).toBeVisible();
  });
}
