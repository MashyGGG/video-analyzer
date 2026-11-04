# A00 开源基线审计

审计日期：2026-11-04（Asia/Shanghai）。任务范围仅 A00。先行计划与失败用例见 [A00-plan.md](A00-plan.md)。

**建议建立轻量新底座，不直接 fork `parse_video` 作为产品基础。** 已完成源码、许可证和出站调用审阅，并尝试原始测试与 Compose。前端构建通过；后端安装、测试和完整服务启动没有通过证据。完整 A00 结论为 **BLOCKED**，不能据此宣布上游可生产使用或开始无条件复用。设计取舍见 [ADR-001](../decisions/ADR-001-foundation.md)，人类 Go/No-Go 审阅尚未发生。

## 1. 固定提交、范围与证据口径

| 项目 | 实际记录 |
|---|---|
| 上游 | https://github.com/XztCloud/parse_video |
| 审计提交 | `adc13afb47a112f0def0435231e691a5307e5b49` |
| 上游提交时间 | `2026-09-20T11:48:56+08:00`，不是本次审计日期 |
| 检出方式 | 浅克隆后 detached checkout 到完整 SHA；见 [锁定记录](../../evidence/A00/pinned-checkout.json) |
| 源码范围 | Git 跟踪的 176 个文件；哈希、路径、表、路由、导入及网络调用候选见 [静态清单](../../evidence/A00/static-inventory.json) |
| 源码完整性 | 审计前后 `git status --porcelain` 为空；仅添加被忽略的临时 `.env`、依赖和构建产物；见 [检查记录](../../evidence/A00/upstream-integrity-final.json) |
| 产品仓库 | 当前是文档起步目录，未导入上游业务源码、数据库或模型；本次不实现 A01–A09 |

下文 `up:路径:行号` 均指上述固定提交中的源码位置，绝非浮动 main。永久源码根地址：
https://github.com/XztCloud/parse_video/tree/adc13afb47a112f0def0435231e691a5307e5b49 。

结论区分三类：源码直接可见的事实、本次实际命令结果、尚未执行的风险推断。README、上游已有报告、mock 和合成样例均没有被计作真实模型/平台验收。

### 本机与隔离措施

- Windows 11 / AMD64；AMD Ryzen AI 9 365（10 核/20 线程），内存约 29.8 GiB，系统枚举到 AMD Radeon 880M。`nvidia-smi` 不存在，未取得 NVIDIA/CUDA 可用证据。[硬件](../../evidence/A00/hardware.json)、[GPU 探测](../../evidence/A00/gpu.json)。
- Docker Desktop 4.96.0，Linux Engine 29.9.1，Compose v5.6.0；主机 Node v22.23.1；测试虚拟环境 Python 3.12.13；审计脚本使用 Python 3.14.6。[Docker](../../evidence/A00/docker-version.json)、[Compose](../../evidence/A00/compose-version.json)、[Python](../../evidence/A00/python-runtimes.json)、[Node](../../evidence/A00/node-version.json)。
- 审计缓存放在被忽略的 `.audit-cache/`。未提供任何云端 API Key、平台 Cookie、真实视频或权重；没有调用付费模型和真实平台下载。
- Compose 使用独立 project `video-analyzer-a00` 和随机临时本地密码。为避免暴露数据库，使用仅改端口绑定的审计 override：前端/API/PostgreSQL/Redis 分别绑定本机 13000/18000/15433/16380。**这是安全测试夹具，不是未经改动的原始部署成功证明。** 上游业务源码、Dockerfile 和主 Compose 未修改。
- Node 安装使用 `npm ci --ignore-scripts`；构建设置 `NEXT_TELEMETRY_DISABLED=1`。业务服务启动未成功，不能据此证明无云端 Key 的可用性。

## 2. 现有架构与数据库

源码拓扑为浏览器 → Next.js `/api/*` 代理 → FastAPI → PostgreSQL/Redis → 单个 Celery worker。解析任务依次调用 FFmpeg/PySceneDetect、字节云 ASR、视觉 LLM、剧本 LLM；复刻任务另走 LangGraph 的剧情、配音、图片、视频和合成流程。

| 服务/模块 | 源码事实与限制 | 位置 |
|---|---|---|
| `frontend` | Next.js 14；相对 `/api/v1` 请求，经配置的 API_PROXY_TARGET 反向代理 | `up:frontend/next.config.js:3`，`up:frontend/src/lib/api.ts:1` |
| `backend` | FastAPI `/api/v1`；上传接口直接运行 ffprobe，链接接口直接在线下载，然后投递分析任务 | `up:backend/app/main.py:76`，`up:backend/app/api/router/videos.py:51`、`:117` |
| `prestart` | `init-db` 仅做连接检查，再迁移、建管理员 | `up:backend/prestart.sh:7`，`up:backend/app/prestart/prestart.py:25` |
| `celery_worker` | 一个任务模块导入分析与自动成片代码，solo pool；没有项目要求的独立 download/media/analyze Worker | `up:backend/app/celery_app.py:7`、`:36`，`up:backend/app/tasks/parse_video.py:1` |
| PostgreSQL | 同步/异步 SQLAlchemy 引擎，部分资源已有用户归属校验 | `up:backend/app/database.py:10`，`up:backend/app/services/ownership.py:24` |
| Redis | 同时作为 broker/result backend/限流存储 | `up:backend/app/celery_app.py:7`，`up:backend/app/api/deps.py:132` |
| 持久化与网络 | uploads/LOGS 主机挂载、数据库卷；主配置直接公布数据库/Redis 端口，没有分区内网与模型离线隔离 | `up:docker-compose.yml:1` |

### 表与迁移

ORM 中有 14 张实体表（清单不包含 Alembic 自身版本表）：

- `users`：`up:backend/app/models/user.py:13`。
- `videos`：`up:backend/app/models/video.py:19`。
- `scripts`、`script_segments`、`clone_scripts`、`clone_voices`、`clone_role_images`、`clone_scene_images`、`clone_script_segments`、`clone_segment_images`、`clone_segment_video`、`clone_videos`：`up:backend/app/models/script.py:47`–`:206`。
- `voice`：`up:backend/app/models/voice.py:10`；`novels`：`up:backend/app/models/novel.py:11`。

静态迁移图包含 20 个 revision，单根 `99c90f70710a`、单 head `f0e1d2c3b4a5`，各文件定义了 downgrade，但**这不代表迁移或恢复已可执行**。根迁移 `upgrade()` 是 `pass`，下一条迁移直接给 `clone_images` 加列；prestart 没有建表步骤，应用中的 `create_all` 也被注释。因此空数据库部署存在明确的基础表缺失风险；本次未完成完整 Alembic/数据库演练，不伪装成已执行的 SQL 错误。

证据：`up:backend/alembic/versions/99c90f70710a_baseline_version_0709.py:21`，`up:backend/alembic/versions/24bd50e6afee_add_image_prompt.py:21`，`up:backend/app/prestart/prestart.py:25`，`up:backend/app/main.py:32`。后续不能只 stamp head 或直接 create_all 来掩盖缺失迁移。

### 现有数据合同与目标差距

- `ScriptSegment.start_time/end_time`、复刻分镜使用 Float；视觉阶段生成浮点毫秒，复刻编排使用秒。原片脚本和新剧本单位语义需逐处梳理，无法直接满足统一整数毫秒合同。位置：`up:backend/app/models/script.py:67`、`:160`，`up:backend/app/services/visual_service.py:212`，`up:backend/app/services/clone_storyboard.py:384`。
- `generate_script` 把 ASR/视觉内容放进 SystemMessage，并让 LLM 依据经验合并镜头；这不能作为项目要求的独立物理镜头事实来源。位置：`up:backend/app/services/script_generator.py:337`–`:379`。
- 现有解析结果保留原始 ASR/视觉文本，但没有目标 `EvidenceFrame`、`AnalysisVersion`、`observed/inferred/recommended` 合同，也没有独立 OCR 与语义段落模型。位置：`up:backend/app/models/script.py:46`–`:73`、静态清单中的全部实体和导入。
- 视频状态仅 pending/processing/done/failed；没有阶段级检查点、取消、重试状态和规定缓存键。位置：`up:backend/app/models/video.py:12`，`up:backend/app/tasks/parse_video.py:43`–`:165`。这里是目标合同对比，未做崩溃恢复实测。

## 3. 外部 API 与出站清单

以下是**上游第一方业务源码中的出站调用族**。配置域名、重定向、CDN 和第三方 extractor 可改变实际目标；表格不是抓包结果或固定域名白名单。AST 候选清单供人工复核，包含 SDK/编排调用及少量同名内部调用，不把“扫描到 60 处”说成“60 个外部 API”。

| 调用族 | 目标/方法与数据 | 是否在解析主链路 | 源码位置；本地化处理 |
|---|---|---|---|
| 视觉模型 | `LLM_BASE_URL` 的 OpenAI 兼容聊天接口；上传 Base64 帧及上下文 | 是 | `up:backend/app/services/visual_service.py:83`–`:131`、`:199`；替换为仅内网 vLLM，限制端点 |
| 剧本/叙事/复刻 LLM | 同一配置端点；ASR、视觉描述、用户需求/小说内容 | 是；复刻/小说为另一路径 | `up:backend/app/services/llm.py:11`，`up:backend/app/services/script_generator.py:365`、`:493`、`:543`、`:689`、`:751`，`up:backend/app/services/novel_analysis.py:15`；拆分本地模型适配器，禁止 SDK 隐式外网回退 |
| ASR 提交 | POST `https://openspeech-direct.zijieapi.com/api/v3/auc/bigmodel/submit`；完整音频 Base64 + 云凭据头 | 是 | `up:backend/app/services/asr_service.py:23`、`:75`；必须替换 FunASR，不能仅更改 LLM URL |
| ASR 轮询 | POST 同域 `/api/v3/auc/bigmodel/query`；任务标识 | 是 | `up:backend/app/services/asr_service.py:88`、`:98`；与提交共同移除 |
| 字节 TTS | POST `https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse`；台词、音色、Key，接收音频 | 自动成片分支 | `up:backend/app/services/gen_voice.py:35`、`:97`、`:384`；MVP 排除 |
| 火山音色目录 SDK | `SPEECHSAASPRODApi.list_speakers`，服务 `speech_saas_prod` / region `cn-beijing`；AK/SK 签名 | 自动配音分支 | `up:backend/app/services/gen_voice.py:178`–`:198`，`up:backend/app/services/clone_voice.py:129`；MVP 排除。固定 SDK 源码显示 ListSpeakers 路由及 `.volcengineapi.com`/回退端点解析；不是本次实际解析的云主机，见 extra-source-evidence |
| RunningHub 提交 | POST `https://www.runninghub.cn/openapi/v2/run/ai-app/{app_id}`；提示词、媒体路径、workflow 参数 | 自动图片/视频分支 | `up:backend/app/services/gen_image.py:135`、`:193`、`:940`、`:1020`；MVP 排除 |
| RunningHub 查询 | POST `https://www.runninghub.cn/openapi/v2/query`；任务 ID | 同上 | `up:backend/app/services/gen_image.py:136`、`:200`；MVP 排除 |
| RunningHub 媒体上传 | POST `https://www.runninghub.cn/openapi/v2/media/upload/binary`；图片/音频字节 | 音驱视频等分支 | `up:backend/app/services/gen_image.py:270`–`:275`；MVP 排除 |
| RunningHub 结果下载 | GET API 返回的动态对象存储/CDN URL；无 RunningHub Authorization 头的独立 client | 自动生成分支 | `up:backend/app/services/gen_image.py:154`、`:248`–`:257`；动态域名未白名单化，不复用 |
| 通用图片 API | POST `IMAGE_MODEL_BASE_URL`，`x-api-key`、提示词；再 GET 返回 URL | 类方法已实现，当前 generate_image 分支使用静态 RunningHub/Comfy 方法；未确认主工作流调用此通用实例方法 | `up:backend/app/services/gen_image.py:487`–`:579`；列为遗留可调用路径，不能把配置项当活跃流量 |
| ComfyUI HTTP | `COMFY_URL` /prompt、/history/{id}、/view；上传 /upload/image | 可选本地生成分支；配置也可指向公网 | `up:backend/app/services/comfy/api_comfy.py:34`、`:123`、`:157`，`up:backend/app/services/clone_image.py:524`，`up:backend/app/services/clone_frame.py:156`，`up:backend/app/services/clone_segment_video.py:402`；MVP 排除生成部分 |
| ComfyUI WebSocket | 从 COMFY_URL 推导 ws/wss `/ws?clientId=...`，可能嵌入 Basic Auth | 同上 | `up:backend/app/config.py:92`，`up:backend/app/services/comfy/api_comfy.py:57`；现有 queue_prompt 还从 ws URL 推导 HTTP 路径，未实测正确性 |
| yt-dlp 获取 | 页面探测与媒体下载，域名、CDN、重定向由 extractor 决定；可读取 Cookie 文件 | `/videos/douyin` 同步执行后投递任务 | `up:backend/app/services/douyin_parser.py:19`–`:65`；必须放独立受控 downloader，增加逐跳/DNS/IP/体积/超时校验 |
| videofetch / videodl | `VideoClient.parsefromurl`/download；配置多平台客户端 | 当前 fallback 被注释；模块仍无条件导入且为直接依赖 | `up:backend/app/services/douyin_parser.py:8`、`:68`–`:105`；排除许可受限依赖，不启用回退 |

`LLM_BASE_URL` 在源码与 env 示例中没有固定为火山地址，不能从 README 的模型举例推导实际主机。空配置存在由客户端默认端点/环境变量决定行为的风险，尚未进行 SDK 默认端点网络实测。阿里 ASR 三个配置项只有声明，未发现对应实现调用，**没有计作已使用的阿里 ASR API**（`up:backend/app/config.py:19`–`:21`）。

### 构建期、工具期与间接网络

| 类型 | 目标/依据 | 审计状态 |
|---|---|---|
| 容器基础镜像 | Docker Hub：python:3.12-slim、node:20、postgres:15、redis:7-alpine | 标签浮动；本次可见 digest 在 compose-up/image-digests 日志。Python digest 只见于 BuildKit 来源解析，未形成可运行镜像 |
| 系统包 | Aliyun Debian 镜像（Dockerfile 将 deb.debian.org URI 替换），apt 安装 FFmpeg 及依赖 | `up:backend/Dockerfile:6`；未锁包版本/校验清单，构建在这里超时 |
| Python 包 | Aliyun PyPI 镜像与包文件；本机审计安装使用 pip/uv 默认索引 | `up:backend/Dockerfile:12`、`:19`、`:25`；上游无完整 Python 锁文件 |
| Node 包 | npmmirror registry；package-lock 中的 resolved 分发源、SWC 等平台包 | `up:frontend/Dockerfile:6`、`up:frontend/package-lock.json`；上游 Docker 使用 npm install，本次用 ci 且禁安装脚本 |
| Next.js 遥测 | 已安装 next 14.2.30 的 `dist/telemetry/storage.js:225` 含 `https://telemetry.nextjs.org/api/v1/record` | 本机审计构建显式关闭；上游 Dockerfile 未关闭。不能把它误作模型 API |
| 可配置代理/SDK 可选追踪 | aiohttp `trust_env=True`、客户端代理/追踪环境变量与传递依赖 | `up:backend/app/services/comfy/api_comfy.py:34`；未捕获全量动态出站，传递依赖及可选追踪不能宣称已全部动态排除 |
| A00 调研 | GitHub/raw.githubusercontent.com、Hugging Face 元数据/模型卡、PyPI/files.pythonhosted.org | 仅公开源码/许可证/元数据；未下载权重或样本媒体 |

PostgreSQL、Redis 和前端到自有后端属于配置的内部服务连接；默认端口暴露仍是部署问题。完整运行时出站抓包、传递依赖 SBOM 和离线阻断尚未完成，这是不能将 A00 判 PASS 的原因之一。

## 4. 许可证、NOTICE 与模型权重

机器可读清单：[licenses.csv](licenses.csv)，共 **563 条审计条目**：上游/候选源码 11、候选权重 4、后端直接/开发依赖 39、前端 lock 包 501、实际容器对应源码 2、构建变体 3、回归模型产物 2、未解析的后端传递集合 1。它是带范围与缺口的清单，**不是全部产物已获分发许可的证明**。前端条目含不同平台可选包；2 个 lock 条目没有 license 字段。

### 关键许可结论

1. **parse_video 根源码 MIT**：`up:LICENSE:1`，版权声明为 2026 Zhitao Xiang。已读完整许可证；Git 全量跟踪路径中未发现 NOTICE。复制 substantial portions 时必须保留原版权与许可；根 MIT 不能代替第三方包、云服务或权重许可。
2. **videofetch 0.9.1 是 PolyForm-Noncommercial-1.0.0**：来自指定版本 PyPI 元数据，并核对 SHA-256 后读取其 wheel 内 LICENSE；wheel 实际导出 `videodl`，因此不是“引用了一个不存在的模块”。虽然下载 fallback 被注释，它仍是直接依赖且被导入。当前没有本项目商业使用授权证据，默认排除。[包证据](../../evidence/A00/extra-source-evidence.json)、[许可全文](../../evidence/A00/sources/pypi__videofetch__0.9.1/LICENSE)。
3. **Mutagen、psycopg2-binary、func_timeout 有独立 copyleft/例外条款**：准确版本的 PyPI 分别声明 GPL-2.0-or-later、LGPL with exceptions、LGPLv2。不能简单把整个依赖栈称 MIT，也不能仅凭类别断言一定与本产品不兼容；发布前按实际构建/链接/分发方式核对。证据：[后端元数据](../../evidence/A00/backend-dependency-metadata.json)。
4. **rea-video 声明 MIT，但授权文本与版权通知缺口仍在**：固定提交的 pyproject.toml:11 声明 MIT；完整未截断 Git 树未找到 LICENSE/LICENCE/NOTICE/COPYING 文件。不是“没有任何许可声明”，也没有批准直接复制源码或数据。证据：[补充审阅](../../evidence/A00/extra-source-evidence.json)。
5. **Redis server 与 redis Python client 要分开**：本次无网络容器版本探测得到 Redis server 7.4.10，其对应官方 LICENSE 是 RSALv2 OR SSPLv1；Python `redis==8.0.1` 元数据为 MIT。PostgreSQL 容器探测为 15.19，其代码使用 PostgreSQL License。两者的容器 OS/附带库没有完成整体 SBOM。证据：[Redis 版本](../../evidence/A00/redis-version.json)、[PostgreSQL 版本](../../evidence/A00/postgres-version.json)、sources 下对应固定源码许可。
6. **FFmpeg 按实际二进制配置判断**：官方源码说明默认 LGPL-2.1-or-later，启用 GPL 部件/库或 nonfree 选项会改变义务；不能将源码 HEAD 的许可直接贴到 apt 得到的二进制。本次后端镜像构建未完成，未取得 ffmpeg -L/-buildconf 与 codec 清单。[官方许可快照](../../evidence/A00/sources/FFmpeg__FFmpeg/LICENSE.md)。
7. **两个 TTS 时长回归 `.pkl` 不复用、不反序列化**：上游提交包含产物，预测代码用 joblib.load；没有单独训练来源和权重分发凭据。不能把根 MIT 视作已完成数据/产物来源审计。位置：`up:backend/app/services/predict/predict_voice_duration.py:102`，文件哈希在 static-inventory。
8. **responses-validator 0.3.0 仍是许可缺口**：指定版本元数据无许可，抽查的 macOS cp312 wheel 内也没有许可文件；不据此推断所有分发格式都没有许可。后端传递依赖闭包未安装完成，亦不能声称已全面核准。

### 候选源码锁定（仅调研快照，非已验证部署组合）

| 项目 | 固定 revision | 本次所见代码许可 |
|---|---|---|
| rea-video | `1c2a51471d9f454ea6e6c77fe161204317385b8c` | pyproject 声明 MIT；无独立许可文本 |
| Douyin_TikTok_Download_API | `5aa03528d2e974a0de23faf86597b5af3420df55` | Apache-2.0，根 NOTICE 已保存 |
| yt-dlp | `b3b18f8fc606e782ee7c82b0780a40c67b829072` | Unlicense；与上游固定 PyPI 2026.7.4 是不同标识 |
| FFmpeg | `39ccb3ca120c0815c62c7f145a1aa1354f335680` | LGPL/GPL 等，依构建而定 |
| PySceneDetect | `c5ce29c73751e77139e838bd9ce9ab66a8e71a23` | BSD-3-Clause |
| FunASR | `1125860d49a7c0c3ce3675f7641374b1d403070e` | MIT，仅工具代码 |
| PaddleOCR | `dab3fe35379033fdcb2d0e9572fac0b36c9a9ebf` | Apache-2.0，仅工具代码 |
| Qwen3-VL | `96588727e44c78b25ba03ea03b8e12f7e64fd0da` | Apache-2.0，仅仓库代码 |
| vLLM | `173d063acdb499ec2980b3d9561a6fbff0fd3701` | Apache-2.0 |
| 火山 SDK（出站辅助核查） | `5df619842a949fc59975cc22c84b482744280c27` | Apache-2.0，NOTICE 已保存；不是 pip 已完成安装的版本 |

来源 URL、原始许可全文和 SHA-256 均见 [sources/index.json](../../evidence/A00/sources/index.json) 与各目录 metadata。除了许可证之外，没有将这些项目代码批量复制到产品。

### 权重单独核查

| 候选模型 | 固定模型仓库 revision | 已确认 / 未确认 |
|---|---|---|
| Qwen/Qwen3-VL-8B-Instruct | `0c351dd01ed87e9c1b53cbc748cba10e6187ff3b` | 模型卡声明 Apache-2.0；未下载权重、未验证本地 hash、未推理 |
| funasr/paraformer-zh | `d7811ee3ac581fbcfdeb37c98c6ba674028433dc` | 模型卡声明 Apache-2.0；未验证时间戳能力/质量，未选齐 VAD、标点、对齐、说话人等辅助权重 |
| PaddlePaddle/PP-OCRv5_server_det | `ca867c897ecbca8873081573a802ad70d499cb94` | 模型卡声明 Apache-2.0；未运行 OCR |
| PaddlePaddle/PP-OCRv5_server_rec | `b26c3587fda8da3c8ec0ce357214b4d661ff1558` | 模型卡声明 Apache-2.0；未运行 OCR |

以上是权利主体模型仓库的明确声明，不是拿工具仓库许可证代替权重许可。这些快照没有单独 LICENSE 文件时，记录为 MODEL_CARD_DECLARATION；发布前仍需保存所用权重对应完整条款、清单、hash 与必要 NOTICE。没有评估 CUDA/驱动/vLLM/量化/帧数的可运行组合，不保证 24GB 显存可用。

## 5. 实际命令与结果

完整 argv、UTC 时间、耗时、原始退出码和脱敏 stdout/stderr 保存在每条 JSON。这里的 PASS 只覆盖该条命令，不扩大成产品验收。

| 检查 | 实际命令摘要 | 退出码与数量/结果 | 证据 |
|---|---|---|---|
| 固定版本/源码状态 | git checkout --detach SHA；git status --porcelain | 0；固定 SHA、工作树干净 | pinned-checkout.json、upstream-integrity-final.json |
| Docker Engine/Compose | docker version；docker compose version | 各 0；客户端与 daemon 可访问 | docker-version.json、compose-version.json |
| GPU | nvidia-smi；Windows GPU 枚举 | 127；仅枚举到 AMD 集显；本地 CUDA 模型验收 BLOCKED | gpu.json、hardware.json |
| 原始 Compose 配置 | docker compose -p video-analyzer-a00 config --quiet | 1；缺少 `.env`，这是未配置前置，非已证明的 Compose 语法缺陷 | compose-config-pristine.json |
| 准备后 Compose 配置 | 同上，增加临时无云凭据 .env 与端口 override | 0；6 服务配置可解析，非健康检查 | compose-config-prepared.json |
| 完整启动尝试 | docker compose ... up -d --build | 124；构建阶段超时，未运行应用验收 | compose-up.json |
| 后端 uv 安装 | uv pip install --python audit-venv upstream/backend | 1；`httpx2=2.7.0` 非合法依赖约束，uv 拒绝 dependency-groups | backend-install.json |
| 后端原始 pip 路径 | audit-venv/python -m pip install upstream/backend | 124；pip 可生成元数据，解析大量 SDK 子包时达到 180 秒上限；**不能将 uv 的拒绝推广为 pip 必然拒绝** | backend-pip-install.json |
| 上游 pytest | audit-venv/python -m pytest -q（backend 目录） | 4；通过 0 / 断言失败 0 / 跳过 0，加载错误 1：conftest 缺 httpx；未完成收集 | pytest-original.json |
| 前端依赖 | npm ci --ignore-scripts --no-audit --no-fund | 0；安装 469 包；平台可选包与 lock 条目数量不同 | npm-install.json |
| TypeScript | node node_modules/typescript/bin/tsc --noEmit | 0；类型检查通过，非测试用例 | frontend-typecheck.json |
| 前端生产构建 | npm run build（设置 API_PROXY_TARGET 与关闭遥测） | 0；7 个页面生成完成；不是浏览器 E2E 或 API 联通测试 | frontend-build.json |
| 上游 lint | npm run lint | 1；缺 ESLint 配置，进入配置问答并退出；构建日志中的 lint 阶段不能替代此门禁 | frontend-lint.json |
| 本地 URL 负例 | python scripts/audit/probe_url_validator.py | 1；7 项：通过 3 / 失败 4 / 跳过 0 | url-validator.json、url-validator-command.json |
| 静态清单 | python scripts/audit/scan_upstream.py | 0；176 文件、14 表、20 迁移；语法扫描无错误，但不代表导入或运行通过 | static-inventory.json、static-scan.json |
| 交付完整性 | python scripts/audit/validate_a00.py | 0；通过 19 / 失败 0 / 跳过 0，核对源码/许可哈希、引用、CSV、脱敏和真实退出码；仅交付校验 | deliverable-validation.json、deliverable-validation-command.json |
| 镜像版本探测 | docker run --rm --network none ... redis-server/postgres --version | 各 0；仅确认二进制版本，不启动数据服务 | redis-version.json、postgres-version.json |
| 镜像 digest 检查 | docker image inspect redis/postgres/node/python | 1；前三者有 digest，Python 来源镜像未留成本地可运行镜像 | image-digests.json |
| 清理 | docker compose ... ps --all；down --remove-orphans | 各 0；没有本项目业务容器；未删除用户其他项目或全局缓存 | compose-ps.json、compose-down.json |

证据根目录：[evidence/A00](../../evidence/A00/)，交付文件 SHA-256 清单见 [manifest.json](../../evidence/A00/manifest.json)。复现入口的默认只读模式已实跑，记录在 `evidence/A00/replay-20261104-123954/`；它保留 URL 缺陷退出码，不代表全部检查通过。虚拟环境初次没有 pip（pip-install.json），随后 ensurepip 成功（pip-bootstrap.json）；没有把该工具准备失败归咎于上游。pytest 是在完整依赖尚未安装时执行，缺 httpx 只证明本次环境无法加载，不能推出上游不存在该依赖（pyproject 明确列了 httpx）。

Compose 初次超时设置为 240 秒；旧探针只终止了 Windows docker 父进程，Compose 子进程继续持有输出管道。审计随后按精确 project/进程识别终止该子树，最终记录耗时 337.9 秒、退出 124。已修复记录器为超时终止所属进程树；没有把这次取消写成上游构建失败或成功。日志最后停在 apt 解包依赖，未达到应用安装/迁移/服务就绪；有界尝试不代表增加时间后一定不能启动。

### 上游测试可信度与未覆盖事项

- 静态发现 `backend/tests/` 下 36 个 test 函数（4 个 API 包装函数、32 个 service 函数）；44 是整个仓库的 test_* 函数数量，含手动脚本与业务辅助函数，**不是实际收集/执行数**。
- `tests/conftest.py` 的 db fixture 整段被注释，但 4 个 API 测试仍请求 db；pytest-asyncio 没有列入 dev 依赖；dev 约束还包含 `httpx2=2.7.0`。位置：`up:backend/tests/conftest.py:39`，`up:backend/tests/tests/api/router/test_auth.py:17`，`up:backend/pyproject.toml:53`–`:58`。这些是静态缺陷，不虚构后续错误日志。
- 上传 fixture 是伪造视频字符串，YAML 仍期望 200；实际上传已要求 ffprobe 验证，测试与实现不一致。位置：`up:backend/tests/commons/runner_utils.py:62`，`up:backend/tests/tests/api/router/video.yaml:2`，`up:backend/app/api/router/videos.py:83`。
- API YAML 包含在线平台链接，手动小说脚本也依赖本地个人文件/登录。没有授权或隔离条件时未执行这些网络/素材用例，也没有使用文档中“测试结果”作证据。
- 前端没有 test/E2E script；本次未做 Playwright、登录、资源隔离、上传到导出浏览器链路。位置：`up:frontend/package.json:5`–`:10`。

## 6. 主要缺陷与风险

| ID / 优先级 | 证据与触发条件 | 对本项目的影响 |
|---|---|---|
| F01 / P0 | URL 白名单用 `host.endswith(d)`，合成 `evildouyin.com` 被接受；8443 端口和 userinfo 也被接受。`up:backend/app/api/router/videos.py:40`–`:49`；URL 探针 3 项失败 | 未满足 SSRF 合同；DNS、IP、重定向也没有第一方逐跳校验。未对真实目标发起 SSRF 请求，不能声称已证明内网读取 |
| F02 / P0 | 音频上传云 ASR，帧进入远端 LLM；没有本地 ASR/OCR/VLM 独立适配合同。tasks:59–95、asr_service:23、visual_service:199 | 违背默认素材本地处理与无付费模型依赖；替换一个 base URL 不够 |
| F03 / P0 | 画面总结器打印 llm_kwargs，其中可包含 api_key；解析任务日志还打印 ASR、视觉、剧本内容。`up:backend/app/services/visual_service.py:105`，`up:backend/app/tasks/parse_video.py:82`、`:91`、`:96` | 若提供真实 Key/私有素材会产生日志泄漏风险；本次未输入这些数据 |
| F04 / P1 | 根迁移 pass 后修改不存在的 clone_images；前述迁移源码 | 干净部署缺少基础 schema；尚未动态执行迁移 |
| F05 / P1 | 无音轨仍先 extract_audio，ASR None 被记为 not find audio track 并失败。`up:backend/app/tasks/parse_video.py:59`–`:78` | 不符合无声视频正常处理；云服务故障也可能被误报为缺音轨 |
| F06 / P1 | LLM 被允许合并物理镜头；Float 单位混用；无稳定帧 timestamp_ms 证据字段 | 必须重建事实时间轴与新 Schema，不能无迁移沿用 |
| F07 / P1 | 视频切片按 mtime 倒序取出，与 scene_list 顺序按索引配对。`up:backend/app/services/video_processor.py:19`–`:28`、`:89`、`:129` | 切片与镜头可能错配；未以真实视频复现实测，不给切镜 F1 分数 |
| F08 / P1 | 上传写入中超限抛异常时 abs_file_path 仍为空；统一 except Exception 将 HTTPException 包成 400。`up:backend/app/api/router/videos.py:61`–`:114` | 可能遗留部分文件并改变 413 错误码；需边界测试。已有 UUID 文件名、流式体积与 ffprobe 校验可借鉴 |
| F09 / P1 | 下载与探测直接在 API 进程执行；FFmpeg/ffprobe 无 subprocess timeout；容器无 USER/资源限额/只读根配置。Dockerfile、videos:83/:122、video_processor:47–63 | 不符合媒体隔离及恶意输入资源边界。相关 subprocess 用 argv 列表，未发现这些调用拼接 shell 的证据，不臆报命令注入已利用 |
| F10 / P1 | untrusted ASR/视觉/分镜数据直接插入 SystemMessage。`up:backend/app/services/script_generator.py:337`–`:367`、`:431`–`:448` | 提示词注入边界不足；未做真实模型攻击测试，不宣称已越狱 |
| F11 / P1 | 一般下载器 URL/返回 URL 无统一字节上限，ASR requests 缺超时，只有轮询次数不等于单次 HTTP 超时 | 无有界执行与标准回退合同；asr_service:75/:98、douyin_parser:58、gen_image:252 |
| F12 / P1 | 无完整 Python 锁、浮动镜像、npm install、后端 Dockerfile:19 的 `|| true`；许可限制/未知项见 CSV | 构建与供应链结果不能稳定复现；不能复用整套依赖 |
| F13 / P2 | capabilities 在 PRODUCTION 下向 UI 返回不允许 local，但 generation_method 解析仍接受 local；当前代码没有在该解析函数强制生产只能云端。`up:backend/app/api/router/clone.py:201`；`up:backend/app/util.py:75` | 不将“生产 Docker 只能云端”的注释/README 当成后端强制策略证据；这是能力声明差异，未做动态 API 测试。单段详情路由位于 capabilities 之后，没有据此报告路由遮蔽漏洞 |

已有有利基础也要保留判断：有 JWT、密码哈希升级、父级归属校验、上传 UUID 与真实视频流校验；相关位置见 `up:backend/app/api/security.py:17`、`up:backend/app/api/deps.py:71`、`up:backend/app/services/ownership.py:24`、`up:backend/app/api/router/videos.py:67`。这些代码尚未通过本次集成验证，不能将“存在实现”写成“权限验收通过”。文件导出虽校验父级归属，仍未看到按真实数据根目录做 realpath/所有权联合约束（scripts.py:75、clone.py:247–340）。

## 7. 可借鉴与排除清单 / 本地化成本

| 范围 | 文件 | 处理建议 | 成本判断依据 |
|---|---|---|---|
| 技术拓扑 | docker-compose.yml、backend/app/database.py、celery_app.py | 借鉴分层思路，新建配置与独立 Worker | 现有只有一个 Worker、安全网络边界不足；不能原样继承 |
| 登录与归属 | backend/app/api/security.py、deps.py、services/ownership.py | 候选参考；若以后摘取代码，先独立测试并保留 MIT 通知 | 中等：依赖原有表与资源父链；新 Schema 需要新权限测试 |
| 媒体算法接线 | backend/app/services/video_processor.py | 参考 PySceneDetect/FFmpeg 调用方式，重建整数毫秒/VFR/证据/时限 | 高：不是增加一个函数即可满足 A03 |
| UI/导出 | frontend/src/components/video-studio/ParseVideoTab.tsx、DetailModal.tsx、frontend/src/lib/exportUtils.ts | 参考交互和可导出字段；当前不能直接作为 A07 时间轴工作台 | 中高：缺视频联动、版本编辑、证据与新 API |
| 解析任务/Schema | tasks/parse_video.py、models/script.py、script_generator.py | 重建目标合同和有检查点的流水线 | 高：主链路云端依赖、LLM 改镜头边界、生成业务耦合 |
| 生成与小说 | services/clone*.py、gen_voice.py、gen_image.py、comfy/、novel*.py、models/voice.py | MVP 排除；本次不删除上游文件 | 大部分是非目标自动成片/配音/小说功能，整仓 fork 会保留维护负担 |
| 依赖与产物 | videofetch/videodl、两个 .pkl、原有锁外依赖组合 | 不引入新底座 | 许可、来源、运行配置与测试可信度缺口 |

以上是以具体改动面为依据的相对成本判断，不是已测工时或报价。没有随意删除稳定代码；因为本地尚无业务代码，选择新底座不会迁移或覆盖用户现有产品数据。公开 API 目标、技术栈和需求编号继续沿用 PROJECT_SPEC。

## 8. 复现入口

Windows PowerShell，从仓库根目录开始；先审阅上游，不读取或使用其 AGENTS/CLAUDE 文件作为本项目指令：

```powershell
git clone --depth 1 https://github.com/XztCloud/parse_video.git .audit-cache/parse_video
git -C .audit-cache/parse_video fetch --depth 1 origin adc13afb47a112f0def0435231e691a5307e5b49
git -C .audit-cache/parse_video checkout --detach adc13afb47a112f0def0435231e691a5307e5b49
python scripts/audit/scan_upstream.py
python scripts/audit/probe_url_validator.py
python scripts/audit/collect_sources.py
python scripts/audit/collect_dependency_metadata.py
python scripts/audit/collect_extra_evidence.py
python scripts/audit/build_license_inventory.py
```

URL 探针目前**预期退出 1**，因为记录的是上游边界缺陷；不得修改断言把漏洞标绿。collect_sources 默认复用已保存的官方来源快照，不自动把 HEAD 漂移写回固定证据；这些 HEAD 是审计快照，不是 A01 部署锁。

运行基线的完整命令、无云凭据配置生成器与有界探针参见 [reproduce.ps1](../../scripts/audit/reproduce.ps1)。它只在空的新缓存目录使用；已有 .env 时拒绝覆盖；网络 API 测试、模型/权重下载与产品验收不在该脚本中。新执行证据放入独立子目录，避免覆盖本次历史记录。

## 9. 门槛与固定汇报

| A00 门槛 | 结果 |
|---|---|
| 上游与候选源码、模型卡固定 revision | 已取得；不是部署组合兼容性验证 |
| LICENSE/NOTICE/模型许可与已知限制逐项列出 | 已交付；未解析依赖/二进制/辅助权重仍有明确 UNKNOWN/BLOCKED |
| 原始启动/测试可复现或精确说明阻塞 | 已尝试并记录具体结果；完整运行 BLOCKED |
| 无未识别外部依赖 | **未达到**：第一方调用已分类，后端传递闭包与动态出站未完成验证 |
| ADR Go/No-Go 人类审阅通过 | **BLOCKED，待审阅**；本次没有自行代签 |

```text
任务 ID：A00
范围与设计：固定提交的源码/许可/出站/测试审计；建议轻量新底座。
变更文件：三份主交付物，A00-plan、审计/复现/交付校验脚本、脱敏 evidence、.gitignore。
测试命令、退出码、通过/失败/跳过数量：URL 探针 exit 1，3/4/0；原始 pytest exit 4，0/0/0，加载错误 1；前端类型/构建 exit 0；lint exit 1；Compose 启动及 pip 安装 exit 124。完整表见第 5 节。
真实验收证据路径（脱敏）：evidence/A00/；无真实模型/平台/离线链路 PASS。
已知缺陷、性能约束、未测事项：许可限制、SSRF 边界、缺初始 schema、云模型耦合、依赖/测试阻塞；无 NVIDIA GPU、授权样本和权重；未做运行时出站捕获、迁移恢复或产品性能评测。
结论：BLOCKED（审计文件已交付；动态基线和人类 Go/No-Go 未通过，不等于文档未编写）。
下一任务建议：先审阅 ADR-001；接受轻量底座后，仅执行 A01，先解决版本/许可、空库迁移、服务/模型隔离与环境自检。
```
