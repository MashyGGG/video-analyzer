"use client";
import { useEffect, useState } from "react";
import { parseBrowserHealth, unavailableHealth, type Health } from "../lib/health";

export default function StatusPanel() {
  const [health, setHealth] = useState<Health | null>(null);
  const [checked, setChecked] = useState(false);
  useEffect(() => {
    let disposed = false;
    let inFlight = false;
    let controller: AbortController | null = null;
    async function refresh() {
      if (disposed || inFlight) return;
      inFlight = true;
      const requestController = new AbortController();
      controller = requestController;
      const timeout = setTimeout(() => requestController.abort(), 8000);
      try {
        const response = await fetch("/api/health", {cache: "no-store", signal: requestController.signal});
        const data = await response.json();
        if (requestController.signal.aborted) throw new Error("Health request timed out");
        if (!disposed) setHealth(parseBrowserHealth(data, response.status) ?? unavailableHealth);
      } catch {
        if (!disposed) setHealth(unavailableHealth);
      } finally {
        clearTimeout(timeout);
        inFlight = false;
        controller = null;
        if (!disposed) setChecked(true);
      }
    }
    void refresh();
    const timer = setInterval(() => void refresh(), 15000);
    return () => {disposed = true; clearInterval(timer); controller?.abort();};
  }, []);
  const ready = health?.status === "ready";
  const items = [
    {name: "本地 API", ok: health?.api_available === true, detail: "服务连接"},
    {name: "数据库", ok: health?.dependencies?.database === true, detail: "持久化与迁移"},
    {name: "Redis", ok: health?.dependencies?.redis === true, detail: "队列连接"},
  ];
  return <section className="panel" aria-label="本地服务状态" aria-live="polite">
    <div className="panel-heading"><div><p className="eyebrow">运行状态</p><h2>{!checked ? "正在连接本地服务" : ready ? "基础服务已就绪" : "部分服务暂不可用"}</h2></div>
      <span className={`indicator ${ready ? "good" : "waiting"}`}>{!checked ? "检测中" : ready ? "已连接" : "请检查服务"}</span></div>
    <div className="services">{items.map(item => <div className="service" key={item.name}><div className="service-top"><h3>{item.name}</h3>
      <span className={`dot ${item.ok ? "good" : "waiting"}`} aria-label={item.ok ? "正常" : "待连接"}/></div><p>{item.detail}</p>
      <strong>{!checked ? "检测中" : item.ok ? "正常" : "暂不可用"}</strong></div>)}</div>
    <div className="model-note"><span className="dot waiting"/><span>本地模型尚未配置，视频分析暂未开放。</span></div>
    <p className="hint">每 15 秒更新。工作进程由容器健康检查单独监控。</p>
  </section>;
}
