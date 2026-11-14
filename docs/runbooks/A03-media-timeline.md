# A03 媒体时间轴

A03 接受 A02 已成功采集的资源，使用现有 `X-Owner` 能力令牌。示例中的 `$asset` 为采集得到的 UUID，`$owner` 是本地会话令牌；不要把令牌写入日志或仓库。

```powershell
$headers = @{ 'X-Owner' = $owner }
Invoke-RestMethod -Method Post -Headers $headers "http://127.0.0.1:8000/api/v1/assets/$asset/timeline"
Invoke-RestMethod -Method Get -Headers $headers "http://127.0.0.1:8000/api/v1/assets/$asset/timeline"
Invoke-RestMethod -Method Get -Headers $headers "http://127.0.0.1:8000/api/v1/assets/$asset/timeline/result"
```

任务状态为 `PENDING`、`RUNNING`、`SUCCEEDED`、`FAILED`。结果及图片需持相同 owner 请求；镜头 `reference.file` 和 `thumbnail` 可从 `/api/v1/assets/{asset}/timeline/frames/{name}` 读取。重复请求进行中或成功任务不会再次入队；失败后 POST 创建新尝试。任务超时后 GET 标记失败，新尝试使用新目录，旧结果不能覆盖新任务。异常退出可能遗留 `.media-*` 临时目录；仅在确认相关 worker 已停止及相关任务已超时后，由管理员清理，不自动清除其他资源。

JSON 记录源文件 SHA-256、容器/编码、视频和音轨索引、尺寸、旋转、时基、帧率与 VFR 判断。镜头为连续半开区间，起止为相对首个解码 PTS 的整数毫秒；末尾取解码帧时长，缺失时采用视频流时长，并标明依据。参考帧保留原始解码 PTS、相对毫秒和 JPEG 哈希；图像经 FFmpeg 自动旋转并缩放至最长边不超过 640。每镜另保存缩略图；短于 300ms 的片段标记 `short_shot`，转场类型未分类。时间戳缺失、倒退或无法在毫秒分辨率表达时明确失败。

检测使用固定版本 PySceneDetect ContentDetector，检测画面缩放为 320×180，阈值 27、最短长度 1 帧。它主要识别硬切，闪白、慢淡变、复杂运动等须人工复核；每个短镜标记而非自动删除。最多 30000 帧、200 镜、180 秒，受进程时间与容器资源上限约束。输入仅限 A02 验证过的本地 MP4/MOV；不读取外部 URL。具体的 API 合同由 `/openapi.json` 产生。

依赖通过 `backend/uv.lock` 和 `backend/requirements.lock` 固定。新增 PySceneDetect 0.6.7.1（BSD-3-Clause）、OpenCV headless 4.12.0.88（包声明 Apache-2.0）、NumPy 2.2.6（BSD-3-Clause，二进制还包含独立许可组件）；传递引入 platformdirs 和 tqdm，并将 click 从 8.5.0 改为 8.2.1。实际 Linux wheel 的许可与 notice 已保存于 `evidence/A03/licenses-20261114/`；镜像的 FFmpeg 构建启用 GPL。发布时仍需核查底层库、镜像 OS 和完整分发义务，不能用顶层许可代替完整分发审计。

复现本机后端测试：`cd backend; uv run --frozen pytest -q`。隔离真实基础设施回归：`python scripts/verify_a01_e2e.py`。A03 单独的真实 Compose 合成视频检查：`python scripts/acceptance_a03.py --output-dir evidence/A03/<new-directory>`；该脚本只创建并清理随机命名的测试 Compose 项目及其合成数据。真实视频标注和 F1 不在此脚本内。

真实留出集就绪后，可用 `python scripts/eval_shot_boundaries.py holdout.json --output evidence/A03/<new-directory>/shot-eval.json` 计算指标。输入格式为 `{"videos":[{"id":"匿名样本编号","split":"holdout","reference_ms":[1000,2000],"predicted_ms":[1020,2010]}]}`；两个数组为严格递增的整数毫秒切点，不包含片头和片尾。工具按时间排序进行 ±300ms 最早一对一匹配，报告 Precision、Recall、F1、误差中位数和 P90；没有任何参考或预测切点时 F1 为 null。长镜头及强特效应分别准备子集报告；样本授权、双人标注仲裁和调参/留出集隔离仍须在数据准备时核实，工具不能代替这些核实。
