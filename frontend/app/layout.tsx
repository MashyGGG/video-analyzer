import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {title: "Video Analyzer · 本地工作台", description: "视频拆解与复刻工作台"};
export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
