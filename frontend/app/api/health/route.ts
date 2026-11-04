export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const base = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";
    const response = await fetch(`${base}/api/v1/health/ready`, {cache: "no-store", signal: AbortSignal.timeout(6000)});
    const data = await response.json();
    if (typeof data.dependencies?.database !== "boolean" || typeof data.dependencies?.redis !== "boolean" || typeof data.status !== "string") throw new Error("Invalid health response");
    return Response.json({status: data.status, api_available: true, dependencies: data.dependencies, models: "not_configured"}, {status: response.ok ? 200 : 503});
  } catch {
    return Response.json({status: "unavailable", api_available: false, dependencies: {database: false, redis: false}, models: "not_configured"}, {status: 503});
  }
}
