# 任务：修复 OCR/ASR HTTP 接入审核（Opus+Codex）发现项

双审结论 PASS-WITH-FIXES。修以下项，保持既有测试不回归，不写真实 key，不 git commit。

## MAJOR：视频解析中 ASR/OCR HTTP 失败应非致命（与图片 OCR 语义一致）
位置：`backend/app/skills/video_parse.py`（约 `real_video_outputs`：音轨 `real_transcript_evidence(...)` ~200 行、帧循环 `real_ocr_evidence(frame)` ~214 行）。
现状：HTTP ASR/OCR 服务超时/连接失败/5xx/非JSON 抛 RuntimeError 冒泡到 `VideoParseSkill.run` → `success=False` → `parse_service` 把 `video_parse` 判 fatal → 整段视频失败，丢失已得证据。图片路径下 OCR 故障只 warning，视频却整体失败，语义不一致。
修复：
- 音轨：把 `real_transcript_evidence(...)` 包 `try/except`（捕获 RuntimeError，FfmpegTimeout 维持原处理），失败时追加脱敏 warning（如 `NO_VIDEO_AUDIO_WARNING` 或带 `redact_health_detail` 原因），继续抽帧/OCR。
- 帧 OCR：在帧循环内对每帧 `real_ocr_evidence(frame)` 逐帧 `try/except`，单帧失败记 warning 并继续后续帧；不要让单帧/服务故障使整段视频 fatal。
- 仅"抽帧本身失败 / 明确的 ffmpeg 超时"等可保持原有 fatal 语义；其余媒体服务故障降级为 warning。
- 确认 `parse_service` 层最终：视频在 ASR/OCR 服务故障时为 `warning` 状态、保留已生成证据，不 fatal。补/更新测试：注入会抛错的 OCR/ASR（mock）验证视频仍产出部分证据且非 fatal。

## MINOR：admin health 的模型目录解析与 skill 不一致
位置：`backend/app/services/admin_service.py`（约 277，`_configured_directory_ready` 用 `Path(value).expanduser().is_dir()`，相对路径按进程 cwd 解析）。
现状：真实 OCR/ASR resolver 按 `PROJECT_ROOT` 解析相对 `OCR_MODEL_DIR`/`ASR_MODEL_DIR`，admin health 却按 cwd → 可能 skill 能跑但 health 报"模型目录未就绪"。
修复：复用 `resolve_ocr_model_dirs()` / `resolve_asr_model_path()`（或在 health 里同样按 `PROJECT_ROOT` 锚定相对路径）判断就绪，保持与 skill 一致。注意这是 lib-fallback 路径（HTTP 路径不受影响）。

## MINOR：文档化 /health 契约
`README.md` 「本机 HTTP OCR/ASR 服务」一节：注明适配服务的 `GET /health` 需返回 `{"status":"ok","warmed":bool}`（与 `media_client.check_media_health` 的判定一致），便于他人接入自有服务时对齐。

## 验证（实际执行，最终消息报告；单测用可注入 mock，不连真实服务/外网）
1. `cd backend && ./.venv/bin/pytest -q` 全绿（含视频 ASR/OCR HTTP 失败非致命的新增测试）。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `./backend/.venv/bin/python scripts/evaluate_demo.py` 仍 3/3。
4. （若动前端）`npm run type-check && build` 通过。
报告每条修复与验证结果。不要 git commit。
