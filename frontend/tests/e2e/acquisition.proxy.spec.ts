import { test, expect } from "@playwright/test";
const id = "11111111-1111-4111-8111-111111111111";
const job = { schema_version: "1.0.0", source_id: id, asset_id: id, job_id: id, platform: "douyin", state: "RESOLVED", attempts: 0, error: null, validation: {}, fallback: "upload" };
const origin = { Origin: "http://127.0.0.1:17800" };

test("acquisition proxy handles valid contract and scopes session", async ({ request }) => {
  await request.post("http://127.0.0.1:17801/__control", { data: { payload: { ...job, secret: "private-password", validation: { unknown: "private-password" } } } });
  const response = await request.post("/api/acquisition/assets/resolve", { headers: origin, data: { text: "https://v.douyin.com/abc", authorized: true } });
  expect(response.status()).toBe(200);
  expect(await response.json()).toEqual(job);
  expect(response.headers()["set-cookie"]).toContain("HttpOnly");
  expect(response.headers()["cache-control"]).toBe("no-store");
});
for (const [name, scenario] of [
  ["null", { payload: null }], ["false success", { payload: { ...job, state: "SUCCEEDED" } }],
  ["private error", { status: 500, raw: "private-password" }], ["disconnect", { disconnect: true }],
  ["timeout", { delay: 12_000, payload: job }],
  ["oversized body", { raw: "x".repeat(9000) }],
] as const) {
  test(`acquisition proxy rejects ${name}`, async ({ request }) => {
    await request.post("http://127.0.0.1:17801/__control", { data: scenario });
    const response = await request.get(`/api/acquisition/jobs/${id}`);
    expect(response.status()).toBe(503);
    expect((await response.json()).code).toBe("ACQUISITION_UNAVAILABLE");
    expect(await response.text()).not.toContain("private-password");
  });
}
test("acquisition proxy refuses cross-site, arbitrary route and size", async ({ request }) => {
  expect((await request.post("/api/acquisition/assets/resolve", { headers: { Origin: "https://evil.test" }, data: {} })).status()).toBe(403);
  expect((await request.get("/api/acquisition/http://169.254.169.254")).status()).toBe(404);
  expect((await request.post("/api/acquisition/assets/resolve", { headers: origin, data: "x".repeat(9000) })).status()).toBe(413);
});
