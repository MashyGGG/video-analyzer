// Deliberate HTTP fixtures for Next proxy tests. Never imported by application code.
import http from "node:http";

let scenario = { status: 200, database: true, redis: true };
const server = http.createServer(async (request, response) => {
  if (request.url === "/health/live") {
    response.writeHead(200).end("fixture-only");
    return;
  }
  if (request.method === "POST" && request.url === "/__control") {
    let body = "";
    for await (const chunk of request) {
      body += chunk;
      if (body.length > 4096) { response.writeHead(413).end(); return; }
    }
    try { scenario = JSON.parse(body); response.writeHead(204).end(); }
    catch { response.writeHead(400).end(); }
    return;
  }
  if (request.url !== "/api/v1/health/ready") { response.writeHead(404).end(); return; }
  const current = { ...scenario };
  if (current.disconnect) { request.socket.destroy(); return; }
  if (current.delay) await new Promise(resolve => setTimeout(resolve, current.delay));
  if (response.destroyed) return;
  const ready = current.database && current.redis;
  const payload = current.payload !== undefined ? current.payload : {
    status: ready ? "ready" : "unavailable",
    code: ready ? "OK" : "DEPENDENCY_UNAVAILABLE",
    dependencies: { database: current.database, redis: current.redis },
    models: "not_configured",
  };
  response.writeHead(current.status ?? 200, { "Content-Type": "application/json" });
  response.end(current.raw ?? JSON.stringify(payload));
});
server.listen(17801, "127.0.0.1");
