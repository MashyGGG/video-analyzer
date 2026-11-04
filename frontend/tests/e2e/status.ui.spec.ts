import { test, expect, healthy, unavailable, service, assertUnavailable } from "../support/fixtures";

test("loading never claims healthy before first response", async ({ page }) => {
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/health", async route => { await held; await route.fulfill({ json: healthy }); });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "正在连接本地服务" })).toBeVisible();
  await expect(page.getByText("基础服务已就绪", { exact: true })).toHaveCount(0);
  release();
  await expect(page.getByRole("heading", { name: "基础服务已就绪" })).toBeVisible();
});

test("healthy dashboard, navigation, refresh and responsive layout", async ({ page }, testInfo) => {
  await page.route("**/api/health", route => route.fulfill({ json: healthy }));
  await page.goto("/");
  await expect(page).toHaveTitle("Video Analyzer · 本地工作台");
  await expect(page.getByRole("heading", { name: "基础服务已就绪" })).toBeVisible();
  for (const name of ["本地 API", "数据库", "Redis"]) await expect(service(page, name).getByText("正常", { exact: true })).toBeVisible();
  await expect(page.getByText("本地模型尚未配置，视频分析暂未开放。")).toBeVisible();
  await expect(page.getByRole("button", { name: /上传|分析/ })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole("link", { name: "◧ Video Analyzer" }).click();
  await expect(page).toHaveURL("/");
  await page.reload();
  await expect(page.getByRole("heading", { name: "基础服务已就绪" })).toBeVisible();
  await testInfo.attach("healthy-dashboard", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
});

for (const dependency of ["database", "redis"] as const) {
  test(`${dependency} failure keeps reachable API accurate`, async ({ page }) => {
    await page.route("**/api/health", route => route.fulfill({ status: 503, json: { ...healthy, status: "unavailable", dependencies: { ...healthy.dependencies, [dependency]: false } } }));
    await page.goto("/");
    await assertUnavailable(page);
    await expect(service(page, "本地 API").getByText("正常", { exact: true })).toBeVisible();
    await expect(service(page, dependency === "database" ? "数据库" : "Redis").getByText("暂不可用", { exact: true })).toBeVisible();
  });
}

for (const [label, payload, status] of [
  ["null", null, 200],
  ["missing fields", { status: "ready" }, 200],
  ["wrong boolean", { ...healthy, dependencies: { database: "true", redis: true } }, 200],
  ["contradictory dependencies", { ...healthy, dependencies: { database: false, redis: true } }, 200],
  ["unknown state", { ...healthy, status: "surprise" }, 200],
  ["HTTP error disguised as ready", healthy, 500],
  ["API down disguised as ready", { ...healthy, api_available: false }, 200],
] as const) {
  test(`invalid health response: ${label}`, async ({ page }) => {
    await page.route("**/api/health", route => route.fulfill({ status, json: payload }));
    await page.goto("/");
    await assertUnavailable(page);
    for (const name of ["本地 API", "数据库", "Redis"]) await expect(service(page, name).getByText("暂不可用", { exact: true })).toBeVisible();
  });
}

for (const mode of ["network", "invalid JSON"] as const) {
  test(`${mode} failure does not crash or expose response body`, async ({ page }) => {
    await page.route("**/api/health", route => mode === "network" ? route.abort("failed") : route.fulfill({ body: "<html>private-upstream-error</html>" }));
    await page.goto("/");
    await assertUnavailable(page);
    await expect(page.getByText("private-upstream-error")).toHaveCount(0);
  });
}

test("polls after 15 seconds and recovers without reload", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-11-04T00:00:00Z") });
  await page.clock.pauseAt(new Date("2026-11-04T00:00:01Z"));
  let calls = 0;
  await page.route("**/api/health", route => route.fulfill({ status: ++calls === 1 ? 503 : 200, json: calls === 1 ? unavailable : healthy }));
  await page.goto("/");
  await assertUnavailable(page);
  await page.clock.runFor(14_000);
  expect(calls).toBe(1);
  await page.clock.runFor(1_000);
  await expect(page.getByRole("heading", { name: "基础服务已就绪" })).toBeVisible();
  expect(calls).toBe(2);
});

test("hung request times out, late response cannot restore stale green, next poll recovers", async ({ page }) => {
  await page.clock.install({ time: new Date("2026-11-04T00:00:00Z") });
  await page.clock.pauseAt(new Date("2026-11-04T00:00:01Z"));
  let calls = 0;
  let late!: () => void;
  const held = new Promise<void>(resolve => { late = resolve; });
  await page.route("**/api/health", async route => {
    calls++;
    if (calls === 1) { await held; await route.fulfill({ json: healthy }).catch(() => {}); }
    else await route.fulfill({ json: healthy });
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "正在连接本地服务" })).toBeVisible();
  await page.clock.runFor(8_100);
  await assertUnavailable(page);
  late();
  await expect(page.getByRole("heading", { name: "部分服务暂不可用" })).toBeVisible();
  await page.clock.runFor(7_000);
  await expect(page.getByRole("heading", { name: "基础服务已就绪" })).toBeVisible();
  expect(calls).toBe(2);
});
