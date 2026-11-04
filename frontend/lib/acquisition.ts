export const states = ["RESOLVED", "PENDING", "ACQUIRING", "PROBING", "SUCCEEDED", "FAILED_PERMANENT"] as const;
export type Job = { schema_version: "1.0.0"; source_id: string; asset_id: string; job_id: string; platform: string; state: typeof states[number]; attempts: number; error: { code: string } | null; validation: Record<string, string | number>; fallback: "upload" };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export function parseJob(value: unknown): Job | null {
  if (!value || typeof value !== "object") return null;
  const j = value as Job;
  if (j.schema_version !== "1.0.0" || ![j.source_id, j.asset_id, j.job_id].every(id => typeof id === "string" && uuid.test(id)) || !states.includes(j.state) || !Number.isInteger(j.attempts) || j.attempts < 0 || j.attempts > 2 || !["file_upload", "douyin", "tiktok", "bilibili", "youtube"].includes(j.platform) || j.fallback !== "upload") return null;
  if (j.error !== null && (!j.error || !/^[A-Z_]{2,40}$/.test(j.error.code))) return null;
  if (j.state === "FAILED_PERMANENT" && !j.error) return null;
  if (j.state !== "FAILED_PERMANENT" && j.error) return null;
  if (!j.validation || typeof j.validation !== "object" || Array.isArray(j.validation)) return null;
  if (j.state === "SUCCEEDED" && (typeof j.validation.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(j.validation.sha256) || typeof j.validation.bytes !== "number" || j.validation.bytes <= 0)) return null;
  const validation: Record<string, string | number> = {};
  for (const key of ["sha256", "bytes", "duration_ms", "container", "validation", "acquired_at_ms"]) {
    const value = j.validation[key];
    if (value !== undefined) {
      if (!(typeof value === "string" && value.length <= 100) && !(typeof value === "number" && Number.isSafeInteger(value) && value >= 0)) return null;
      validation[key] = value;
    }
  }
  return { schema_version: "1.0.0", source_id: j.source_id, asset_id: j.asset_id, job_id: j.job_id, platform: j.platform, state: j.state, attempts: j.attempts, error: j.error ? { code: j.error.code } : null, validation, fallback: "upload" };
}
