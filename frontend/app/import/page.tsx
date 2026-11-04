import Link from "next/link";
import ImportPanel from "./panel";
export default function ImportPage() {
  return <main><header><Link className="brand" href="/">◧ Video Analyzer</Link><span className="badge">A02 · 视频采集</span></header><h1>从一条视频开始</h1><p>仅处理您获授权的素材。采集完成后保存在本机，分析功能尚未开放。</p><ImportPanel/></main>;
}
