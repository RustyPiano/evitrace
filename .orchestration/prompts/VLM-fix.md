# 任务：修复 VLM 视觉理解审核（Codex）发现的 3 个 MAJOR

视觉理解特性 Opus 审核 PASS、Codex 审核 PASS-WITH-FIXES。修以下 3 项，保证既有测试不回归。不要写入/打印真实 key，不要 git commit。

## 1. MOCK_VISION 未在 docker-compose 透传
`docker-compose.yml` backend environment 已透传 `MOCK_LLM`/`MOCK_MEDIA`，但缺 `MOCK_VISION`。
修复：加入 `MOCK_VISION: ${MOCK_VISION:-}`（与 MOCK_LLM/MOCK_MEDIA 同样写法），保证 Docker 下 `.env` 的显式 MOCK_VISION 生效。

## 2. 真实视频重复抽帧（应复用 video_parse 真实帧，仅在帧是 mock 占位时才自抽）
位置：`backend/app/skills/visual_understand.py` 视频真实分支（约 `_run_real_video` / line 99-122），当前真实视觉**总是**再调 `extract_video_frames()` 重抽，与 `video_parse` 已抽的同一批帧重复（full-real 模式下双跑 ffmpeg、二次清理/覆盖帧、增加超时与降级概率）。
修复（按帧来源判定）：
- 当 `settings.effective_mock_media` 为 **False**（即 `video_parse` 已产出**真实**帧并通过 `payload["frames"]` 传入）→ **复用** `payload["frames"]`，逐个 `_safe_frame_path` 校验后直接 VLM 描述，**不要**重新抽帧。
- 当 `effective_mock_media` 为 **True**（传入的是 mock 占位帧）→ 才用 `extract_video_frames()` 从原视频自抽真实帧再描述（用户场景：MOCK_MEDIA=true + 真实 VLM）。
- ffmpeg 缺失/抽帧失败仍为非致命 warning。保持帧路径安全校验。

## 3. 短 VLM key 未脱敏
位置：`backend/app/utils/health_details.py`（约 19，`VLM_API_KEY` 仅 `len>=8` 才加入脱敏表）。
修复：对任何**非空** `settings.vlm_api_key` 都加入脱敏替换（不设最短长度门槛）；同理检查 `local_llm_api_key`/`secret_key` 是否也有同类长度门槛，如有一并对非空值脱敏。补一个单测：短 VLM key 出现在异常/health detail 中会被 `redact_health_detail` 替换。

## 验证（实际执行，最终消息报告）
1. `cd backend && ./.venv/bin/pytest -q` 全绿（含短-key 脱敏、视频帧复用相关新增/更新测试）。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `cd frontend && npm run type-check && npm run build` 通过（若动到前端）。
4. `./backend/.venv/bin/python scripts/evaluate_demo.py` 仍 3/3。
5. `docker compose config` 校验 compose 合法且含 MOCK_VISION。
报告每条修复与验证结果。不要 git commit。
