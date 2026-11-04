# Video Analyzer

本地视频拆解与复刻系统。目前完成 A00 审计与 A01 基础设施；**尚未实现上传、下载、视频分析或脚本生成**。完整需求见 [PROJECT_SPEC](docs/PROJECT_SPEC.md)，底座决策见 [ADR-002](docs/decisions/ADR-002-A01-foundation-acceptance.md)。不使用 Vercel 或第三方付费模型 API。

## 启动

需要 Docker Engine + Compose v2.30+（建议当前受支持版本）、Python 3.12+；首次构建需要访问 Docker Hub、PyPI、npm。推荐 Ubuntu；开发验证环境为 Windows 11 + Docker Desktop 的 Linux 容器。CPU 基础服务不需要 NVIDIA GPU。

```bash
python3 scripts/init_local.py
docker compose up -d --build --wait --wait-timeout 180
python3 scripts/doctor.py --services
```

PowerShell 使用 `python` 替换 `python3`；无需修改命令中的 Compose 参数。Bash 也可运行 `bash scripts/doctor.sh --services`。可选复制 `.env.example` 为 `.env` 修改端口，默认无须创建 `.env`。不要将 .env/密钥/素材放进 Git。

- 页面：<http://127.0.0.1:3000>
- OpenAPI：<http://127.0.0.1:8000/docs>
- 存活：`GET /api/v1/health/live`，独立于数据层。
- 就绪：`GET /api/v1/health/ready`，真实检查 PostgreSQL、迁移版本和 Redis。就绪为 200，不就绪为 503；`models: not_configured` 不影响 A01。
- Worker：Compose healthcheck 用真实 Celery inspect ping；页面的 Redis 卡片只表示 Redis 连接，不代表 Worker 或模型验收通过。

所有发布端口仅绑定本机。Postgres/Redis/Worker 不发布端口；前端仅连接 ingress 网络，不能直接连接内部数据层。API 连接 ingress 与内部 backend 网络，Worker/数据层仅内部网络。当前尚未提供业务认证，不要通过反向代理或修改监听地址将其公开给其他用户。正式模型与离线网络验收属于 A05/A09。

## 数据与凭据

初始化生成两个随机密码文件，放在被忽略的 `.secrets/`。再次执行会校验并保留原值；部分缺失或无效时拒绝隐式轮换。**已有数据卷时不能删除密码重新生成**，应从受控备份恢复匹配凭据。

Linux 下目录权限为 0700，内部文件为 0444：Compose 文件 secret 使用 bind mount，非 root 容器必须可读文件；目录权限阻止其他普通主机用户遍历。Windows 请将目录 ACL 限制到本人、SYSTEM、管理员；本机验证已具备此限制。Compose secrets 不是主机磁盘加密，备份应受控。

命名卷 `postgres_data`、`redis_data`、`work_data` 分别持久化数据库、队列与 `/data`。`docker compose down` 保留数据；`docker compose down -v` 会永久删除卷，日常停机不要加 `-v`。

```bash
docker compose ps --all
docker compose logs --tail 100 api worker migrate
docker compose stop
docker compose start
```

迁移服务成功后 API/Worker 才启动。正常升级：先按 [迁移运行手册](docs/runbooks/A01-infrastructure.md)备份，再运行 `docker compose run --rm migrate`。初始迁移创建 installation 标识，不创建后续业务表，不调用 `create_all`。

## 开发与验证

Python 锁文件为 `backend/uv.lock`；Docker 使用对应的、带哈希的 `requirements.lock`，不在容器启动时安装依赖。Node 使用 `package-lock.json` 和 `npm ci`。基础镜像固定版本与 digest；锁和许可记录见 [A01 依赖说明](docs/audit/A01-dependencies.md)。

```bash
uv sync --project backend --frozen
cd backend
uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen mypy
cd ../frontend
npm ci --ignore-scripts --no-audit --no-fund
npm run lint
npm run typecheck
npm run build
```

前端每次更新都必须补充/调整对应的成功与失败用例，并执行以下统一门禁；具体要求已写入 AGENTS.md：

```bash
cd frontend
npx playwright install chromium
npm run verify
cd ..
python3 scripts/verify_a01_e2e.py
```

`verify` 顺序执行 lint、TypeScript、生产构建、Chromium 桌面/移动视口 E2E 和 Next 健康代理合同测试。使用独立的 17800/17801 端口，并拒绝复用未知服务。Ubuntu 首次安装浏览器可用 `npx playwright install --with-deps chromium`。测试输出位于被忽略的 `.artifacts/playwright/`，HTML 报告可用 `npx playwright show-report ../.artifacts/playwright/functional-report`（frontend 目录）。失败保留截图与 trace；重跑会替换原始报告，重要失败请先保存并脱敏。

`verify_a01_e2e.py` 创建独立 `video-analyzer-e2e` Compose 项目，使用 17810/17811 端口、独立命名卷，执行原有 25 项基础设施验收和真实浏览器故障恢复测试。会停止本次测试实例的服务；不会停止日常 3000/8000 实例。结束后清理测试容器/网络，保留卷；逐次证据保存在 `evidence/A01-e2e/runs/<UTC时间>/`，已有项目容器时拒绝抢占。证据/截图要在提交前检查，不提交 Cookie、客户素材或模型权重。

GitHub Actions 的 `Frontend and A01 E2E` 在 push/PR 时运行相同门禁。未配置远端分支保护时，workflow 本身不能阻止有直接写权限的人跳过本地测试；应将 `frontend-e2e` 设置为 required check。CI 是否实际通过以对应 run 为准。场景覆盖及本次复验集中记录在 [A01 E2E 验收报告](docs/audit/A01-e2e-acceptance.md)，不宣称 100% 代码行覆盖率或真实模型通过。

原始基础设施验收也保留兼容入口（会短暂停止和重建所选项目容器；仅在独立开发/验收实例执行）：

```bash
python3 scripts/acceptance_a01.py
```

可使用 `--compose-project <项目名> --api-port <端口> --web-port <端口> --output-dir <新证据目录>` 避免覆盖历史记录。日常复验优先使用上面的隔离脚本。

脚本验证真实 Celery 往返、单独临时数据库中的迁移降级/重放、重建后的三类持久化、数据层断开后的 503 与恢复。不会删除持久卷；只删除本次生成的探针和 `a01_accept_<随机 UUID>` 临时数据库。报告写入 `evidence/A01/acceptance.json`。不能把这些基础设施结果当成视频/模型验收。

## GPU 诊断

```bash
python3 scripts/doctor.py --require-gpu
docker compose -f compose.yaml -f compose.gpu.yaml --profile gpu-check run --rm gpu-check
```

严格 doctor 缺 GPU 返回 2，容器诊断缺驱动/硬件返回非零。overlay 只运行 NVIDIA 硬件查询，A01 没有伪造 vLLM 服务或自动下载权重；A05 再锁定并验证模型、CUDA、vLLM 组合。当前 AMD 开发机 GPU 验证为 BLOCKED，CPU 基础设施单独判定。

## 阶段记录

[A00 基线](docs/audit/baseline.md)保留原始审计状态；后续 Go 决策另存 ADR-002，不改写历史证据。[A01 计划](docs/plans/A01.md)在实现前写入，[A01 验收](docs/audit/A01-acceptance.md)记录实际结果和限制。下一任务为 A02，需单独授权开始。
