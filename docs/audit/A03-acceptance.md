# A03 媒体时间轴验收记录

日期：2026-11-14，Asia/Shanghai。结论：**BLOCKED**，已完成下列实现和合成数据检查；真实授权视频的人工标注留出集及其 F1、边界误差尚未取得，不能宣称切镜质量门槛通过。

## 范围与实现

基于 A02 已成功采集的资源，通过受 owner 约束的 API 请求独立 media 队列任务。ffprobe 读取轨道及解码帧 PTS；PySceneDetect ContentDetector 找物理切点并映射回 PTS；结果含连续半开毫秒区间、源文件哈希、旋转/音轨/VFR 信息、每镜参考帧和缩略图。帧经旋转和缩放，保留原始 PTS、时间和哈希。数据库迁移 `0003_media_timeline` 保存状态；任务重试使用独立尝试标识，旧尝试不能覆盖新状态。具体 API 和操作见 [A03 手册](../runbooks/A03-media-timeline.md)。

新增评测脚本 `scripts/eval_shot_boundaries.py` 以 ±300ms 做一对一匹配；它尚未运行于真实标注集，也不能验证样本授权、标注仲裁或训练/留出集隔离。

## 环境和依赖

Windows 11 10.0.26200，Intel i5-13420H（8 核/12 线程），约 15.7 GiB 内存；Python 3.12.13，主机 FFmpeg 9.0.2，隔离容器 FFmpeg 5.1.9-0+deb12u1，Docker Engine 29.9.3，前端验收 Node 22.23.1。硬件、版本及构建信息见 [evidence/A03](../../evidence/A03/)。

固定 `scenedetect==0.6.7.1`、`opencv-python-headless==4.12.0.88`、`numpy==2.2.6`，同时锁定传递依赖并导出带哈希清单；click 从 8.5.0 变为 8.2.1。实际 Linux 镜像的六个直接和相关传递包的许可证及 notice 已保存至 [packages.json](../../evidence/A03/licenses-20261114/packages.json)。容器 FFmpeg 配置启用 GPL，见 [ffmpeg.json](../../evidence/A03/licenses-20261114/ffmpeg.json)。这些材料不等于完整容器系统/二进制依赖 SBOM，也不构成发布许可审批。

## 测试与真实基础设施证据

| 命令 | 退出码 | 通过/失败/跳过 | 范围和证据 |
|---|---:|---|---|
| `cd backend; python -m pytest -q`（项目 3.12 虚拟环境） | 0 | **122/0/0** | [pytest.json](../../evidence/A03/checks-v3-20261114/pytest.json)；含 20 组合成硬切，横竖屏、多帧率、VFR、旋转和音轨，以及无声、损坏、超时、所有权、队列故障、重试、旧任务和评测匹配。1 条 Starlette/httpx 弃用警告 |
| `ruff check app migrations tests ../scripts/acceptance_a03.py ../scripts/collect_a03_licenses.py ../scripts/eval_shot_boundaries.py` | 0 | 静态检查通过 | [ruff.json](../../evidence/A03/checks-v3-20261114/ruff.json) |
| `cd backend; mypy` | 0 | 26 个源文件通过 | [mypy.json](../../evidence/A03/checks-v3-20261114/mypy.json) |
| `python scripts/acceptance_a03.py --output-dir evidence/A03/compose-final-20261114` | 0 | **9/0/0** | [summary.json](../../evidence/A03/compose-final-20261114/summary.json)；真实 Compose、真实上传和 Celery 队列、合成双镜头、帧哈希及跨 owner 拒绝 |
| `python scripts/verify_a01_e2e.py --output-dir evidence/A03/a01-regression-final-20261114` | 0 | 基础设施 **25/0/0**，采集 **26/0/0**，浏览器 **7/0/0** | [summary.json](../../evidence/A03/a01-regression-final-20261114/summary.json)；包含真实数据库、迁移重放、隔离网络及桌面/移动浏览器，不代表真实模型验收 |
| `python scripts/collect_a03_licenses.py evidence/A03/licenses-20261114/packages.json` | 0 | 6 包记录 | [collect.json](../../evidence/A03/licenses-20261114/collect.json)；独立断网容器读取包内许可 |

开发过程中竖屏样例在检测画面补黑边时出现 10 个失败，修正为完整画面缩放后 20 组硬切均通过；不能以此替代真实 F1。另有一次证据采集器使用相对可执行路径导致 3 条命令各记录退出 127，改用绝对路径后在新目录重跑；原始记录保留在 `evidence/A03/checks-20261114/`。

## 限制与未测事项

- 真实人工标注数据集、F1 ≥ 0.85、边界误差中位数 ≤150ms、长镜头和强特效分层：**BLOCKED**。合成样例偏重硬切，不代表真实视频质量。
- ContentDetector 对闪白、慢淡变、复杂运动可能漏检或误检；只标记短镜，转场分类、复杂运动自适应加密采样尚未实现。当前每镜一帧及缩略图。
- 30,000 帧、200 镜、180 秒的上限和单 worker CPU 配置未做真实视频负载/性能基准。异常终止可能留下临时目录，处理方式见手册；磁盘耗尽、宿主机强制掉电和真实并发压力尚未实测。
- 当前 Linux 容器含 GPL 构建的 FFmpeg；NumPy/OpenCV wheel 的第三方组件及容器 OS 完整分发义务仍需发布前审查。Qwen、ASR、OCR、GPU 和全流程离线推理均不属于本卡实测。

下一步：取得获授权、按规范划分并人工标注的真实留出集，运行评测并对未达门槛的镜头类型改进；在此之前 A03 保持 BLOCKED。
