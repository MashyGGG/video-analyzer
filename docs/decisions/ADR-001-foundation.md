# ADR-001 Video-analyzer 基础工程选择

日期：2026-11-04。任务：A00。状态：**Proposed / 待人类审阅**。不是已批准的产品架构变更，不构成进入 A01 的验收签字。

## 决策

**建议自建轻量底座，不把 `parse_video` 整仓 fork 为产品基础。** 保持 PROJECT_SPEC 规定的 Next.js + FastAPI + PostgreSQL + Redis/Celery、FFmpeg/PySceneDetect、FunASR、PaddleOCR、Qwen3-VL/vLLM 技术路线与公开 API 目标。上游作为带固定版本的参考，不默认继承其业务表、迁移、依赖、Prompt、生成流水线或模型产物。

审计版本为 `XztCloud/parse_video@adc13afb47a112f0def0435231e691a5307e5b49`。事实、源码行号、563 条许可条目和执行日志见 [baseline.md](../audit/baseline.md)、[licenses.csv](../audit/licenses.csv)、[evidence/A00](../../evidence/A00/)。本 ADR 对收益/成本的判断是工程推断，未把 README 或 mock 当成运行证明。

## 背景与判定依据

本项目优先交付可追溯的原片镜头分析和可编辑实拍脚本，要求没有第三方付费模型依赖。`parse_video` 同时面向小说、TTS、图像/视频生成与自动成片，关键解析路径依赖云 ASR 与远端 LLM。直接 fork 虽能获得界面和用户体系，却不能直接获得目标的数据与安全合同。

| 决策维度 | 直接 fork 的实际情况 | 轻量底座的代价与收益 |
|---|---|---|
| 已验证资产 | 前端 npm ci、TypeScript 和生产构建通过；JWT/归属/上传验证有实现 | 需重建基础服务和认证，不能声称免费获得成熟后端；可明确保留已理解的交互思路 |
| 纯本地分析 | parse_video.py:59–95 调用云 ASR/视觉；llm.py:11 在 import 时初始化模型；没有 OCR 目标适配 | 从第一天定义本地模型 adapter，控制启动与外部依赖边界 |
| 时间轴合同 | Float 时间，阶段间秒/毫秒语义不同；LLM 可以合并镜头 | 独立物理镜头/语义段落，统一整数毫秒与证据引用；避免迁移一套不适配的核心模型 |
| 任务与隔离 | 下载/探测在 API；单一 Celery worker 耦合分析和成片 | 需实现 download/media/analyze 分工，但不会同时拆掉不需要的生成体系 |
| 许可证 | 根 MIT 可参考；videofetch 0.9.1 非商业限制；其他 copyleft、二进制与传递项有单独条件 | 自选必要依赖和明确版本，排除 videofetch、TTS 回归 pkl 与非目标云模块 |
| 基础部署 | 完整启动未完成；初始迁移空、后继直接改已有表；Python 无完整锁，uv 拒绝 dev 约束 | 新建可重放的初始 schema 和锁文件；不用 stamp/head 或 create_all 掩盖迁移缺失 |
| 回归可信度 | pytest 未完成加载；db fixture 注释、假视频期望成功、缺 lint 配置 | 从合同和失败用例建立可运行测试；额外成本存在，但无法依赖上游绿灯抵消 |
| 安全与证据 | URL 探针 3 过/4 失败；潜在 Key/内容日志泄漏；无目标证据/版本实体 | 按本项目信任边界新建，减少继承路径的修复与复测面 |

上游的 UI 和部分权限实现值得参考；决定不 fork 的原因是**需要替换的恰好是核心流水线、时间轴/版本 Schema 和部署合同**，且没有可运行的后端回归基线证明保留其余部分能降低风险。这不是对整个上游项目的通用质量评价。

## 考虑过的方案

### 方案一：整仓 fork 后本地化

优点是已有登录、列表、分镜报告、导出和编排代码，前端构建实际通过。需要处理：初始迁移、版本锁与测试；替换 ASR/视觉/叙事；新增 OCR 和帧证据；调整时间单位和分析版本；拆 downloader/media/analyze；移除非目标生成、小说、TTS 和受限依赖；重新验证全部权限与导出路径。

不选择此方案作为当前建议。不能以“配置一个本地 LLM URL”概括上述改动，也不能因暂时网络/构建超时就断言上游永远无法启动。

### 方案二：轻量工程，按任务卡增量实现（建议）

按 PROJECT_SPEC 定义模块和 API，从 A01 最小服务开始，只引入完成当前任务所需依赖。初期工作量包括认证/迁移/任务/存储骨架，接受这些明确成本，以减少继承非目标代码、许可风险和不匹配数据合同的长期维护。

### 方案三：直接复用 rea-video

不作为可用替代底座。它在固定 revision 的 pyproject 声明 MIT，但没有独立许可证/版权通知文本；本次未验证其部署、API、任务、权限或模型本地化。仅借鉴分析维度与报告思路，不复制代码、Prompt 数据集或示例素材。

## 模块与依赖处理

| 范围 | 决定 |
|---|---|
| 参考文件 | `backend/app/api/security.py`、`api/deps.py`、`services/ownership.py`；`services/video_processor.py`；前端 ParseVideoTab/DetailModal/exportUtils。仅参考，尚未选取复制任何业务代码；若未来复制，保留 MIT 版权/许可并加独立测试 |
| 不继承 | 原始 models/script 的时间合同、20 条迁移链、tasks/parse_video 编排、LLM 直接融合事实与推测的 Prompt |
| MVP 排除 | clone 自动成片、gen_voice/gen_image/comfy、小说转换、TTS 时长回归权重、RunningHub 与字节云服务调用 |
| 下载候选 | yt-dlp；Douyin 下载器作为可选独立服务，不默认为成功支持。仅授权、无绕过平台访问控制，受限时回退上传 |
| ASR/OCR/VLM | FunASR、PaddleOCR、Qwen3-VL/vLLM；代码与权重许可分别管理。A00 只锁定审计快照；辅助模型、运行版本、digest、显存和 hash 在相应任务选择与验证 |
| Redis/FFmpeg | 必须核查实际 server/二进制版本与许可；不把 redis Python 库的 MIT 当 Redis server 授权，也不把 FFmpeg 源码默认许可当实际 codec 构建许可 |

## 对接口、数据与迁移的影响

本地没有现存业务数据库和已发布 API，当前选择不会删除用户数据，也没有可执行的用户数据库迁移。本项目新实现以 `docs/PROJECT_SPEC.md` 的 `/api/v1` 目标为起点，最终以 OpenAPI/Pydantic 固定版本为事实来源，不能拿上游相同前缀当兼容承诺。

若未来需要导入 `parse_video` 数据，必须另写导入 ADR：逐字段确认时间单位、映射旧 ID、保留原始内容与来源、转为整数毫秒、验证证据引用、记录 Schema 版本、备份原库并在新库试跑。没有可验证原始帧/时间戳的数据不得补造 observed；不直接连接旧生产库，也不自动运行旧迁移链。

## A01–A03 最小推进计划（尚未实现）

| 任务 | 最小范围 | 首先写出的失败用例与门槛 |
|---|---|---|
| A01 本地基础设施 | 前端/FastAPI/PostgreSQL/Redis/Celery；分区网络与持久卷；初始迁移、health/readiness、doctor；Python/Node/镜像固定版本；无 Key 也能启动基础服务 | 空库 upgrade/downgrade/恢复；Redis/DB 不可达；模型未就绪仍区分基础服务状态；重启后数据保留；端口仅本机/内网；记录 Redis 许可选项。mock 仅开发模式 |
| A02 媒体获取 | 上传与 SourceAdapter；share-text 先提 URL；平台能力状态；独立联网 downloader；明确错误码/上传回退 | 相似域名、userinfo、异常端口、私网/metadata/DNS/重定向、超大/损坏媒体、超时/限流/无权；没真实授权样例的平台标 BLOCKED/实验性，不承诺已支持 |
| A03 媒体事实时间轴 | ffprobe、VFR/旋转/音轨信息；PySceneDetect；PTS/整数毫秒、代表帧、校验和；保留物理镜头及语义分段边界 | 无声/单镜/VFR/旋转/闪白/短镜/损坏流、FFmpeg 超时与磁盘不足；原片关键帧可追溯；合成精确测试与授权留出集分开，不用 LLM 改切点 |

一次只做一张任务卡。A01 的具体设计与失败用例仍需在执行该卡之前编写，不能把本表视为已经完成计划审批、实现或验收。

## 风险与重新评估条件

- 新底座需要重建认证、任务、文件服务和 UI，不能假定比复用有固定工期优势；本次没有虚构工时估计。
- A00 的 pip 安装/Compose 构建有界尝试超时，不是上游永久不可运行的证明；若后续取得可重放的干净部署、完整测试和可控本地化分支，可提出新 ADR 重新评估。
- 若提取上游代码，需逐文件记录来源、通知、依赖及测试；参考库不等于已批准的资产库。
- 当前 AMD 主机没有本地 NVIDIA 推理证据，Qwen/vLLM、离线模型及平台实测均 BLOCKED。可先开发确定性组件，但不能用 mock 补签真实验收。

## 审阅与阶段结论

| 项目 | 状态 |
|---|---|
| 审计与决策建议文档 | 已交付 |
| 建议 | No-Go：直接复用整仓；Go（建议）：轻量底座 |
| 完整 A00 | BLOCKED：动态后端基线、完整外部传递依赖核查及人类审阅未通过 |
| 决策审批人 / 日期 | 待填写 / 待填写 |
| 是否自动进入 A01 | 否；本次仅完成 A00 授权范围 |

人类审阅是 PROJECT_SPEC 第 11 章 A00 的明确门槛“人类审阅通过 Go/No-Go 决策”，不是 Agent 自行增加的确认环节；本文件已准备为可直接审阅的具体结果。
