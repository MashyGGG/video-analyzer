# A01 基础设施运行手册

## 启停与排障

先运行 `python3 scripts/init_local.py`，再 `docker compose up -d --build --wait --wait-timeout 180`。首次下载/构建依赖网络，后续基础服务运行不调用第三方模型。检查 `docker compose ps --all`：migrate 应退出 0，其余服务 healthy。

- live 200、ready 503：查看数据库、Redis、migrate；HTTP 不返回底层连接异常和凭据。模型未配置不会造成此错误。
- migrate 非零：检查本地 secret 与卷是否匹配，再查看 migrate 日志。禁止用 stamp/head、手工建表或 `create_all` 掩盖迁移失败。
- 页面可打开但部分状态不可用：检查 API ready 与前端 `/api/health`；停止 API 时前端自身 live 仍可用。
- 只有内部端口、主机无法访问：Engine 29 对仅内部网络的发布端口未实际映射。本项目将 API/前端接入 ingress bridge；不要为了修复网页而将数据库/Worker 接入公网网络。以真实 HTTP 和 `docker port` 验证，不只看 Compose config。
- 端口占用：在 `.env` 修改 VA_WEB_PORT / VA_API_PORT，doctor/验收脚本使用对应的 `--web-port` / `--api-port`。

API/前端 ingress 具有普通 bridge 出站能力，本阶段没有声称它们被防火墙阻断外网；应用不配置模型 URL/Key。backend 网络的 Worker/数据层保持 internal。A08/A09 必须对最终模型/媒体容器另做网络和抓包验证。

## 迁移与恢复

仅首次空库创建 installation 表和 Alembic 版本。幂等升级不会重置 installation ID。不要对正在使用的数据库执行初始版本 downgrade，它会删除 installation 标识。验收脚本只在独立随机命名数据库验证 downgrade/upgrade，finally 清除临时数据库。

升级前在 Bash 下备份（PowerShell 重定向二进制在不同版本可能改变内容，可使用 Docker cp 搬运容器内 dump）：

```bash
mkdir -p .audit-cache/backups
docker compose exec -T postgres pg_dump -U video_analyzer -d video_analyzer -Fc > .audit-cache/backups/before-upgrade.dump
docker compose run --rm migrate
docker compose up -d --wait
```

数据库备份含项目数据，不能提交；`.secrets` 另作私密备份。停止写入服务后才能做一致恢复。恢复前确认目标实例、备份完整性、对应凭据；本阶段不提供会自动覆盖现存库的恢复脚本。完整备份恢复演练由 A08 执行。

`docker compose down` 保留卷；日常不执行 `down -v`。若本地 secret 丢失，恢复原文件；不通过重建凭据尝试连接旧卷。密码轮换需同步修改数据库/Redis 和受控 secret，不属于初始化脚本职责。

## 锁更新

Python：修改明确版本，`uv lock --project backend`，然后 `uv export --frozen --no-dev --no-emit-project --project backend --output-file backend/requirements.lock`；必须同时评审两个锁。Node：修改精确版本、更新 package-lock，之后 `npm ci`、lint/typecheck/build。不要在启动脚本调用 install。

镜像 digest 来自官方 Docker Hub，多架构索引固定；本次只验证 linux/amd64。依赖更新同时更新 A01 许可清单，检查安全公告与新出站行为。Redis server 7.2.13 采用 BSD-3-Clause，不继承 A00 审计的 7.4 RSAL/SSPL 镜像；其维护/安全补丁需持续跟进。

## 权限与日志

应用/Worker UID 10001、只读根目录、cap_drop ALL；Redis 为 redis 用户；Postgres 使用官方 entrypoint 初始化目录后降权到 postgres，不把初始化 root 阶段当成全程非 root。运行时数据库角色目前是本实例 owner，尚未拆分最小权限业务角色，A08 再收紧。默认仅本机使用。

Docker json-file 限制每服务 3×10MB。健康错误只输出依赖名称；不记录密码、模型 Key 或素材。首次构建日志会包含公开依赖 URL，但不使用私有 registry 凭据。若配置私有仓库需使用构建 secret，不把 token 写进 Dockerfile、锁文件或 evidence。
