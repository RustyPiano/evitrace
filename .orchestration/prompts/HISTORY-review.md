# 代码审核（只读，禁止修改）：保留历史运行

独立审核「重跑保留历史」改动。最高风险：①迁移破坏既有库或误删索引；②证据读取未按运行隔离 → **当前运行混入历史运行证据**（污染抽取/冲突/报告）；③display_id 跨运行冲突触发唯一约束；④默认未返回最新运行。

## 范围
`backend/app/models.py`、`backend/app/database.py`(迁移)、`backend/app/services/result_service.py`、`backend/app/services/parse_service.py`、`backend/app/services/orchestrator.py`、`backend/app/api/analysis.py`、`backend/app/api/evidence.py`、`backend/app/services/task_service.py`、相关测试、（若动）前端。

## 必查项（只报真实问题，给文件:行）
1. **证据按运行隔离（最关键）**：`orchestrator` 在一次运行内取证据是否**仅限本 run_id**（`Evidence.run_id == run.id`）？累积历史后，抽取/冲突/报告绝不能看到其它运行的证据。逐一确认 `_list_evidence`、`analysis._evidence_payload`、`result_service.list_task_evidence/index/detail/source/frame` 都按「解析出的目标 run（默认最新）」过滤，无任何遗漏的 task 级全量查询导致跨运行泄漏。
2. **display_id 不冲突**：`next_display_id` 仍 task 级递增（跨运行继续编号），新运行不会与旧运行 display_id 撞 `(task_id, display_id)` 唯一约束。确认连续两次运行的编号单调且唯一。
3. **迁移安全/幂等**：`initialize_database` 的 SQLite 迁移——`ADD COLUMN run_id` 仅在缺列时执行；删除 analysis_results 的 task_id 唯一索引时，**只**删「唯一且仅含 task_id」的索引（不要误删其它索引/约束）；回填 SQL 是否安全（无语法错、NULL 安全）；全部 try/except 不致命、不打印路径/凭证；非 SQLite 后端是否跳过。多次启动是否幂等无副作用。
4. **默认最新 + 历史访问**：`resolve_result` 无 run_id 时取**最新**（created_at desc，tie 用 TaskRun.started_at）；带 run_id 取指定且校验归属（越权/跨任务 run_id 返回 404 而非泄漏）。`GET /tasks/{id}/runs` 列表、results/report?run_id= 是否正确鉴权（ensure_task_access）。
5. **重跑不删 + 删任务级联**：确认 `_delete_previous_outputs` 不再于重跑调用；旧结果/证据保留。删除任务仍物理删除该任务全部 Evidence/AnalysisResult/TaskRun/TaskFile（不残留）。
6. **报告文件**：历史 run 下载是否正确（latest.md 为最新；历史用 `{run_id}.md` 或从 DB markdown 落盘）；文件名/时间戳用对应结果时间；无路径穿越。
7. **回归**：单次运行语义不变；evaluate_demo 3/3、coverage/invalid 不变；既有 analysis/evidence 测试仍通过；前端 type-check/build（若动）通过。
8. **并发/约束**：AnalysisResult 去唯一后是否有别处假设「每任务一条结果」而 `.first()` 误取旧结果（应一律经 resolve_result 取最新或指定）。

## 输出
每条发现：严重级（BLOCKER/MAJOR/MINOR/NIT）、文件:行、问题、最小修复建议。重点给出能触发「跨运行证据泄漏」或「迁移破坏」的具体输入/场景（若有）。末行总评 PASS / PASS-WITH-FIXES / FAIL + 合并前必修项。只报真实问题。
