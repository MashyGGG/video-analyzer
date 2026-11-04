# A02 本地采集运行手册

默认 http://127.0.0.1:3100/import；保持 A01 的 health/live/ready 合同。首次或升级：

```powershell
python scripts/init_local.py
docker compose up -d --build --wait
docker compose logs --tail 100 worker-download worker-media
```

不要将本机端口直接暴露到互联网。A02 的所有权使用随机 256-bit capability：Next HttpOnly/SameSite=Strict session cookie，只向 FastAPI 发送 X-Owner，数据库仅存其 SHA256。它不是完整账号体系；清除 cookie 后无法找回既有任务。Next POST 必须有同源 Origin，默认只接受 localhost/127.0.0.1 Host，防止 DNS rebinding；自有反向代理部署须配置 frontend 的 PUBLIC_ORIGIN 为精确 HTTPS origin，并另做访问控制/TLS。未经管理员配置不接受任意 Host。

API 只绑定本机，直接调用需自行保管随机 64 位十六进制 X-Owner（相当于 bearer 密钥），不可写入证据/日志。上传是 raw application/octet-stream，不是 multipart；必须 Content-Length 与 X-Authorized:true。不要把平台 Cookie、凭据或客户素材提交至仓库。

## 合同

OpenAPI：GET http://127.0.0.1:8000/openapi.json，Pydantic 定义在 backend/app/acquisition.py。所有业务路由均验证 owner，越权与不存在同为 404。

| 方法/路径（前缀 /api/v1） | 请求 | 结果 |
|---|---|---|
| POST /assets/upload | raw bytes；授权/owner/长度头 | 202 Job，后续在 media 队列校验 |
| POST /assets/resolve | {text, authorized:true} | 200 Job，RESOLVED；不下载、不请求页面 |
| POST /assets/{source_id}/acquire | 空请求体、owner | 202 Job；重复请求不重复发布 |
| GET /acquisition/jobs/{job_id} | owner | 200 Job，状态、有限 attempts、错误与验证摘要 |

Job 中 source_id/asset_id/job_id 在 A02 同一个 UUID，schema_version=1.0.0；上传返回 202 不代表有效媒体。最终 SUCCEEDED 才表示真实格式及完整视频解码成功。标准错误：{code,message,retryable,details:{fallback:"upload"}}，请求校验不回显不可信输入。阶段由持久化 phase 和 CAS 控制，避免下载/校验重复消息串队。队列发布失败终止；重提交生成新 ID。

状态 RESOLVED→PENDING→ACQUIRING→PENDING（media phase）→PROBING→SUCCEEDED / FAILED_PERMANENT。上传从 PENDING 进入 PROBING。仅限流和超时自动再试一次，Celery countdown=2，有界重试不占用 Worker 等待；最终错误不再自动重试。超过创建时间 600 秒的任务在查询/执行时终止。排队时间计入总预算，繁忙时请重新提交。每 owner 最多 5、全局最多 20 个未结束任务，PostgreSQL 事务锁保护准入。

## 限制与失败回退

- 文件 ≤200 MiB、时长 ≤180000ms、每维 ≤4096px。只接收代码白名单 ISO-BMFF major brands 的 MP4/MOV；不支持无 ftyp 的旧式 QuickTime。原文件名/Content-Type 不参与安全判断，服务端不使用用户文件名作为路径。
- ffprobe 15 秒、完整视频轨解码 45 秒；无音轨有效。完整音频解码、媒体元数据规范化留给 A03。限制由 A02 常量固定，修改后必须重新测试；不是可承诺的性能 SLO。
- 平台均为实验性条件接入：抖音优先、TikTok/B站/YouTube。需要可公开访问且明确授权的单文件 HTTPS MP4；无 Cookie、登录、DRM、验证码、地区绕过。没有授权样例就不能宣布真实平台成功。
- 不自动回退低画质；HLS/DASH、分离音视频、动态 JS 依赖或新 CDN 未在本卡支持。工具请求非白名单域名或非 HTTPS 会被拒绝；用户应上传合法本地文件。
- SOURCE_UNSUPPORTED / SOURCE_AUTH_REQUIRED / SOURCE_ACCESS_DENIED / SOURCE_RATE_LIMITED / SOURCE_TIMEOUT / SOURCE_EXPIRED / SOURCE_CHANGED / SOURCE_UNSAFE / MEDIA_INVALID / MEDIA_TOO_LARGE / MEDIA_LIMIT_EXCEEDED / QUEUE_UNAVAILABLE / ACQUISITION_BUSY 等均显示上传回退。不记录下载器原始正文。

## 网络、资源与落盘

download 仅 backend+acquisition 两个 internal 网络；media 仅 backend internal；egress 独占 outbound 出口，且无数据库 secret/视频卷/公开端口。gateway 仅 CONNECT:443，固定域名后缀白名单，DNS 所有回答均须公网、拒绝 mapped IPv6，直接连接一次解析得到的数值地址并校验 peer。跨域重定向每次新连接都受同一校验，同主机连接只能到原已验证 IP。yt-dlp urllib 重定向上限 5、同址重复 2；下载 socket 8 秒、每次工具 160 秒、外层进程 165 秒、单次任务硬限 185 秒。没有 TLS 解密；下载器仍执行证书校验。

gateway 最多 4 个活动隧道，每隧道 180 秒、220 MiB 双向流量，单任务仅选一个媒体且并发 Worker=1、速率4 MiB/s、实际文件200 MiB上限；容器资源与 fsize 见 compose。临时下载日志和视频均受 fsize 限制；不将日志返回给用户。GNU timeout 独立监督工具进程，即使 Celery 子进程被强杀仍有工具时限。媒体只用 mov demuxer、本地 file 协议，关闭外部 data references/绝对引用；非 root、只读根目录、CPU/内存/PID 上限。

验证成功文件：/data/original/{UUID}/source.mp4（MOV 同样保留原字节，不做转码）。同 owner/不同提交分别保存，暂不做跨资产去重。SHA256、字节、容器、duration_ms、获取时间和验证版本入库；来源、平台资源 ID、工具版本单独入库，不长期存 CDN 临时 URL/分享全文。先独占写文件，成功后事务发布状态；失败清理 staging 与未发布原片。媒体卷必须监控容量；成功文件保留到管理员清理，当前没有配额/自动保留期。

SIGKILL/主机掉电不保证 finally 执行；超过一小时的失败或遗留工作通过管理命令清理（先确认无人工维修中的任务）：

```powershell
docker compose exec -T worker-media python -m app.services.sources.cleanup
```

它只操作数据库记录对应、超过一小时且非 SUCCEEDED 的 UUID 目录。A08 的可恢复取消、重放与长期生命周期不在本卡。

## 迁移与恢复

升级前停止入口/Worker，备份 PostgreSQL 与 work_data 成对快照。0002_acquisition 是独立新增表，不修改 installation。migrate 自动 upgrade head；ready 验证 0002 head。恢复/降级只能在维护窗口与备份后运行：停止 api、worker-download、worker-media；运行 `docker compose run --rm migrate alembic downgrade 0001_installation`，随后回退到 A01 代码/镜像。该命令删除采集记录，保留文件卷；不在旧 schema 上启动 A02 API。需要恢复时还原同一时点 DB/volume，再 upgrade head。验收脚本只在独立数据库做 base→head→base→head，不操作日常数据。

## 验收

```powershell
cd backend
uv run --frozen ruff check app migrations tests
uv run --frozen mypy
uv run --frozen pytest -q
cd ../frontend
npm run verify
cd ..
python scripts/verify_a01_e2e.py --output-dir evidence/A02/<new-unique-run>
```

最后命令建立独立 Compose 项目、原 A01 真实故障/迁移/持久化检查、新 A02 真实上传/队列/出口负例、真实浏览器上传和回退，finally 停止它自己的容器与网络并保留卷。不以测试 adapter 或故障注入证明平台下载成功。授权样例应由管理员在本地操作导入页，另外记录授权依据、脱敏资源标识、版本、哈希/结果；不得将私有视频或会话凭据提交证据。
