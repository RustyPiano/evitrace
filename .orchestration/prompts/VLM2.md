# 任务：把"视觉理解(VLM)"与本地媒体 mock 解耦，并确保失败优雅降级

VLM 视觉理解 Skill 已实现（`visual_understand` + `VisionClient`）。但目前它受 `effective_mock_media` 控制——而用户的情况是：有**云端 VLM**（SiliconFlow，独立端点），但**没有本地 OCR(PaddleOCR)/ASR(faster-whisper)**，所以会设 `MOCK_MEDIA=true`，导致 VLM 也被强制 mock，无法用真实视觉。需要解耦：让视觉理解由 **VLM 是否配置** 决定真假，独立于 OCR/ASR 的 `MOCK_MEDIA`。已实测 VisionClient 请求构造正确（真实端点在有余额时返回了正确描述；当前 403 是账户余额不足，与代码无关）。保持既有测试不回归。

## 必读
`app/config.py`、`app/skills/visual_understand.py`、`app/services/vision_client.py`、`app/skills/video_parse.py`、`app/services/parse_service.py`、`app/services/admin_service.py`、`backend/tests/unit/{test_config,test_skill_registry,test_mock_media_skills}.py`、`.env.example`、`README.md`。

## 1) 配置解耦：新增 effective_mock_vision（独立于 media）
`app/config.py`：
- 新增 `mock_vision: bool | None`（env `MOCK_VISION`，沿用现有空字符串→None 的 validator）。
- 新增属性 `vlm_configured` = `bool(vlm_base_url and vlm_model and vlm_api_key)`。
- 新增属性 `effective_mock_vision`：`mock_vision` 显式设置则用之；否则 **VLM 已配置→False(真实)，未配置→True(mock)**。即：配好 VLM 就走真实视觉，与 `MOCK_MEDIA` 无关。
- `effective_mock_llm` / `effective_mock_media` 保持不变。

## 2) visual_understand 改用 effective_mock_vision
- 图片路径与视频路径的 mock 判定从 `effective_mock_media` 改为 `effective_mock_vision`。
- 这样：用户设 `MOCK_AI=false`（LLM 真实）、`MOCK_MEDIA=true`（OCR/ASR 走 fixture，无需本地模型）、配好 `VLM_*` → 视觉理解走**真实 VLM**，OCR/ASR 走 fixture，互不影响。

## 3) 视频真实视觉：visual_understand 自带真实抽帧（不依赖 video_parse 的 mock 帧）
问题：`MOCK_MEDIA=true` 时 `video_parse` 产出的是占位 mock 帧，对其做真实 VLM 描述没意义。
修复：`visual_understand._run_video` 在 `effective_mock_vision=False`（真实视觉）时，**自行用 ffmpeg 对原视频按 `VIDEO_FRAME_INTERVAL_SEC` 抽真实关键帧**（复用一个共享抽帧 helper——可从 video_parse 抽出公共函数，二者共用，避免两份逻辑），写入任务派生帧目录（路径安全：resolve+任务目录前缀校验），逐帧 `VisionClient.describe_image` 生成 `video_frame_caption` 证据（locator 含真实 timestamp_ms/frame_path）。
- ffmpeg 不可用时：记 warning 并跳过视频视觉（非致命），不崩。
- `effective_mock_vision=True` 时：维持现有 fixture/默认描述行为。

## 4) 优雅降级（关键）
- `visual_understand` 任意失败（VLM 403/余额不足/超时/未配置/ffmpeg 缺失）必须是**非致命 warning**：不影响 document_parse / image_ocr / audio_transcribe / video_parse，任务仍能完成；错误信息经 `redact_health_detail` 脱敏后入 warning（不泄露 key/路径）。
- 确认 `parse_service` 中 `visual_understand` 失败不被当作 fatal（image/video 都不应因视觉失败而把文件判 failed；OCR 仍是图片的主解析）。

## 5) 健康检查
`admin_service` / `registry` 健康：`visual_understand` 用 `effective_mock_vision`——mock 时 skipped；真实时校验 `vlm_configured`（缺配置→unavailable，脱敏）。`/admin/health` 增一个 `vlm`/视觉条目或并入 skill 健康（择一，保持脱敏、非致命）。

## 6) 文档
`.env.example` / README：说明视觉理解由 VLM 配置驱动、独立于 MOCK_MEDIA；推荐用户配置：
```
MOCK_AI=false
MOCK_MEDIA=true            # 无本地 OCR/ASR → 走 fixture
LOCAL_LLM_*                # 文本 LLM（DeepSeek）
VLM_BASE_URL=https://api.siliconflow.cn/v1
VLM_MODEL=Qwen/Qwen3.6-35B-A3B
VLM_API_KEY=<在 .env，勿提交>   # 需账户有余额
```
并注明：VLM 与文本 LLM 是两个独立端点；视觉理解失败会降级为 warning 不影响其它解析。

## 验证（实际执行，最终消息报告；不要发起需余额的真实 VLM 外网单测）
1. `cd backend && ./.venv/bin/pytest -q` 全绿（新增/更新：effective_mock_vision 逻辑、视觉真实路径用可注入 mock VisionClient、视觉失败优雅降级为 warning 的测试）。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `cd frontend && npm run type-check && npm run build` 通过。
4. `./backend/.venv/bin/python scripts/evaluate_demo.py` 仍 3/3。
5. 报告：config 解耦语义、视频自带抽帧的共享 helper、降级行为、健康与文档位置。
不要 git commit；不要写入/打印真实 key。
