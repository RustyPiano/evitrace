# 代码审核：EviTrace 接入本地 OCR/ASR HTTP 服务

你是独立审核员（只读，禁止修改）。审核新增的 OCR/ASR HTTP 适配是否正确、安全、无回归。这是增量特性：把图片 OCR、音频 ASR、视频帧 OCR/音轨从 in-process 库改为可调用本机 HTTP 服务（PaddleOCR :8000 `POST /ocr`、FunASR :8001 `POST /asr`）。该特性已在真实服务上跑通端到端（OCR 出 bbox、ASR 出带说话人/秒级时间戳分段、跨模态时间+数量冲突被检出）。

## 范围
`backend/app/services/media_client.py`、`backend/app/skills/image_ocr.py`、`backend/app/skills/audio_transcribe.py`、`backend/app/skills/video_parse.py`（复用 real_ocr/real_transcript）、`backend/app/config.py`、`backend/app/services/admin_service.py`、`backend/app/skills/registry.py`、`backend/app/utils/health_details.py`、`.env.example`、`README.md`、`docker-compose.yml`、`backend/tests/**`。

## 契约（服务端真实行为）
- OCR `POST /ocr` multipart `file` → `{width,height,results:[{text,score,box:[x1,y1,x2,y2]}]}`。
- ASR `POST /asr` multipart `file` → `{duration,segments:[{start秒,end秒,speaker|null,text}]}`。
- 两者 `GET /health` → `{status,warmed}`。

## 必查项
1. **安全/泄露**：OCR/ASR 服务错误、超时、连接失败的消息是否经 `redact_health_detail` 脱敏（不含磁盘绝对路径、不含任何 key、不含内部堆栈）；health detail 是否脱敏；`base_url` 是否仅来自管理员配置的 env（非用户输入，SSRF 面有限）；是否避免把上传文件内容/路径泄露到证据或日志。
2. **HTTP 客户端健壮性**：`media_client` 是否设置超时（MEDIA_TIMEOUT_SEC）、正确处理非 2xx/连接错误/超时/非 JSON 响应；multipart 上传是否正确读取文件并释放句柄（with/finally）；是否新建并关闭 httpx client（无泄漏）；**业务 skill 是否不直接 import httpx**（只经 media_client）。
3. **映射正确性**：OCR `box[x1,y1,x2,y2]→locator.bbox`、`score→confidence`、`text→content`、空文本跳过、无结果 warning；ASR `start/end 秒→start_ms/end_ms(×1000 取整)`、`speaker→"[说话人N] text"` 拼接、空 segments/text warning；视频帧 OCR 是否仍组装为 `video_frame` locator(含 bbox/timestamp_ms/frame_path)、视频音轨是否 `video_audio` locator。
4. **real/mock/lib 选择**：`effective_mock_media=True`→fixture(不变)；`=False` 且配 `OCR_BASE_URL`/`ASR_BASE_URL`→HTTP；`=False` 且未配 URL→回退 in-process 库(OCR_MODEL_DIR/faster-whisper)。逻辑是否清晰、向后兼容（仅 MOCK_AI 时不变）。
5. **降级语义**：OCR/ASR 服务不可用时的行为——image_ocr 在 image 上失败是否仍 fatal（设计如此？是否合理：服务宕机即整图失败 vs 应 warning）；视频帧 OCR / 音轨 ASR 失败是否非致命、不影响其它证据；确认服务故障不会让任务卡死或整体崩溃。指出任何不当的 fatal/非 fatal 选择。
6. **健康探活**：admin/health 与 registry 对 OCR/ASR——配 URL 时 `GET {url}/health` 探活（非致命、脱敏），否则 lib/模型目录检查；mock skipped。
7. **回归/范围**：MOCK 演示 evaluate 3/3 不破坏；既有 fixture/lib 路径语义未变；不引入被禁止依赖；docker-compose 透传新 env（OCR_BASE_URL/ASR_BASE_URL/MEDIA_TIMEOUT_SEC）且 host.docker.internal 文档正确；.env.example/README 无真实 key（占位）。
8. **资源/超时**：FunASR CPU 较慢，超时是否足够；大文件 multipart 是否一次性读入内存（可接受但指出）。

## 输出
每个发现：严重级别（BLOCKER/MAJOR/MINOR/NIT）、文件:行、问题、修复建议。最后一行总评 PASS/PASS-WITH-FIXES/FAIL + 合并前必修项。只报告真实问题。
