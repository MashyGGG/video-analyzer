import { test as base, expect, type Page } from "@playwright/test";

export const healthy = { status: "ready", api_available: true, dependencies: { database: true, redis: true }, models: "not_configured" };
export const unavailable = { status: "unavailable", api_available: false, dependencies: { database: false, redis: false }, models: "not_configured" };

export function service(page: Page, name: string) {
  return page.locator(".service").filter({ has: page.getByRole("heading", { name, exact: true }) });
}

export async function assertUnavailable(page: Page) {
  await expect(page.getByRole("heading", { name: "部分服务暂不可用" })).toBeVisible();
  await expect(page.getByText("基础服务已就绪", { exact: true })).toHaveCount(0);
}

export const test = base.extend<{ browserGuard: void }>({
  browserGuard: [async ({ page }, use) => {
    const exceptions: string[] = [];
    const external: string[] = [];
    page.on("pageerror", error => exceptions.push(error.message));
    await page.route("**/*", async route => {
      const url = new URL(route.request().url());
      if (["http:", "https:"].includes(url.protocol) && url.origin !== "http://127.0.0.1:17800") {
        external.push(url.origin);
        await route.abort("blockedbyclient");
      } else { await route.continue(); }
    });
    await use();
    expect(exceptions, "No uncaught browser exceptions").toEqual([]);
    expect(external, "No external browser requests").toEqual([]);
  }, { auto: true }],
});
export { expect };
