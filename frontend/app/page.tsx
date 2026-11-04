import StatusPanel from "./status-panel";
import Link from "next/link";

export default function Home() {
  return <main>
    <header><Link className="brand" href="/">◧ <span>Video Analyzer</span></Link><span className="badge">本地工作台 · 0.1</span></header>
    <section className="intro"><p className="eyebrow">视频拆解与复刻</p><h1>先看清每一镜，<br/>再创作下一条。</h1>
      <p className="subtitle">从原片证据到拍摄脚本，让创作有据可循。</p></section>
    <StatusPanel/>
    <section className="upcoming"><div><span className="step">下一阶段</span><h2>从一条视频开始</h2>
      <p>上传获授权的 MP4/MOV，或提交分享链接。</p></div><Link className="coming" href="/import">导入视频</Link></section>
    <footer>素材留在自己的设备上。<span>基础设施版本 A01</span></footer>
  </main>;
}
