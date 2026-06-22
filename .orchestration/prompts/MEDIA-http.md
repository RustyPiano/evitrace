# 任务：接入本地 OCR/ASR 的 HTTP 服务（替代 in-process 库），打通真实多模态

用户已在本机把 OCR、ASR 部署为 **HTTP 微服务**（不是我们当前用的 in-process paddleocr/faster-whisper 库）。需要新增 HTTP 适配，使真实模式调用这些服务。保持既有测试不回归，不写入/打印任何真实 key，不 git commit。

## 已确认的服务契约（实测通过，按此实现）
**OCR 服务**（本机 `http://127.0.0.1:8000`，Docker 内用 `http://host.docker.internal:8000`）：
- `POST /ocr` multipart 字段 `file=<图像>` → `{"filename","width","height","count","results":[{"text":str,"score":float,"box":[x1,y1,x2,y2]}]}`（box 为像素轴对齐框）。
- `GET /health` → `{"status":"ok","warmed":bool}`。

**ASR 服务**（本机 `http://127.0.0.1:8001`，Docker 内 `http://host.docker.internal:8001`）：
- `POST /asr` multipart 字段 `file=<音频>` → `{"filename","duration","segments":[{"start":秒float,"end":秒float,"speaker":"说话人N"|null,"text":str}]}`。
- `GET /health` → `{"status":"ok","warmed":bool}`。
- 注意：start/end 是**秒**（要转成毫秒）；segments 可能为空（静音）。

## 1) 配置
`app/config.py` 新增：`OCR_BASE_URL`、`ASR_BASE_URL`（默认空→None，沿用空串→None validator）；`MEDIA_TIMEOUT_SEC`（默认 180，OCR/ASR HTTP 调用超时，CPU 推理较慢）。
real 模式（`effective_mock_media=False`）下：**若 `OCR_BASE_URL` 配置则走 HTTP OCR 服务，否则回退到现有 in-process 库（OCR_MODEL_DIR + paddleocr）**；ASR 同理（`ASR_BASE_URL` → HTTP，否则 faster-whisper 库）。`MOCK_MEDIA=true` 仍走 fixture（不变）。

## 2) HTTP 媒体客户端 `app/services/media_client.py`
- `ocr_image(base_url, image_path) -> list[dict]`：httpx multipart POST `{base_url}/ocr`，超时 `MEDIA_TIMEOUT_SEC`，返回 results（[{text,score,box}]）。
- `asr_audio(base_url, audio_path) -> dict`：POST `{base_url}/asr`，返回 {duration, segments}。
- 错误处理：HTTP 非 2xx / 连接失败 / 超时 → 抛明确 RuntimeError（消息经 `redact_health_detail` 脱敏，不含路径/内部细节）。
- **业务 skill 不直接 import httpx**，只经 media_client（与 llm_client/vision_client 一致）。

## 3) image_ocr 真实路径接 HTTP
`app/skills/image_ocr.py` 的 `real_ocr_evidence`（及 video 复用它的地方）：当 `OCR_BASE_URL` 配置时改调 `media_client.ocr_image`，把每个 result 映射为证据：`content=text`、`confidence=score`、`locator={"kind":"image","bbox":box}`、`evidence_type="ocr"`、`modality` 由调用方决定（图片=image，视频帧由 video_parse 设 video/locator kind=video_frame 含 bbox+timestamp_ms+frame_path）。空文本跳过；无任何结果 → warning（不伪造）。未配 OCR_BASE_URL 时保持原 in-process 行为。
- 注意视频帧 OCR：video_parse 现在对每帧调 `real_ocr_evidence(frame_path)`；保证 HTTP 模式下也按帧返回 box，并组装成 `video_frame` locator（沿用现有视频帧证据组装逻辑，只换底层 OCR 来源）。

## 4) audio_transcribe 真实路径接 HTTP
`app/skills/audio_transcribe.py` 的 `real_transcript_evidence`：当 `ASR_BASE_URL` 配置时改调 `media_client.asr_audio`，把每个 segment 映射为证据：`content`=（speaker 非空则 `f"[{speaker}] {text}"`，否则 `text`）、`locator={"kind":"audio","start_ms":int(start*1000),"end_ms":int(end*1000)}`（视频音轨由 video_parse 设 kind=`video_audio`）、`evidence_type="asr"`。空文本/空 segments → warning。未配 ASR_BASE_URL 时保持原 faster-whisper 行为。
- video_parse 的音轨转写复用 `real_transcript_evidence`，HTTP 模式自动生效。

## 5) 健康检查
`admin_service` / `registry` 健康：real 模式下 OCR/ASR——若配了 *_BASE_URL，则 `GET {url}/health` 探活（healthy/unavailable，脱敏，非致命）；否则用原 lib/模型目录检查。mock 模式 skipped。

## 6) 文档/配置
`.env.example` 与 README：新增 `OCR_BASE_URL`/`ASR_BASE_URL`/`MEDIA_TIMEOUT_SEC` 说明 + 「本机 HTTP OCR/ASR 服务」配置示例（本机 127.0.0.1:8000/8001；Docker 用 host.docker.internal）；说明 real 模式下优先 HTTP、否则用本地库；并给出**全真实**示例配置：
```
MOCK_AI=false
MOCK_MEDIA=false
OCR_BASE_URL=http://127.0.0.1:8000
ASR_BASE_URL=http://127.0.0.1:8001
LOCAL_LLM_BASE_URL=https://api.deepseek.com/v1   (+key+model)
VLM_BASE_URL=https://api.siliconflow.cn/v1       (+key+model)
```
并提醒：本机 OCR 服务占用 8000（与后端默认端口冲突），本地裸跑后端请换端口（如 8088）。

## 验证（实际执行，最终消息报告；单测不要发起真实外网/服务调用，用可注入 mock/httpx MockTransport）
1. `cd backend && ./.venv/bin/pytest -q` 全绿（新增：OCR/ASR HTTP 适配映射[box/秒→ms/speaker]、空结果 warning、服务错误降级、real 模式 HTTP-优先选择逻辑、健康探活；用 mock transport，不连真实服务）。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `cd frontend && npm run type-check && npm run build` 通过（若动到前端）。
4. `./backend/.venv/bin/python scripts/evaluate_demo.py` 仍 3/3（MOCK 路径不回归）。
报告：改动文件、HTTP 适配映射、real 模式 HTTP/lib 选择与 mock 关系、健康探活、文档位置、端口冲突提醒。不要 git commit。
