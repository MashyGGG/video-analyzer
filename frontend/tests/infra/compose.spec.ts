import { test, expect } from "@playwright/test";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";

const exec = promisify(execFile);
const root = path.resolve(__dirname, "../../..");
const api = "http://127.0.0.1:17811";
async function compose(...args: string[]) {
  return await exec("docker", ["compose", "-p", "video-analyzer-e2e", ...args], { cwd: root, timeout: 40_000 });
}

test.beforeEach(async ({ page, request }) => {
  await expect.poll(async () => (await request.get(`${api}/api/v1/health/ready`)).status()).toBe(200);
  await page.clock.install({ time: new Date("2026-11-04T00:00:00Z") });
  await page.clock.pauseAt(new Date("2026-11-04T00:00:01Z"));
});

test("published port override reaches the frontend listening on 3100", async ({ request }) => {
  const { stdout } = await compose("port", "frontend", "3100");
  expect(stdout.trim()).toBe("127.0.0.1:17810");
  expect((await request.get("/health/live")).status()).toBe(200);
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

test("real browser upload validates generated media and persists after reload", async ({ page }) => {
  const { stdout } = await exec("docker", ["compose", "-p", "video-analyzer-e2e", "exec", "-T", "worker-media", "python", "-c", "import subprocess,base64,pathlib; p='/tmp/browser-a02.mp4'; subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=green:s=64x64:r=5','-t','1','-c:v','mpeg4',p],check=True); print(base64.b64encode(pathlib.Path(p).read_bytes()).decode()); pathlib.Path(p).unlink()"], { cwd: root, timeout: 30_000 });
  await page.goto("/import");
  await page.getByLabel("我确认有权处理此视频").check();
  await page.getByLabel("选择视频").setInputFiles({ name: "generated.mp4", mimeType: "video/mp4", buffer: Buffer.from(stdout.trim(), "base64") });
  await page.getByRole("button", { name: "上传视频" }).click();
  await expect.poll(async () => { await page.clock.runFor(2001); return await page.getByText("视频已校验并保存在本机。").count(); }, { timeout: 30_000 }).toBe(1);
  await page.reload();
  await page.clock.runFor(1);
  await expect(page.getByText("视频已校验并保存在本机。")).toBeVisible();
});

test("real browser fake media fails with upload fallback", async ({ page }) => {
  await page.goto("/import");
  await page.getByLabel("我确认有权处理此视频").check();
  await page.getByLabel("选择视频").setInputFiles({ name: "fake.mp4", mimeType: "video/mp4", buffer: Buffer.from("<html>fake</html>") });
  await page.getByRole("button", { name: "上传视频" }).click();
  await expect.poll(async () => { await page.clock.runFor(2001); return await page.getByRole("alert", { name: "采集错误" }).count(); }, { timeout: 30_000 }).toBe(1);
  await expect(page.getByRole("alert", { name: "采集错误" })).toContainText("MEDIA_INVALID");
  await expect(page.getByRole("alert", { name: "采集错误" })).toContainText("请上传");
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
