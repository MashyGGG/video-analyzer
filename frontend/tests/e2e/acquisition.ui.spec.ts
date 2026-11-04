import { test, expect } from "../support/fixtures";

const id = "11111111-1111-4111-8111-111111111111";
const pending = { schema_version: "1.0.0", source_id: id, asset_id: id, job_id: id, platform: "file_upload", state: "PENDING", attempts: 0, error: null, validation: {}, fallback: "upload" };
const success = { ...pending, state: "SUCCEEDED", validation: { sha256: "a".repeat(64), bytes: 42 } };

test("authorized upload, polling, persistence and responsive form", async ({ page }, testInfo) => {
  await page.route("**/api/acquisition/assets/upload", async route => {
    expect(route.request().headers()["x-authorized"]).toBe("true");
    expect(route.request().postDataBuffer()?.toString()).toBe("synthetic-fixture");
    await route.fulfill({ status: 202, json: pending });
  });
  await page.route("**/api/acquisition/jobs/*", route => route.fulfill({ json: success }));
  await page.goto("/import");
  await page.getByLabel("选择视频").setInputFiles({ name: "synthetic.mp4", mimeType: "video/mp4", buffer: Buffer.from("synthetic-fixture") });
  await expect(page.getByRole("button", { name: "上传视频" })).toBeDisabled();
  await page.getByLabel("我确认有权处理此视频").check();
  await expect(page.getByRole("button", { name: "上传视频" })).toHaveCSS("background-color", "rgb(198, 243, 152)");
  await page.getByRole("button", { name: "上传视频" }).click();
  await expect(page.getByText("视频已校验并保存在本机。")).toBeVisible();
  await page.reload();
  await expect(page.getByText("视频已校验并保存在本机。")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await testInfo.attach("acquisition-form", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
});

for (const code of ["SOURCE_AUTH_REQUIRED", "SOURCE_EXPIRED", "SOURCE_RATE_LIMITED", "SOURCE_TIMEOUT", "MEDIA_INVALID", "MEDIA_TOO_LARGE"]) {
  test(`link task ${code} provides upload fallback`, async ({ page }) => {
    await page.route("**/api/acquisition/assets/resolve", route => route.fulfill({ json: { ...pending, state: "RESOLVED", platform: "douyin" } }));
    await page.route("**/api/acquisition/assets/*/acquire", route => route.fulfill({ status: 202, json: pending }));
    await page.route("**/api/acquisition/jobs/*", route => route.fulfill({ json: { ...pending, state: "FAILED_PERMANENT", error: { code } } }));
    await page.goto("/import");
    await page.getByLabel("我确认有权处理此视频").check();
    await page.getByLabel("分享文本").fill("授权分享 https://v.douyin.com/abc/");
    await page.getByRole("button", { name: "提交链接" }).click();
    await expect(page.getByRole("alert", { name: "采集错误" })).toContainText(code);
    await expect(page.getByRole("alert", { name: "采集错误" })).toHaveCSS("color", "rgb(255, 180, 171)");
    await expect(page.getByRole("alert", { name: "采集错误" })).toContainText("请上传");
    await expect(page.getByLabel("选择视频")).toBeVisible();
  });
}

for (const mode of ["network", "invalid contract", "upload rejected"] as const) {
  test(`${mode} fails safely without private body`, async ({ page }) => {
    await page.route("**/api/acquisition/assets/upload", route => mode === "network" ? route.abort() : route.fulfill({ status: mode === "upload rejected" ? 400 : 200, json: mode === "upload rejected" ? { code: "MEDIA_INVALID", message: "private-secret" } : { state: "SUCCEEDED", private: "private-secret" } }));
    await page.goto("/import");
    await page.getByLabel("我确认有权处理此视频").check();
    await page.getByLabel("选择视频").setInputFiles({ name: "bad.mov", mimeType: "video/quicktime", buffer: Buffer.from("bad") });
    await page.getByRole("button", { name: "上传视频" }).click();
    await expect(page.getByRole("alert", { name: "采集错误" })).toContainText("上传");
    await expect(page.getByText("视频已校验并保存在本机。")).toHaveCount(0);
    await expect(page.getByText("private-secret")).toHaveCount(0);
  });
}

test("poll timeout recovers and ignores late response", async ({ page }) => {
  await page.clock.install();
  await page.clock.pauseAt(new Date());
  await page.route("**/api/acquisition/assets/upload", route => route.fulfill({ status: 202, json: pending }));
  let calls = 0;
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/acquisition/jobs/*", async route => {
    if (++calls === 1) { await held; await route.fulfill({ json: success }); }
    else await route.fulfill({ json: success });
  });
  await page.goto("/import");
  await page.getByLabel("我确认有权处理此视频").check();
  await page.getByLabel("选择视频").setInputFiles({ name: "s.mp4", mimeType: "video/mp4", buffer: Buffer.from("x") });
  await page.getByRole("button", { name: "上传视频" }).click();
  await expect(page.getByText("任务状态：PENDING")).toBeVisible();
  await page.clock.runFor(1);
  await expect.poll(() => calls).toBe(1);
  await page.clock.runFor(10_001);
  await expect(page.getByRole("alert", { name: "采集错误" })).toContainText("状态查询失败");
  release();
  await expect(page.getByText("视频已校验并保存在本机。")).toHaveCount(0);
  await page.clock.runFor(2001);
  await expect(page.getByText("视频已校验并保存在本机。")).toBeVisible();
});
