# 任务：保留历史运行（重跑不再销毁证据/结果，可追溯）

外部评审指出：每次开始新运行前 `orchestrator._delete_previous_outputs()` 删除该任务**全部**旧 `Evidence` + `AnalysisResult`，且 `AnalysisResult.task_id` 唯一——重跑即销毁历史，与「分析过程可复现、可追溯」定位冲突。

目标：重跑保留历史；默认读取**最新运行**；可按 run 查看历史；仅在删除任务时物理删除。向后兼容、既有测试不回归、MOCK 演示仍 3/3、含对旧 SQLite 库的轻量迁移。不要 git commit。

## 采用「低风险」方案（务必照此，避免大改 display_id 唯一性）
- **保留** `Evidence` 唯一约束 `(task_id, display_id)` 不变。
- `display_id` 计数器**保持 task 级递增**（`result_service.next_display_id` 不改语义）：新一轮运行的证据继续从上轮最大值+1 编号（如上轮 E-0001..E-0008，本轮 E-0009..），因此跨运行 display_id 永不冲突，无需改唯一约束。每个运行内部仍是一段连续编号，报告/抽取只引用本运行段，语义自洽。
- 给 `Evidence` 增加 `run_id`（标记证据属于哪次运行），读取时按运行过滤。

## 1) 模型（`backend/app/models.py`）
- `Evidence`：新增 `run_id: Mapped[str | None] = mapped_column(Text, ForeignKey("task_runs.id"), nullable=True, index=True)`（**nullable**，兼容旧行）。唯一约束保持 `(task_id, display_id)`。
- `AnalysisResult`：`task_id` 去掉 `unique=True`，保留 `index=True`（一个任务可有多条结果，每次运行一条）。`run_id` 已存在，保留。

## 2) 轻量迁移（`backend/app/database.py` 的 `initialize_database`，幂等、仅 SQLite）
`create_all` 不会改既有表。新增对既有库的安全迁移（用 `PRAGMA table_info` / `sqlite_master` 检测，全部 try/except 容错、不抛致命）：
- 若 `evidence` 表缺 `run_id` 列 → `ALTER TABLE evidence ADD COLUMN run_id TEXT`。
- 回填：`UPDATE evidence SET run_id=(SELECT ar.run_id FROM analysis_results ar WHERE ar.task_id=evidence.task_id) WHERE run_id IS NULL`（旧库通常只有一条结果，能正确回填；多结果库尽力而为）。
- 若 `analysis_results` 上存在 `task_id` 的**唯一索引**（旧 `unique=True` 自动生成，名如 `sqlite_autoindex_analysis_results_*` 或检测其 `origin=u`/`unique=1` 且仅含 task_id 列）→ `DROP INDEX` 该唯一索引，使其可容纳多结果。仅删除「唯一且列为 task_id」的索引，不要误删其它。
- 非 SQLite 后端：跳过迁移（仅 create_all）。
- 迁移信息用现有 logger，**不要**打印任何路径/凭证（脱敏）。

## 3) 运行解析助手（`backend/app/services/result_service.py` 或新 helper）
- `resolve_result(db, task_id, run_id=None) -> AnalysisResult`：
  - `run_id` 给定 → 取该任务该 run 的结果；不存在 → 404。
  - 未给 → 取该任务**最新**结果（按 `AnalysisResult.created_at` desc，并列时按对应 `TaskRun.started_at` desc）。无 → 404。
- `resolve_run_id_for_evidence(db, task_id, run_id=None) -> str | None`：给定 run_id 用之；否则用最新结果的 run_id；若任务尚无结果但有证据（异常态）回退最新有证据的 run。

## 4) 证据读取按运行过滤（`result_service.py` + `orchestrator.py`）
所有「按 task 读全部证据」的入口都要改成「按解析出的 run 过滤」，避免把历史运行证据混入当前视图：
- `result_service.list_task_evidence` / `list_task_evidence_index` / 单条 `get_evidence_detail` / `evidence_source` / `frame_file_response`：解析目标 run（默认最新），`Evidence` 查询加 `Evidence.run_id == <resolved>`（兼容：若 resolved 为 None，退回旧的 task 级行为，保证空历史/旧库不崩）。
- `orchestrator._list_evidence(db, task_id)` → 改 `_list_evidence(db, run_id)`，按 `Evidence.run_id == run.id` 过滤（execute_run 内已有 run.id）。**这是关键**：累积证据后，当前运行只能看自己这轮的证据。
- `analysis._evidence_payload(db, task_id)` → 按 run 过滤（用 result.run_id）。

## 5) 证据写入带 run_id（`parse_service.py` / `result_service.create_evidence`）
- `create_evidence(...)` 增加 `run_id` 参数并写入。`parse_service` 调用处把当前 `run_id`（context 已有）传入。`next_display_id` 仍 task 级（递增，跨运行不冲突）。

## 6) 不再销毁历史（`orchestrator.py`）
- 删除/停用 `start_run` 与 `_create_run_without_user` 中对 `_delete_previous_outputs` 的调用（函数可保留但不再于重跑时调用；或直接移除调用点）。重跑只追加新 run 的证据与结果。
- `AnalysisResult` 创建保持（已带 run_id、task_id）；task_id 现非唯一，可多条。

## 7) 历史 API（`backend/app/api/analysis.py`）
- 新增 `GET /tasks/{id}/runs`：列出该任务全部运行（run_id、status、progress、started_at、finished_at、是否有结果 has_result），按 started_at desc。复用 `ensure_task_access`。
- `GET /tasks/{id}/results` 增加可选 `run_id` 查询参数（默认最新）；用 `resolve_result`。
- `GET /tasks/{id}/report/download` 增加可选 `run_id`（默认最新）。报告文件：当前写 `reports/latest.md`（最新运行）。历史下载：若 `reports/{run_id}.md` 不存在则用该结果 DB 内 `report_markdown` 写入 `reports/{run_id}.md` 再返回。文件名时间戳用该结果时间。
- `regenerate_report` / `update_conflict_status`：作用于**指定或最新**结果（用 resolve_result，默认最新），确保改的是当前展示的那一条。

## 8) 删除任务（`task_service.py`）
- 现有删除已按 task_id 级联删 Evidence/AnalysisResult/TaskRun/TaskFile —— 保留（这就是「仅删除任务时物理删除」）。确认仍正确（Evidence 仍有 task_id 列）。

## 9) 前端（最小、可选，勿破坏）
- 后端默认仍返回最新运行，前端**行为不变**即可（type-check/build 必须过）。
- 可选低风险增强：任务/结果页加一个「历史运行」下拉（调用 `GET /tasks/{id}/runs`，选某 run 时带 `run_id` 拉 results）。**非必需**；若加须 type-check/build 通过、不硬编码任何密钥。时间紧可仅后端 + 不动前端。

## 验证（实际执行，最终消息逐条报告）
1. `cd backend && ./.venv/bin/pytest -q` 全绿。新增测试：
   - 同一任务连续两次 run：两轮证据都在库、display_id 跨轮不冲突、各自 run_id 正确；
   - 默认 results/evidence 返回**最新** run；带 `run_id` 返回历史 run；
   - 重跑后旧结果仍可查（不被删）；
   - `GET /tasks/{id}/runs` 列出多次运行；
   - 删除任务后该任务所有证据/结果/run 物理删除；
   - 迁移测试：构造「旧 schema」库（evidence 无 run_id 列 + analysis_results.task_id 唯一索引），跑 `initialize_database` 后列已加、唯一索引已删、可插入第二条结果、旧证据 run_id 回填。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `./.venv/bin/python scripts/evaluate_demo.py` 仍 3/3，coverage/invalid 不变（单次运行语义不变）。
4. `cd frontend && npm run type-check && npm run build` 通过。
报告：模型/迁移改动、run 解析与证据过滤策略、历史 API 契约、删除语义、迁移测试结果、demo 不回归。并明确说明：旧本地库会被自动迁移；若迁移失败的兜底建议（重建 data/app.db）。不要 git commit。
