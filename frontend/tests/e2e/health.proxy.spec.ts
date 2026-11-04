import { test, expect } from "@playwright/test";

const ready = { status: "ready", code: "OK", dependencies: { database: true, redis: true }, models: "not_configured" };
const down = { status: "unavailable", api_available: false, dependencies: { database: false, redis: false }, models: "not_configured" };

test("proxy forwards real-shaped upstream ready and live is independent", async ({ request }) => {
  await request.post("http://127.0.0.1:17801/__control", { data: { status: 200, database: true, redis: true } });
  const response = await request.get("/api/health");
  expect(response.status()).toBe(200);
  expect(await response.json()).toEqual({ status: "ready", api_available: true, dependencies: ready.dependencies, models: "not_configured" });
  expect((await request.get("/health/live")).status()).toBe(200);
});

test("proxy preserves valid 503 with API reachable", async ({ request }) => {
  await request.post("http://127.0.0.1:17801/__control", { data: { status: 503, database: false, redis: true } });
  const response = await request.get("/api/health");
  expect(response.status()).toBe(503);
  expect(await response.json()).toEqual({ ...down, api_available: true, dependencies: { database: false, redis: true } });
});

for (const [name, scenario] of [
  ["null", { payload: null }],
  ["malformed JSON", { raw: "private-parser-details" }],
  ["unknown status", { payload: { ...ready, status: "surprise" } }],
  ["missing contract fields", { payload: { status: "ready", dependencies: ready.dependencies } }],
  ["contradictory ready", { payload: { ...ready, dependencies: { database: false, redis: true } } }],
  ["HTTP 500 with ready body", { status: 500, payload: ready }],
  ["HTTP 200 with unavailable body", { status: 200, payload: { ...ready, status: "unavailable", code: "DEPENDENCY_UNAVAILABLE" } }],
  ["wrong boolean", { payload: { ...ready, dependencies: { database: "true", redis: true } } }],
  ["connection reset", { disconnect: true }],
  ["upstream timeout", { delay: 10_000, payload: ready }],
] as const) {
  test(`proxy rejects ${name} without exposing upstream data`, async ({ request }) => {
    await request.post("http://127.0.0.1:17801/__control", { data: scenario });
    const before = Date.now();
    const response = await request.get("/api/health");
    expect(response.status()).toBe(503);
    expect(await response.json()).toEqual(down);
    expect(Date.now() - before).toBeLessThan(9_000);
  });
}
