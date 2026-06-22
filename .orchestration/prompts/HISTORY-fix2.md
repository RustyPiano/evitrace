# 任务：修复历史保留复审发现的新 MAJOR（独立 parse 端点会删历史证据）

复审确认前 4 项已闭合，但发现新 MAJOR：独立端点 `POST /tasks/{id}/parse`（`backend/app/api/tasks.py:65-86` → `parse_service.parse_task_files_for_endpoint` → `parse_all_files(task_id)`，**不传 run_id**）。run_id=None 时 `result_service.delete_file_evidence(file_id, run_id=None)`（`result_service.py:120-124`）**删除该 file 的全部 evidence（跨所有运行）**，而历史 `AnalysisResult` 仍在 → 破坏历史保留链路。该端点前端未使用，是预解析/遗留路径。

目标：让独立 parse 端点也**在一个真实 run 下运行**，全系统统一按 run 作用域，**彻底消除 run_id=None 的证据删除/派生清理路径**。不要 git commit；既有测试不回归、demo 3/3。

## 方案：独立 parse 端点分配并使用一个 run
1. `backend/app/api/tasks.py` 的 `parse_task_files_for_endpoint` 触发处 / `backend/app/services/parse_service.py`：
   - 在已有 `run_guard.single_run_start_lock()` 内创建一个 `TaskRun`（参照 `orchestrator._create_run_without_user` 的创建方式：status=running 或 queued、started_at、plan 可省略或简单填充），拿到 `run_id`。
   - 后台任务改为携带该 `run_id`：`parse_task_files_for_endpoint(task_id, run_id)` → `parse_all_files(task_id, run_id=run_id, ...)`。
   - 解析**成功**后把该 run 置为**终态**（如 `RUN_STATUS_SUCCEEDED`，current_step=`parsed`，progress=100，finished_at=now）；失败置 `RUN_STATUS_FAILED` + 脱敏 error。确保不会被 `recover_interrupted_runs` 误判（终态即可）。task.status 维持原有「解析完成/就绪/失败」语义不变。
   - 该 run 没有 AnalysisResult，属正常：`list_runs` 标 `has_result=False`，`resolve_result` 自动忽略它。
2. **消除 run_id=None 危险路径**：
   - `delete_file_evidence`：保留签名，但**额外加固**——当 `run_id is None` 时只删除 `Evidence.run_id.is_(None)` 的行（绝不再跨 run 全删）。这样即使别处遗漏传 run 也不会损坏历史。
   - 确认 `_cleanup_file_derived_artifacts` 与 `video_parse` 帧/音频路径在本端点下都拿到真实 `run_id`（落到 `derived/runs/{run_id}/...`），不再出现 `derived/runs/None`。
3. 不改变主分析流程（`POST /tasks/{id}/runs` → `execute_run`）的现有行为。

## 测试
- 新增/更新：任务已有一次成功分析（含 evidence + AnalysisResult）后，调用 `POST /tasks/{id}/parse` 再解析 → **历史运行的 evidence 仍在**（按历史 run_id 仍可查）、历史 `AnalysisResult` 仍可解析其证据；新 parse run 出现在 `GET /tasks/{id}/runs` 且 `has_result=False`。
- `delete_file_evidence(run_id=None)` 只删 run-less 行的单元测试。
- 既有 parse 端点相关测试更新（现在会创建 run）。

## 验证（实际执行，最终消息逐条报告）
1. `cd backend && ./.venv/bin/pytest -q` 全绿。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `backend/.venv/bin/python scripts/evaluate_demo.py` 仍 3/3，coverage/invalid 不变。
4. `cd frontend && npm run type-check && npm run build` 通过（若动前端；通常不需）。
报告：parse 端点 run 化实现、run 终态处理、delete_file_evidence 加固、测试与验证结果。不要 git commit。
