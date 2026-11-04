# A01 依赖与许可边界

本阶段未复制上游业务代码，也未安装 parse_video、videofetch、TTS、RunningHub、LLM/ASR/OCR SDK 或权重。`backend/uv.lock`、哈希导出 `backend/requirements.lock` 和 `frontend/package-lock.json` 是新底座版本来源；[A01-licenses.csv](A01-licenses.csv) 单独登记，不替换 A00 清单。

Python/Node 直接与传递包的授权来自已安装同版本 METADATA/许可文件或 npm 锁的 license 字段，文本副本及 SHA 在 `evidence/A01/licenses/`、`license-notices.json`。Python 清单覆盖锁中的开发及条件平台包；安装/许可文本采集主机为 Windows；Linux 运行镜像的实际包列表另存运行证据。npm 包含开发与可选平台项，数量不同于当前平台实际安装数量。registry-selection.json 是选择时的官方 registry 元数据快照，最终部署版本只以锁为准。

主要许可条件：FastAPI/SQLAlchemy/Pydantic/Next/React/redis Python 客户端为 MIT；Celery/Uvicorn 为 BSD；TypeScript 为 Apache-2.0。psycopg/psycopg-binary 为 LGPL-3.0-only：保留安装包自带许可、通知及重新链接/替换条件，不宣称镜像全部为 MIT；不修改这些库。本项目后续若分发镜像，需随包提供所需通知和相应源代码/提供方式。certifi 的证书包授权及其他传递条件保留在清单与原始 notices。

Redis **server** 明确选择 7.2.13，其官方 tag COPYING 为 BSD-3-Clause，固定 sha256 `9907ac0c435717b4d95697cb4d0ce77d100b1d21269a01a0ce66f27335184c38`；与 A00 的 7.4.10 RSALv2/SSPLv1 不同。PostgreSQL 17.11 使用 PostgreSQL license，digest `266d3c257594e195b309ae9d1805e54c788f1d7b375f56bf6c367aac6c917e7b`。源码文本副本来自官方固定 tag，服务实际版本由容器命令记录。

Python 3.12.13 / Node 22.23.1 官方基础镜像分别使用 PSF/Node MIT 及其随附第三方授权；Debian/Alpine OS、libpq/OpenSSL 等 bundled 库有各自条件。**当前清单不是完整容器 OS SBOM，也不是对所有分发方式的法律审核结论**；A09 发布前需要容器级 SBOM/NOTICE 和漏洞复核。GPU overlay 重用 Python 镜像做硬件查询，不包含 CUDA/vLLM/权重；相应许可和部署锁留给 A05。

实现依据：[Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/)、[启动顺序](https://docs.docker.com/compose/how-tos/startup-order/)、[网络](https://docs.docker.com/engine/network/)、[Next standalone](https://nextjs.org/docs/app/api-reference/config/next-config-js/output)、[Celery 配置](https://docs.celeryq.dev/en/stable/userguide/configuration.html)。这些文档是配置依据，不是本项目运行证据。
