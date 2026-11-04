# A01 本地基础设施验收

日期：2026-11-04（Asia/Shanghai）。范围：新建轻量底座的 CPU 基础设施，不包括 A02–A09。授权与决策见 [ADR-002](../decisions/ADR-002-A01-foundation-acceptance.md)，实现前计划与负例见 [A01 计划](../plans/A01.md)。A00 历史证据未重写。

## 实现与环境

已实现六个 Compose 服务：Next.js 前端、FastAPI、Celery Worker、Alembic 一次性迁移、PostgreSQL、Redis。新增 live/ready、受控本地凭据初始化、三个持久卷、依赖/镜像锁、GPU 诊断 overlay、跨平台 doctor 和真实基础设施验收脚本。未继承上游业务代码、依赖链或迁移。

实际环境：Windows 11 / Docker Desktop Linux amd64 容器，Engine 29.9.1、Compose 5.6.0；AMD Ryzen AI 9 365，10 核/20 线程，31,989,297,152 字节内存；AMD Radeon 880M。容器内 Python 3.12.13、Node 22.23.1、PostgreSQL 17.11、Redis server 7.2.13。运行内核 `6.18.33.1-microsoft-standard-WSL2`。证据：hardware-final、versions、node-runtime、database-version、redis-version、images JSON。

Python 锁含 53 个第三方包（运行/开发/条件平台并集，不含本项目），npm 锁含 388 个包条目（不等于当前平台安装数）；另有 Redis/Postgres 两行，总许可清单 443 行，UNKNOWN 0。保留 65 个许可/通知文件。清单不是完整容器 OS SBOM，分发许可边界见 [A01-dependencies](A01-dependencies.md)。

## 测试命令与结果

所有证据位于 [evidence/A01](../../evidence/A01/)，命令 JSON 记录 UTC 时间、参数、退出码、耗时和脱敏输出。

| 命令（仓库根目录，注明的除外） | exit | 通过/失败/跳过 | 证据 |
|---|---:|---|---|
| `cd backend; uv run --frozen pytest -q` | 0 | **21/0/0**；1 条 Starlette 对 httpx 测试客户端的弃用警告 | python-tests-post-recovery.json |
| `cd backend; uv run --frozen mypy` | 0 | 10 个源文件通过，非测试数量 | mypy-final.json |
| `uv run --project backend --frozen ruff check --config backend/pyproject.toml backend/app backend/migrations backend/tests scripts/doctor.py scripts/init_local.py scripts/acceptance_a01.py scripts/collect_a01_dependencies.py` | 0 | 静态检查通过 | ruff-post-recovery.json |
| `uv lock --project backend --check --offline` | 0 | 锁与清单一致 | locks-check.json |
| `cd frontend; npm run lint` | 0 | 0 errors / 0 warnings | frontend-lint-final.json |
| `cd frontend; npm run typecheck` | 0 | TypeScript 通过 | frontend-typecheck.json |
| `cd frontend; npm run build` | 0 | 生产构建通过（4 routes） | frontend-build.json；最终 Linux 构建另见 compose-build-final.json |
| `docker compose --progress plain build api frontend`；健康检查修复后 `... build api` | 0 | Linux 镜像构建通过 | compose-build-final.json、compose-build-recovery.json |
| `docker compose up -d --wait --wait-timeout 120` | 0 | migrate exit 0；5 个长期服务 healthy | compose-up-recovery.json、compose-status.json |
| `python scripts/acceptance_a01.py` | 0 | **25/0/0，真实基础设施检查** | acceptance.json、infrastructure-tests-final.json |
| `python scripts/doctor.py --services` | 0 | 7 项 PASS，GPU 另列 BLOCKED | doctor-services.json |
| `bash scripts/doctor.sh`（Git Bash） | 0 | Bash 入口可运行；没有当成 Ubuntu 证据 | doctor-bash.json |
| `python scripts/doctor.py --require-gpu` | 2（符合负例预期） | GPU BLOCKED；CPU base PASS | doctor-gpu-required.json |
| `docker compose -f compose.yaml -f compose.gpu.yaml --profile gpu-check run --rm gpu-check` | 1 | NVIDIA runtime：WSL 未找到适配器；未执行模型 | gpu-container.json |
| 停止 Worker 后 `doctor.py --services` / `app.infra_probe queue` | 1 / 1（符合负例预期） | Worker 不健康、真实队列有界超时；API/前端仍存活，随后恢复 Worker | doctor-worker-stopped.json、worker-queue-timeout.json、worker-start.json |
| 内部独立进程给 DB/Redis 注入错误的临时密码，再调用实际依赖检查 | 0 | 两项依赖均被判为 false，响应/日志未输出密码；不修改运行服务凭据 | invalid-credentials.json |

25 个真实检查覆盖：未设置云模型 Key 的基础就绪、私有数据端口、前端 HTTP/live/proxy、真实 Celery 往返、独立临时库空库迁移/重复升级/降级/重升、重建全部容器后 installation ID/Redis marker/工作文件不变、Postgres/Redis 停止时 live 200 与 ready/proxy 503、恢复后可用及队列再往返、API 停止时前端仍存活且 proxy 503、非 root API、日志无本地密码。测试结束恢复服务、删除探针和临时数据库，不删除任何持久卷。

## 实际发现与修复

1. 首次启动：YAML flow list 将未加引号的 tmpfs 逗号拆成两个元素，Docker 报 `invalid mount path: 'mode=1777'`。已将完整挂载字符串加引号，并增加配置合同测试。GPU query 中含逗号的参数同样加引号，合同检查参数数量。
2. 六个服务 healthy 并不代表主机可访问。Engine 29 上只接 internal 网络时 HostConfig 存在端口请求，但 NetworkSettings 没有实际发布，真实 HTTP 失败。已增加 ingress bridge，仅连接 API/前端，前端不接数据网络；重新用主机 HTTP 验证。
3. 第一次完整故障测试为 **17 PASS / 1 FAIL（TimeoutError）**，保留在 acceptance-redis-timeout.json / infrastructure-tests.json。确认 redis Python 8.1.0 默认 retry count 为 10；socket timeout 不等于总时限。健康检查显式设置 `Retry(NoBackoff(), 0)`，重建后全量 25 项通过。没有通过提高测试超时掩盖故障。
4. 首次 lint 的 Next Link 错误、MyPy 六处类型错误、Ruff 导入问题已修复，原始失败 JSON 保留。最初 Windows 相对 Python 可执行路径调用失败为 exit 127，改用 `uv run --frozen`；不将其伪装成测试断言失败。

## 风险、限制与未测项

- **A01 CPU 基础设施在本环境 PASS；Ubuntu 原生正式部署未测**。没有声称可在所有新环境一键运行。
- 当前 AMD 环境没有 NVIDIA GPU/推理证据，GPU 诊断为 BLOCKED。真实模型、CUDA/vLLM 兼容组合、权重 hash、离线视频全链路归 A05/A09，不是本阶段 PASS 的组成部分。
- 前端只做状态页及 HTTP/proxy 检查，未做浏览器视觉与交互 E2E；视频工作台、认证、上传、模型、时间轴和脚本尚未实现。
- Postgres 运行角色仍是本实例 owner，最小权限业务角色、备份恢复演练、最终防火墙/抓包与深入安全测试留给 A08。API/前端 ingress 并非外网阻断网络；不宣称系统已经离线验收。
- 容器级 OS SBOM/漏洞与发布通知复核尚未执行；没有发布镜像或产品版本。Redis 7.2 分支需跟进维护/安全补丁，不能因 BSD 许可而忽视更新。
- 当前没有媒体/模型性能结论；512MB 应用内存、单核、Worker 并发 1 只是基础设施配置，不是视频吞吐量证明。

## 固定汇报

```text
任务 ID：A01
范围与设计：轻量底座；六服务、初始迁移、live/ready、命名卷、secret、依赖/镜像锁、doctor 与可选 GPU 诊断。
变更文件：compose*.yaml、backend/、frontend/、infra/、scripts/、README、A01 计划/验收/依赖清单、ADR-002、evidence/A01、Git 忽略/换行规则。
测试命令、退出码、通过/失败/跳过数量：pytest 21/0/0 exit 0；真实 Compose 检查 25/0/0 exit 0；Ruff/MyPy/TS/ESLint/build/doctor exit 0；严格 GPU 检查 exit 2，容器 GPU exit 1（均记录硬件阻塞，非推理 PASS）。
真实验收证据路径（脱敏）：evidence/A01/acceptance.json、命令 JSON、openapi.json、manifest.json；无私有素材/权重/密码。
已知缺陷、性能约束、未测事项：Ubuntu 原生部署、GPU/模型、浏览器交互、A02–A09 业务、安全/备份与完整 OS SBOM 未验收；仅本机开放。
结论：PASS（本机 Linux 容器的 A01 CPU 基础设施）；GPU 诊断 BLOCKED，Ubuntu 正式部署未测。
下一任务建议：A02 视频采集与平台适配；先定义鉴权/资源归属、上传合同与 SSRF/失败回退用例，另获授权后开始。
```
