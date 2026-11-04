import { parseBackendHealth, unavailableHealth } from "../../../lib/health";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const base = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";
    const response = await fetch(`${base}/api/v1/health/ready`, {cache: "no-store", signal: AbortSignal.timeout(6000)});
    const data = await response.json();
    const health = parseBackendHealth(data, response.status);
    if (!health) throw new Error("Invalid upstream health response");
    return Response.json(health, {status: health.status === "ready" ? 200 : 503, headers: {"Cache-Control": "no-store"}});
  } catch {
    return Response.json(unavailableHealth, {status: 503, headers: {"Cache-Control": "no-store"}});
  }
}
