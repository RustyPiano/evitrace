# 任务：修复 EviTrace M5 审核（Codex + Opus 主循环直审）发现的问题

M5 已实现并提交。审核确认：评估脚本**诚实**（真实管线、临时 DB、expected.json 仅事后比对、阈值不达标 exit 1）、compose/entrypoint 安全、README 结构完整、仓库未提交 .env/secret。以下为需修复项。请精确修复并重新验证。

## MAJOR

### 1. 演示音频/视频时长不符合 SPEC §14.1（约 20–40 秒）
现状：`scripts/build_demo_data.py` `MEDIA_SECONDS = 8`，三组 demo 的 audio.wav/video.mp4 均为 8s。SPEC §14.1 要求约 20–40 秒。
修复：把 `MEDIA_SECONDS` 改为 20–40 秒内的确定值（建议 30），重新生成三组 `audio.wav` 与 `video.mp4` 并提交。生成后用 `ffprobe`/wav header 确认时长≈30s。**重新运行 `evaluate_demo.py` 确认三组仍 recall≥0.8、coverage≥0.9、invalid==0、四模态齐全**（sidecar 的 start_ms/end_ms 若超出新时长需相应调整到时长范围内）。

### 2. `build_demo_data.py` 在无 ffmpeg 时仍返回 0，可能生成缺 video.mp4 的“成功”不完整 demo
现状：无 ffmpeg 时只 warning 并 `main` 返回 0；而生成演示视频确实需要 ffmpeg。
修复：把 ffmpeg 设为**生成 demo 的硬依赖**——无法生成 `video.mp4` 时打印明确错误并 `return 非 0`（不要静默产出不完整 demo）。同时更新 README「Requirements/Demo」处：明确「(重新)生成演示视频需要 ffmpeg」（区别于真实视频解析的 ffmpeg 需求）。

### 3. Docker real-mode 文档不自洽：镜像未含 ffmpeg/OCR/ASR，但 README 生产段建议 `MOCK_AI=false`，且 healthcheck 仅 liveness → 可“容器 healthy 但真实多模态不可用”的假成功
现状：`backend/Dockerfile` 只装 curl + `requirements.txt`（无 ffmpeg、无 paddleocr/faster-whisper）；`README.md` 生产配置段（约 92–99 行）建议 `MOCK_AI=false`；compose healthcheck 只打公开 `/health`（恒 ok）。
修复（以文档诚实为主，二选一并落实）：
- **推荐**：明确**所提供的 Docker 镜像仅用于 MOCK 演示**。在 README Docker 段与 compose 注释中说明：在容器内启用真实模式（`MOCK_AI=false`）需要自行扩展镜像（安装 `requirements-optional.txt`、系统 `ffmpeg`）并挂载本地 `OCR_MODEL_DIR/ASR_MODEL_DIR` 与配置 `LOCAL_LLM_*`；否则保持 `MOCK_AI=true`。把 README 生产段的 `MOCK_AI=false` 改为有前提条件的说明，不要让读者以为开箱即用。
- 可选增强（如时间允许，不阻塞）：增加一个真实模式的 Dockerfile target/compose profile（安装 ffmpeg + optional 依赖、挂载模型目录），或为真实模式增加覆盖 LLM/OCR/ASR/ffmpeg 的 readiness 检查；若不做，务必在文档中明确当前镜像为 MOCK-only。

## 验证（实际执行，最终消息报告每条真实输出）
1. `./backend/.venv/bin/python scripts/build_demo_data.py` 重新生成，`ffprobe`/header 确认 audio/video ≈30s；无 ffmpeg 时返回非 0（可临时改 PATH 模拟说明，或仅说明逻辑已就位）。
2. `./backend/.venv/bin/python scripts/evaluate_demo.py` 通过，三组指标仍达标（贴 evaluation_result.md 表格）。
3. `cd backend && ./.venv/bin/pytest -q` 仍全绿；`cd frontend && npm run build` 仍通过。
4. README 的 Docker/Requirements/MOCK 段与镜像实际能力一致（不再暗示开箱即用 real-mode）。
不要运行 git commit。报告所有修复与验证结果。
