import { cookies } from "next/headers";
import { randomBytes } from "node:crypto";
import { parseJob } from "../../../../lib/acquisition";

export const dynamic = "force-dynamic";
const max = 200 * 1024 * 1024;
const failure = (code: string, status: number) => Response.json({ code, message: "采集未完成，请上传获授权的 MP4/MOV。", retryable: false, details: { fallback: "upload" } }, { status, headers: { "Cache-Control": "no-store" } });

async function proxy(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const path = (await context.params).path.join("/");
  const id = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
  if (!(request.method === "POST" && (/^assets\/(upload|resolve)$/.test(path) || new RegExp(`^assets/${id}/acquire$`).test(path))) && !(request.method === "GET" && new RegExp(`^jobs/${id}$`).test(path))) return failure("NOT_FOUND", 404);
  if (request.method === "POST") {
    let permitted = false;
    try {
      const origin = new URL(request.headers.get("origin") ?? "");
      permitted = origin.host === request.headers.get("host") && ["http:", "https:"].includes(origin.protocol) &&
        (["127.0.0.1", "localhost"].includes(origin.hostname) || origin.origin === process.env.PUBLIC_ORIGIN);
    } catch { /* Missing/malformed Origin is denied. */ }
    if (!permitted) return failure("SOURCE_ACCESS_DENIED", 403);
  }
  const length = Number(request.headers.get("content-length"));
  if (request.method === "POST" && path !== `assets/${path.split("/")[1]}/acquire` && (!Number.isSafeInteger(length) || length <= 0 || length > (path === "assets/upload" ? max : 8192))) return failure("MEDIA_TOO_LARGE", 413);
  const jar = await cookies();
  let owner = jar.get("va_session")?.value;
  if (!owner || !/^[a-f0-9]{64}$/.test(owner)) {
    owner = randomBytes(32).toString("hex");
    jar.set("va_session", owner, { httpOnly: true, sameSite: "strict", secure: new URL(request.url).protocol === "https:", path: "/" });
  }
  try {
    const headers: Record<string, string> = { "X-Owner": owner, "Content-Type": path === "assets/upload" ? "application/octet-stream" : "application/json" };
    if (request.method === "POST") headers["Content-Length"] = String(length);
    if (request.headers.get("x-authorized") === "true") headers["X-Authorized"] = "true";
    let received = 0;
    const body = request.method === "POST" && length > 0 ? request.body?.pipeThrough(new TransformStream({ transform(chunk, controller) { received += chunk.byteLength; if (received > length || received > max) throw new Error("limit"); controller.enqueue(chunk); } })) : undefined;
    const response = await fetch(`${process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000"}/api/v1/${path.startsWith("jobs/") ? "acquisition/" : ""}${path}`, { method: request.method, headers, body, duplex: "half", cache: "no-store", signal: AbortSignal.timeout(path === "assets/upload" ? 190_000 : 8000) } as RequestInit);
    const reader = response.body?.getReader();
    if (!reader) throw new Error("contract");
    const chunks: Uint8Array[] = [];
    let size = 0;
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      size += chunk.value.byteLength;
      if (size > 8192) { await reader.cancel(); throw new Error("contract"); }
      chunks.push(chunk.value);
    }
    const raw = Buffer.concat(chunks).toString("utf8");
    const data = JSON.parse(raw);
    if (response.ok) {
      const job = parseJob(data);
      if (!job) throw new Error("contract");
      return Response.json(job, { status: response.status, headers: { "Cache-Control": "no-store" } });
    }
    const code = typeof data?.code === "string" && /^[A-Z_]{2,40}$/.test(data.code) ? data.code : "ACQUISITION_UNAVAILABLE";
    return failure(code, [400, 401, 404, 413, 422, 503].includes(response.status) ? response.status : 503);
  } catch { return failure("ACQUISITION_UNAVAILABLE", 503); }
}
export { proxy as GET, proxy as POST };
