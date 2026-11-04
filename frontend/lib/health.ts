export type Health = {
  status: "ready" | "unavailable";
  api_available: boolean;
  dependencies: { database: boolean; redis: boolean };
  models: "not_configured";
};

export const unavailableHealth: Health = {
  status: "unavailable", api_available: false,
  dependencies: { database: false, redis: false }, models: "not_configured",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function validCore(value: unknown): value is Omit<Health, "api_available"> & Record<string, unknown> {
  if (!isRecord(value) || !isRecord(value.dependencies)) return false;
  const { database, redis } = value.dependencies;
  if (typeof database !== "boolean" || typeof redis !== "boolean" || value.models !== "not_configured") return false;
  return (value.status === "ready" && database && redis) || (value.status === "unavailable" && !(database && redis));
}

// The HTTP status, dependency flags and declared readiness must agree.
export function parseBackendHealth(value: unknown, httpStatus: number): Health | null {
  if (!validCore(value)) return null;
  if (value.status === "ready" ? httpStatus !== 200 || value.code !== "OK"
    : httpStatus !== 503 || value.code !== "DEPENDENCY_UNAVAILABLE") return null;
  return { status: value.status, api_available: true,
    dependencies: { database: value.dependencies.database, redis: value.dependencies.redis }, models: "not_configured" };
}

export function parseBrowserHealth(value: unknown, httpStatus: number): Health | null {
  if (!validCore(value) || typeof value.api_available !== "boolean") return null;
  if (value.status === "ready" ? httpStatus !== 200 || !value.api_available : httpStatus !== 503) return null;
  if (!value.api_available && (value.dependencies.database || value.dependencies.redis)) return null;
  return { status: value.status, api_available: value.api_available,
    dependencies: { database: value.dependencies.database, redis: value.dependencies.redis }, models: "not_configured" };
}
