# 代码审核任务：EviTrace M2（多模态解析与证据卡片）

你是独立代码审核员（只读，禁止修改）。审核 M2 是否符合 `SPEC.md`/`PLAN.md`。

## 依据
- `SPEC.md` §5.4（EVID-001~006 证据与 locator 结构）、§5.9（SKILL-001~004）、§6.3 目录、§8.4 evidence 接口、§12 安全、§13 错误码、NFR-001。
- `PLAN.md` 第 4 章 M2-01~08、第 10 章风险降级。
- 代码：`backend/app/skills/*`、`backend/app/services/{parse_service,result_service}.py`、`backend/app/api/evidence.py`、`backend/app/skills/registry.py`、`backend/tests/*`、`frontend/src/components/EvidencePanel.vue`、`frontend/src/views/TaskDetailView.vue`、`backend/requirements*.txt`。

## 必查项
1. **延迟导入隔离**：paddleocr/faster-whisper/torch/paddle 是否绝不在应用启动路径 import；只在 MOCK_AI=false 的执行分支内 import。无这些依赖时应用能否启动、测试能否跑（这是硬性要求）。
2. **locator/证据 结构**：各模态 locator 是否与 SPEC §5.4 EVID-006 完全一致（text: page/paragraph/char_start/char_end；image: bbox；audio: start_ms/end_ms；video_audio: start_ms/end_ms；video_frame: timestamp_ms/frame_path/bbox）；evidence_type 取值（paragraph/ocr/asr/video_frame_ocr）与 modality（text/image/audio/video）是否正确。
3. **证据编号**：`next_display_id` 是否从 E-0001 递增、同任务唯一不重复；批量写入跨多个文件时编号是否仍连续且无冲突；并发不是首版目标但单任务逻辑要正确。
4. **文档解析正确性**：TXT/MD 编码检测与空行切段；DOCX 非空段落；PDF 按页 + 1000 字符切块 + 正确页码；空白块不保存；损坏文件标记 failed 且不抛未捕获异常；扫描 PDF 无文本是否 warning。
5. **MOCK fixture 机制**：是否确定性、是否不伪造（无文本/无语音应 warning 而非编内容）；默认 fixture 是否产出结构正确证据；sidecar 查找是否有路径穿越风险。
6. **路径安全**：派生文件（derived/audio、derived/frames）与 frame_path 是否严格限制在任务目录内；`/evidence/{id}/frame` 是否做归属权限校验、能否被用于读取任务目录外文件；evidence 读取接口是否都校验 owner/admin（IDOR）。
7. **解析编排**：单文件失败是否不影响其他文件；文件状态机（uploaded→parsing→parsed/warning/failed）是否正确；重解析前是否删除该文件旧证据；停用某解析 skill 时该类文件是否 warning 且流程继续；`parse_all_files` 是否可被 M3 orchestrator 复用（未写死任务最终状态）。
8. **Skill 框架**：base 的 SkillManifest/SkillContext/SkillResult/Skill 协议是否符合 PLAN M2-01；registry 是否含 7 个 skill、required 不可停用校验是否存在；健康检查是否非致命（探测失败不崩）。
9. `POST /tasks/{id}/parse` 权限、运行中 409、BackgroundTasks 行为是否正确；是否存在两份重复解析逻辑（应只有一份供复用）。
10. 是否越界实现 M3（LLM 提取/冲突/报告/总 orchestrator 不应在此出现）；是否引入被禁止依赖；requirements 分层是否正确（轻量在 requirements.txt，重型在 optional）。
11. 前端：EvidencePanel 是否能据 locator 跳转音视频时间、显示 PDF 页码/bbox/关键帧缩略图；无权 URL 是否不可直接访问；构建是否无 CDN 外链。

## 输出
每个发现：严重级别（BLOCKER/MAJOR/MINOR/NIT）、文件:行、问题、修复建议。最后一行总评 PASS/PASS-WITH-FIXES/FAIL，并列出进入 M3 前必须修的项。只报告真实问题。
