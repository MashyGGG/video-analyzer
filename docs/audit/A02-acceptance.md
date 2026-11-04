# A02：视频采集与平台适配器验收

日期：2026-11-04。基线 fa700de，开始时 git 工作区干净。用户授权只完成 A02，保留 A00/A01 历史、不重做 A00、不实现 A03–A09、不做 GitHub Pages。实施前计划：[A02.md](../plans/A02.md)。

## 判定范围

本卡对授权本地 MP4/MOV 提供上传→真实 Celery media 队列→格式/视频轨完整解码→校验和→持久化文件/状态；对分享文案提供 URL 抽取、平台识别、可替换下载 adapter、隔离下载队列、有界失败与上传回退。默认前端仍为 3100，原 A01 健康合同保留。平台真实成功下载单独验收，不能用适配器测试或故障注入替代。

本机为原 A01 Windows 11 / Docker Desktop Linux amd64 环境，硬件记录沿用 [A01](A01-acceptance.md)。本次实际工具版本以 evidence/A02 的 acceptance、commands、container-packages 为准；前端 Node 22.23.1、Chromium 桌面/Pixel 7 模拟视口，后端容器 Python 3.12。无 GPU 不影响 A02。

## 设计与接口

- `backend/app/acquisition.py`：Pydantic/OpenAPI、owner capability 验证、来源和任务持久化、准入上限、原子状态转移；`limits.py` 在 JSON 解析前限制字节量。
- `services/sources/security.py`：URL 和平台规则；`adapters.py` 可替换 SourceAdapter；`download_cli.py` 固定重定向上限；`egress.py` 独立公网出口；`media.py` 仅基本媒体验证；`cleanup.py` 管理员清理。
- `tasks/acquire.py`：独立 download / media Celery 队列，不修改 infrastructure 队列职责；API 不执行 FFmpeg 或 yt-dlp。不同 phase 的 CAS 避免同一任务重复获取/校验；晚到的下载结果不得恢复已超时任务。
- `frontend/app/import` 与 Next 同源采集代理：授权确认、文件/分享文本提交、状态轮询、刷新恢复和明确上传回退；不扩展时间轴/分析工作台。代理/客户端检验响应合同，拒绝伪成功；过滤未知字段与原始错误体。

| HTTP（/api/v1） | 请求 | 返回 |
|---|---|---|
| POST /assets/upload | raw bytes、Content-Length、X-Authorized:true、X-Owner | 202 Job，不代表验证成功 |
| POST /assets/resolve | {text,authorized:true}、X-Owner | 200 Job / RESOLVED，无页面网络请求 |
| POST /assets/{source_id}/acquire | 空 body、X-Owner | 202 Job，幂等发布 |
| GET /acquisition/jobs/{job_id} | X-Owner | 200 Job；越权/不存在同为 404 |

Job schema_version=1.0.0，source_id/asset_id/job_id 在 A02 为同一 UUID；state、attempts、validation、error、fallback 由 Pydantic 定义。错误体统一 code/message/retryable/details，不回显请求文本/内部异常。业务接口默认本机管理范围；随机 256-bit HttpOnly/SameSite session 是能力令牌，不是完整账号体系。FastAPI 仅保存 owner 的 SHA256，前端不能代替后端所有权检查。完整说明、错误码及直接调用约束见 [运行手册](../runbooks/A02-acquisition.md)。

状态 RESOLVED→PENDING(download)→ACQUIRING→PENDING(media)→PROBING→SUCCEEDED / FAILED_PERMANENT。上传从 PENDING(media) 开始。只有超时/限流最多两次，2 秒 Celery countdown；工具自带重试为 0。每 owner 最多5、全局20个未结束任务；创建超过600秒的任务终止。重提创建新 ID，A08 的取消/自动重放不在此卡。

0002_acquisition 新增单表，保存来源/资源 ID、版本、owner、状态/phase、attempts、错误、整数创建时间与验证摘要；原 installation 表保留。缓存使用 /data/original/{UUID}/source.mp4，上传文件名不参与路径。成功保存 SHA256、字节、duration_ms、获取时间与验证版本。不同资产目前独立保存，无跨资产去重。降级删除本卡记录但保留文件；维护窗口先成对备份 DB/volume，再 downgrade 至0001并回退镜像，恢复需还原配对备份。隔离迁移演练验证完整 head/base 往返，不对日常库做降级。

## 首批平台与工具来源

| 来源 | 实现范围 | 真实成功验收 |
|---|---|---|
| 本地 MP4/MOV | 白名单 ISO BMFF brand，≤200 MiB、≤180000ms、≤4096px，真实探测+完整视频轨解码 | 合成授权 fixture 实测，见下文 |
| 抖音（首批优先） | douyin.com 分享/视频链接；实验性 yt-dlp 路径 | **BLOCKED：无获授权样例** |
| TikTok | tiktok.com；同样需公开授权单文件 HTTPS MP4 | **BLOCKED：无获授权样例** |
| B站 | bilibili.com / b23.tv；不支持分离音视频 | **BLOCKED：无获授权样例** |
| YouTube | youtube.com / youtu.be；禁远程 JS、登录与地理绕过 | **BLOCKED：无获授权样例** |
| 任意 direct_media / HTTP / HLS / DASH | 本卡不支持，明确上传回退 | 不宣称支持 |

平台支持列表不能保证链接一直可下载，也不代表平台授权。新 CDN、格式、访问控制或提取逻辑变化按错误码停止；不自动降画质、不导入 Cookie，不绕过 DRM/登录/验证码/付费墙/风控。未被测试的路径不会因 README 宣传标成 PASS。

| 依赖 | 固定版本/许可与证据 |
|---|---|
| yt-dlp | **2026.10.26**，uv.lock + hash-locked requirements.lock；使用 PyPI wheel 的 **Unlicense**，不采用 PyInstaller GPL bundle。官方 [固定 tag README](https://raw.githubusercontent.com/yt-dlp/yt-dlp/2026.10.26/README.md) 与 [LICENSE](https://raw.githubusercontent.com/yt-dlp/yt-dlp/2026.10.26/LICENSE)。固定入口禁配置/插件/远程组件/JS、geo bypass/fixup；argv 调用与版本 contract 已测 |
| FFmpeg/ffprobe | Debian **7:5.1.9-0+deb12u1**；实际 buildconf 含 enable-gpl，`ffmpeg -L` 显示 **GPL-2.0-or-later**，不是默认 LGPL 构建。实际配置/许可输出在 acquisition/acceptance.json；[Debian 固定源码](https://sources.debian.org/src/ffmpeg/7%3A5.1.9-0%2Bdeb12u1/)、官方 [protocol whitelist](https://ffmpeg.org/ffmpeg-protocols.html)、[ffprobe](https://ffmpeg.org/ffprobe.html)、[许可说明](https://ffmpeg.org/legal.html)。与 Python 以独立可执行进程调用；若分发镜像需遵守相应源码/通知义务 |
| GNU coreutils timeout | 来自原 digest 固定 Debian 基础镜像，9.1-1 / GPL-3.0-or-later；独立监督工具时限，避免 Worker 突然退出后工具无限运行 |

新增 Python 直接/传递项已锁 wheel hash；原 A01 依赖不升级。APT 固定 FFmpeg 直接包版本，并记录 [实际 OS 包清单](../../evidence/A02/container-packages.txt)；APT 传递包没有逐项 hash 锁或 snapshot 源，不宣称跨日期逐字节重建镜像。本次没有引入模型权重、付费 API、平台凭据或第三方下载服务。

## 安全边界与限制

download Worker 无公网路由，只有 backend+acquisition internal 网络；media 仅 backend internal；只有无 secret/媒体卷的 egress 有 outbound 网卡。gateway 只 CONNECT:443，域名后缀白名单、检查全部 DNS 回答（混合公网/私网同样拒绝）、拒绝非公网/mapped IPv6/metadata，直接连接已验证数值 IP并复核 peer，避免二次解析。重定向每个目标连接受同样约束；urllib 上限5，同址2。HTTPS 证书校验保留，不以忽略证书换成功。

工具均 argv、无 shell、禁工具更新/外部插件、socket/总时间/速率/体积上限，Worker 并发1。容器非 root、只读根、cap drop、CPU/内存/PID、fsize/tmpfs 限制；下载器原始输出使用匿名 tmpfs 文件，不持久化 Cookie/签名 CDN 日志。媒体强制 mov demuxer、file 协议、关闭 data references/绝对引用，FFmpeg 单线程及单次分配上限。文件独占 UUID 目录，不使用用户文件名，不允许覆盖；失败清理 staging/未发布原片。成功素材需要管理员监控磁盘和保留期。

另外拒绝可能封装私网 IPv4 的 NAT64/6to4/Teredo 地址，以及 [Azure 的特殊 168.63.129.16 服务地址](https://learn.microsoft.com/en-us/azure/virtual-network/what-is-ip-address-168-63-129-16)，不只依赖 is_global 的布尔分类。这些是模拟 DNS 单元负例；没有把本机未启用的 NAT64 环境宣称为真实部署验收。

剩余边界：不是互联网多租户产品；清除会话后不能找回任务；无登录/RBAC/共享工作区；不支持旧式无 ftyp QuickTime、复杂编解码覆盖、完整音频解码、跨资产去重、配额/自动过期。硬终止/掉电需一小时后的管理 cleanup，不能宣称完整 A08 故障恢复。Ubuntu原生/真实手机/其他浏览器/压力SLO/授权平台成功均未验证。

## 测试与真实验收

| 最终命令 | exit | 通过/失败/跳过 | 独立证据 |
|---|---:|---|---|
| `cd backend; uv run --frozen ruff check app migrations tests`（另检查新增/修改脚本） | 0 | 静态检查通过 | [checks/20261104T082740Z](../../evidence/A02/checks/20261104T082740Z/)；doctor.py 另行 Ruff 通过 |
| `cd backend; uv run --frozen mypy` | 0 | 21 个源文件无类型错误 | 同上 mypy.log |
| `cd backend; uv run --frozen pytest -q` | 0 | **81/0/0** | 同上 pytest.log、summary.json |
| `cd frontend; npm run verify` | 0 | **72/0/0**，flaky 0；lint/TS/生产构建通过 | [checks/20261104T082018Z](../../evidence/A02/checks/20261104T082018Z/) |
| `python scripts/verify_a01_e2e.py --output-dir evidence/A02/infra-run-04` | 0 | 真实基础设施 **25/0/0** + 采集/隔离 **26/0/0** + 浏览器 **7/0/0**，flaky0 | [infra-run-04](../../evidence/A02/infra-run-04/)：summary / infrastructure/acceptance / acquisition/acceptance / playwright / commands |

`python scripts/verify_a02_checks.py` 是有日志/退出码的质量门禁入口；`--backend-only` 可单跑后端，每次新建 UTC 目录。中间记录始终保留，不用后续通过覆盖失败。

最终隔离运行12条构建/启动/验收/doctor/采集/清理命令均 exit0，结束后停止自己的容器/网络并保留卷；日常数据没有参与故障注入。[镜像源码校验](../../evidence/A02/image-source-manifest.json)核对镜像中的21个后端 Python 文件与最终工作区，差异0；[源文件清单](../../evidence/A02/source-manifest.json)记录内容SHA256。[OpenAPI快照](../../evidence/A02/openapi.json)由当前Pydantic生成。

后端 81 项包括原 A01 回归、分享文本及四平台识别、URI/域名/端口/userinfo、16 类 DNS/IP 负例、数值 IP 连接与 peer 校验、重定向上限与目标规则、大小/长度矛盾、真伪格式/视频轨/时长/尺寸、argv/超时/错误脱敏、队列异常、两次重试、清理、所有权、容量、阶段幂等和晚到结果。媒体探测/下载器故障模拟与真实工具验收分开；受控 adapter 成功不算平台成功。

前端 72 项为 52 个 UI（桌面/Pixel7各26）和20个代理合同，保留原42项；新增上传授权/成功/刷新保留/无横向溢出、六类任务错误回退、网络/错误体/伪成功拒绝、轮询超时迟到响应/恢复、同源和路由/体积限制、上游超时/超长体及未知字段丢弃。截图来自明确受控 fixture；已人工检查 [桌面](../../evidence/A02/screenshots-final/chromium-desktop.png)、[移动视口](../../evidence/A02/screenshots-final/chromium-mobile.png)，修正按钮和错误提示对比度，无横向溢出。

真实容器场景：人工生成1秒蓝色视频 MP4/MOV，均真实上传→Celery→ffprobe/FFmpeg→SHA256/落盘→Worker重启保持；伪视频清理、越权404、非法来源拒绝；实际 download 队列的受控不支持平台故障→明确错误/上传回退；实际下载/媒体容器公网 TCP 被阻断、非root；gateway对回环/metadata/端口/未知域名返回403，且无数据库secret/媒体目录。原 A01 的真实 DB/Redis/API 故障、持久化、队列、迁移与恢复全部保留。实际浏览器新增真实成功上传/伪装文件回退两项，合计7项；这些请求没有 Playwright route mock。

已知首轮问题：前端错误 alert 定位与 Next 路由公告冲突、内部 URL 与浏览器 Origin 不同；均有失败记录并已修正。首轮真实容器 A01 25项、A02 26项、浏览器7项通过，但 doctor 仍限定6个服务导致总门禁 FAIL；修正为9个服务后另开目录重跑。测试适配器成功只证明编排/幂等，真实下载队列使用明确的故障注入证明失败回退，不是平台成功下载证据。

## 固定汇报

任务 ID：A02。

范围与设计：上传/分享文本/实验性平台适配、分离队列与受控公网网关、基本媒体验证、持久化与最小导入页；默认3100，A01健康兼容。

变更文件：backend/app/acquisition.py、limits.py、services/sources、tasks/acquire.py、0002迁移、配置/依赖锁/Dockerfile；Compose、doctor/验收脚本；frontend导入页/代理/合同/E2E；README、本计划/手册/报告、evidence/A02。

测试命令、退出码、通过/失败/跳过数量：Ruff/mypy exit0；Pytest81/0/0；前端72/0/0、flaky0；真实基础设施25/0/0、采集/隔离26/0/0、浏览器7/0/0，最终隔离脚本exit0。后端仍有一条原有 Starlette/httpx 弃用警告。

真实验收证据路径（脱敏）：evidence/A02，历史 evidence/A00/A01 不改写；最终执行目录见上表。

已知缺陷、性能约束、未测事项：见前述安全/范围限制。真实授权平台下载成功 BLOCKED，Ubuntu原生与压力SLO未测；没有因GPU缺失阻塞上传/采集。

结论：BLOCKED（本机上传、采集编排/错误回退、安全负例和A01回归 PASS；真实平台成功下载因无授权样例 BLOCKED。不构成产品发布验收）。

下一任务建议：补充授权样例并逐平台签收，再评审 A03；本次不提前实现 A03。

## 2026-11-04：授权抖音样例追加验收

上述为原始A02交付记录；后续用户已明确授权单个抖音分享链接，并执行真实验收。该链接解析/排队成功，下载尝试1次后返回SOURCE_ACCESS_DENIED，进入FAILED_PERMANENT；无缓存视频、暂存已清理，真实浏览器显示上传回退。本条“缺少授权样例”已解除，成功下载仍BLOCKED，具体拒绝来自平台还是受控出口尚未确定。其他平台未新增真实样例。

本次9/0/0检查已记录，临时驱动最后控制台打印发生编码错误exit1；修复输出后离线证据/编码校验exit0，没有再次请求平台。完整退出码边界和独立证据见 [抖音追加报告](A02-douyin-20261104.md)，不把失败下载或旧fixture当作平台成功。
