"use client";
import { useEffect, useState } from "react";
import { parseJob, type Job } from "../../lib/acquisition";

export default function ImportPanel() {
  const [authorized, setAuthorized] = useState(false);
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const saved = sessionStorage.getItem("acquisition-job");
    const id = job?.job_id ?? (saved && /^[a-f0-9-]{36}$/.test(saved) ? saved : null);
    if (!id || job?.state === "SUCCEEDED" || job?.state === "FAILED_PERMANENT") return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const response = await fetch(`/api/acquisition/jobs/${id}`, { cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10_000)]) });
        const next = parseJob(await response.json());
        if (!response.ok || !next) throw new Error("状态查询失败，请重新提交或上传本地文件。");
        if (controller.signal.aborted) return;
        setJob(next); setError("");
        if (["SUCCEEDED", "FAILED_PERMANENT"].includes(next.state)) return;
      } catch { if (controller.signal.aborted) return; setError("状态查询失败，请重新提交或上传本地文件。"); }
      timer = setTimeout(poll, 2000);
    }
    timer = setTimeout(poll, 0);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [job?.job_id, job?.state]);
  async function submit(kind: "upload" | "link") {
    if (busy) return;
    setBusy(true); setError(""); setJob(null); sessionStorage.removeItem("acquisition-job");
    try {
      if (!authorized) throw new Error("请先确认素材授权。");
      if (kind === "upload" && (!file || file.size === 0 || file.size > 200 * 1024 * 1024)) throw new Error("请选择不超过 200 MB 的 MP4/MOV。");
      let response = await fetch(`/api/acquisition/assets/${kind === "upload" ? "upload" : "resolve"}`, { method: "POST", headers: kind === "upload" ? { "X-Authorized": "true", "Content-Type": "application/octet-stream" } : { "Content-Type": "application/json" }, body: kind === "upload" ? file : JSON.stringify({ text, authorized: true }), signal: AbortSignal.timeout(195_000) });
      let data = await response.json();
      let next = parseJob(data);
      if (!response.ok || !next) throw new Error(typeof data.code === "string" && /^[A-Z_]{2,40}$/.test(data.code) ? data.code : "采集服务暂不可用");
      if (kind === "link") {
        response = await fetch(`/api/acquisition/assets/${next.source_id}/acquire`, { method: "POST", signal: AbortSignal.timeout(10_000) });
        data = await response.json(); next = parseJob(data);
        if (!response.ok || !next) throw new Error("下载任务创建失败，请上传本地文件。");
      }
      setJob(next); sessionStorage.setItem("acquisition-job", next.job_id);
    } catch (e) { setError(e instanceof Error ? e.message : "采集服务暂不可用"); }
    finally { setBusy(false); }
  }
  return <section className="import-panel">
    <label><input type="checkbox" checked={authorized} onChange={e => setAuthorized(e.target.checked)}/> 我确认有权处理此视频</label>
    <h2>上传本地视频</h2><p>MP4 / MOV，最多 200 MB、3 分钟、4096 像素。服务器会校验真实格式和可解码性。</p>
    <label>选择视频<input type="file" accept=".mp4,.mov" onChange={e => setFile(e.target.files?.[0] ?? null)}/></label><button disabled={busy || !authorized || !file} onClick={() => submit("upload")}>上传视频</button>
    <h2>导入分享链接</h2><p>抖音优先；TikTok、B站、YouTube 为实验性支持，仅限公开授权的单文件 MP4。登录、验证码、限流或不支持的格式请改用上传。</p>
    <label>分享文本<textarea maxLength={4096} value={text} onChange={e => setText(e.target.value)}/></label><button disabled={busy || !authorized || !text.trim()} onClick={() => submit("link")}>提交链接</button>
    {busy && <p role="status">正在提交，请稍候…</p>}
    {error && <p role="alert" aria-label="采集错误">{error} 请尝试上传获授权的本地 MP4/MOV 文件。</p>}
    {job && <div aria-live="polite"><p>任务状态：{job.state}</p><p>任务编号：{job.job_id}</p>{job.state === "SUCCEEDED" && <p>视频已校验并保存在本机。</p>}{job.error && <p role="alert" aria-label="采集错误">{job.error.code} · 请上传获授权的本地 MP4/MOV 文件。</p>}</div>}
  </section>;
}
