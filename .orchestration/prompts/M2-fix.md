# 任务：修复 EviTrace M2 三方审核（Opus×2 + Codex）发现的问题

M2 已实现并提交。以下问题由三个独立审核员交叉确认。请**精确修复**并实际跑 `pytest` 验证；为关键修复补测试。不顺手改无关代码，不实现 M3 业务。

## MAJOR

### 1. 无音轨视频不能继续抽帧（违反 PLAN M2-06「无音轨视频仍可抽帧」）
位置：`backend/app/skills/video_parse.py`（真实模式音轨提取失败处）。
现状：提取 WAV 失败直接进入 except → 整个 video_parse 失败，关键帧抽取不执行。
修复：音轨提取失败时**记 warning 并继续**抽帧+帧 OCR；仅当帧处理也失败时才把文件置 failed。MOCK 模式同理：无音轨 fixture 仍应产出帧证据。补测试（无音轨视频仍生成帧证据）。

### 2. `parse_all_files` 写死任务/run 终态，破坏 M3 orchestrator 复用
位置：`backend/app/services/parse_service.py`（结尾把 `task.status=ready`、run 置 succeeded/failed/progress=100）。
修复：
- `parse_all_files` 只负责**文件级**状态（uploaded→parsing→parsed/warning/failed）与证据写入、进度更新，返回 `ParseSummary`；**不要**写死 task 最终状态，也不要把 run 标记终态。
- 任务/run 终态由调用方决定：M2 的 `POST /tasks/{id}/parse` 端点路径在解析后自行把 task 置回合适状态（如 `ready`）；M3 orchestrator 复用时由其控制 parsing→extracting→…。
- 单文件失败**不应**把整个 run 判为 failed（解析阶段单文件失败属 warning）；run 级 failed 留给 orchestrator 综合判断。

### 3. `/tasks/{id}/parse` 缺全局单运行保护（违反 NFR-004「单机只允许一个分析任务运行」）
位置：`backend/app/api/tasks.py`。
现状：只检查当前任务是否运行中。
修复：启动前查询**全局**是否存在处于 `queued/parsing/extracting/detecting_conflicts/generating_report` 的任务或 running 的 task_run，存在则返回 409 `TASK_ALREADY_RUNNING`。用简单进程内锁或 DB 查询避免并发双启动（与 M3-06 将实现的单运行锁保持一致的语义；可把该锁逻辑放到可被 M3 复用的位置）。补测试。

### 4. MOCK fixture 显式空列表被默认 fixture 覆盖 → 伪造证据（违反不伪造原则）
位置：`video_parse.py`（`if fixture_frames:` 回退 `_default_frame_items()`）；**同时检查并修复** `image_ocr.py` 与 `audio_transcribe.py` 是否有同类「显式空 fixture 回退默认」的问题。
修复：当 sidecar fixture **存在**时，必须尊重其空列表语义——空结果返回对应 `NO_*_WARNING`，**不要**回退内置默认内容。只有「完全没有 fixture」时才使用内置默认确定性 fixture。补测试（提供显式空 fixture → 得到 warning 且无伪造证据）。

### 5. 真实模式 OCR/ASR 使用默认模型名/目录，可能联网下载（违反 NFR-001 离线）
位置：`image_ocr.py`（`PaddleOCR(...)`）、`audio_transcribe.py`（`WhisperModel("small", ...)`）。
修复：从配置读取**本地模型路径**（新增 env，如 `OCR_MODEL_DIR`、`ASR_MODEL_DIR`/`ASR_MODEL_SIZE`，加入 `.env.example` 与 config）。真实模式加载时：路径不存在 → 返回明确错误并让健康检查标记 unavailable，**禁止自动下载**（设置库的本地/离线参数）。MOCK 模式不受影响。说明：本环境仍跑 MOCK，无需真的下载模型，但代码路径要正确 fail-closed。

### 6. ffmpeg subprocess 无超时，可能挂死后台解析（违反 PLAN §0.8）
位置：`video_parse.py`（`subprocess.run(...)`）。
修复：所有 ffmpeg 调用加 `timeout=`（如 120s），捕获 `subprocess.TimeoutExpired` 转明确 RuntimeError（文件 failed，不挂进程）。

## MINOR

### 7. sidecar fixture JSON 解析未容错
位置：`backend/app/skills/utils.py`（`json.loads(path.read_text(...))`）。
修复：try/except 包裹，损坏 JSON 降级为「无 fixture」+ warning，不抛异常。

### 8. 重解析不清理旧派生产物
位置：`parse_service.py`（重解析仅删 DB 证据）。
修复：重解析某文件前，清理该文件相关的 `derived/frames`、`derived/audio` 旧产物（按 file_id 限定，避免误删他文件）。

### 9. EvidencePanel 加载缺 catch
位置：`frontend/src/components/EvidencePanel.vue`（watch 内 try/finally 无 catch）。
修复：加 catch，区分真实错误（网络/500）与「不存在/无权」，显示不同提示；避免未处理 rejection。`npm run type-check && build` 通过。

### 10. Skill 健康检查接口未暴露（PLAN M2-01「Skill 健康检查接口」不可达）
修复：后端新增管理员可访问的 skill 健康接口（如 `GET /api/v1/admin/skills` 返回列表含 last_status，及/或 `POST /api/v1/admin/skills/{id}/health` 触发探测刷新）。探测失败只写 `last_status/last_error`，非致命。（前端 Skill 管理页完整 UI 仍留 M4-06。）

### 11. PDF char 偏移基准说明
位置：`document_parse.py`。
修复：在代码 docstring/注释注明 PDF 的 `char_start/char_end` 为**页内相对偏移**（TXT 为全文偏移），避免消费方误用。

## 验证（实际执行，最终消息报告每条结果）
1. `cd backend && ./.venv/bin/pip install -r requirements.txt -r requirements-dev.txt && ./.venv/bin/pytest -q` 全绿，报告新增/总测试数。
2. 端到端（MOCK）：解析 6 类文件仍正常；无音轨视频仍产帧证据；显式空 fixture → warning 不伪造；`parse_all_files` 后 run 未被写死终态；第二个任务在有任务运行时 `/parse` 返回 409。
3. 应用在未安装 paddleocr/faster-whisper 时仍能启动并跑完 MOCK（确认延迟导入未被破坏）。
4. 前端构建通过。
不要运行 git commit。报告所有修复与验证结果，以及任何边界决定（如全局锁放置位置、新增 env）。
