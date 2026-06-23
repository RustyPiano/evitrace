# 任务：真实抽取——批次并发 + 进度反馈 + 可取消（修复"卡在55%/持续扣费"）

背景（已诊断）：真实模式下要素抽取按每 30 条证据一次 LLM 调用、**串行**处理所有批次；大输入（如 61 文档 → 8121 证据 → 271 批）会让进度长时间停在 55%（仅在全部批次完成后才到 70%），且持续真实调用扣费。本次**不加证据上限**（保留全量覆盖），改为：①批次**并发**提速；②抽取期间**按批次更新进度**（不再卡死）；③**可取消**——用户可中断正在运行的分析以立即止血。既有测试不回归、demo 3/3、不写真实 key、不 git commit。

## 1) 配置（`backend/app/config.py`）
- 新增 `EXTRACT_CONCURRENCY`（默认 4，clamp 到 1..16）：抽取批次并发数。

## 2) 模型 + 迁移（`backend/app/models.py` + `backend/app/database.py`）
- `TaskRun` 新增 `cancel_requested: Mapped[bool]`（默认 False, nullable=False, server/default False）。
- `database.py` SQLite 幂等迁移：若 `task_runs` 无 `cancel_requested` 列 → `ALTER TABLE task_runs ADD COLUMN cancel_requested BOOLEAN NOT NULL DEFAULT 0`（与现有迁移同风格，try/except、脱敏、仅 SQLite）。

## 3) 抽取并发 + 回调（`backend/app/skills/intelligence_extract.py`）
- `IntelligenceExtractSkill.run` 增加可选参数：`progress_callback: Callable[[int,int],None] | None = None`、`cancel_check: Callable[[],bool] | None = None`。
- `_run_real_extraction`：
  - 用 `concurrent.futures.ThreadPoolExecutor(max_workers=settings.extract_concurrency)` 并发提交所有批次（每批仍调 `client.generate_json`，其内部各自新建 httpx client，线程安全）。
  - 用 `as_completed` 在**主线程**收集结果：每完成一批 → `done+=1`；若 `progress_callback` 调 `progress_callback(done, total)`；若 `cancel_check and cancel_check()` → 取消未完成 future（`future.cancel()` + executor shutdown(cancel_futures=True)）、停止收集，抛 `RunCancelled`。
  - **DB/进度更新只在主线程**（progress_callback 由编排器实现并在主线程被调用），worker 线程只做纯 LLM 调用、返回 ExtractionResult，不碰 DB。
  - 结果合并 `_merge_extractions`（顺序无关，保持现有去重/字段引用合并）。保留每批 sanitize warnings。
- 定义/复用一个 `RunCancelled(Exception)`（放 `app/services/orchestrator.py` 或 `app/skills/base.py`，供编排器捕获）。mock 路径与单批路径行为不变。

## 4) 编排器（`backend/app/services/orchestrator.py`）
- 新增模块级 `class RunCancelled(Exception)`（若放这里）。
- run 启动时（start_run/_create_run_without_user 建 run 后）**重置** `cancel_requested=False`，避免历史取消标志误杀新 run。
- 提供给抽取的回调：
  - `progress_callback(done,total)`：`_update_state(progress = 55 + int(15*done/max(total,1)) , task_status=EXTRACTING, current_step=f"extracting {done}/{total}")`（progress 单调，clamp ≤70）。在背景任务线程内执行，复用现有 db/session，安全。
  - `cancel_check()`：用**新建短生命周期** session 读取该 run 的 `cancel_requested`（`with SessionLocal() as s: r=s.get(TaskRun, run_id); return bool(r and r.cancel_requested)`），以便看到取消请求线程已提交的标志。
- 在关键步骤边界检查取消（解析后、抽取前、抽取后、冲突前）：若 `cancel_check()` 为真或抽取抛 `RunCancelled` → 跳出，按"已取消"收尾。
- 解析阶段（10–45%）也尽量可取消：在 `parse_all_files` 的文件循环间检查 cancel（可给 parse_service 传一个 cancel_check，或在编排器分文件调用之间检查——以低风险方式实现；若改动大，至少保证抽取可取消 + 解析后边界可取消）。
- **取消收尾**：捕获 `RunCancelled` → run.status=`RUN_STATUS_FAILED`、current_step=`cancelled`、error_message=`"分析已手动取消"`、finished_at；task.status=`TASK_STATUS_FAILED`、last_error 同；释放单运行锁（finally 已有 _force_fail_unfinished_run，确认其不会覆盖为其它信息或重复）。**立即停止后续 LLM 调用**（不再进入冲突/报告）。

## 5) 取消 API（`backend/app/api/analysis.py`）
- `POST /tasks/{task_id}/runs/cancel`：鉴权 `ensure_task_access`；找该任务**当前运行中**（status in TASK_RUNNING/RUN running|queued）的最新 run，置 `cancel_requested=True`（提交），记审计 `analysis_cancel_requested`。返回 `{data:{run_id, cancel_requested:true}, message}`。无运行中 run → 409/404 友好提示。
- 不直接杀线程：协作式取消（背景任务在下个检查点优雅停止）。

## 6) 前端（`frontend/src/views/TaskWorkbenchView.vue` 等）
- 运行进行中（轮询 `/runs/latest` 状态为运行中）时，显示「停止分析」按钮 → `POST /tasks/{id}/runs/cancel`；点击后置按钮 loading、提示"正在停止…"，继续轮询直至终态。
- 进度条/文案展示 `current_step`（现在含 `extracting i/N`）与 progress（55→70 递增）。type-check/build 通过；不硬编码密钥/URL。

## 验证（实际执行，最终消息逐条报告；单测用可注入 mock，不连真实外网）
1. `cd backend && ./.venv/bin/pytest -q` 全绿。新增测试：
   - 并发抽取：注入一个假 llm_client（generate_json 计数/可延时），多批并发完成、结果合并正确、`progress_callback` 被调 total 次、done 单调到 total。
   - 取消：cancel_check 在第 k 批后返回 True → 抛 `RunCancelled`、未再调用更多 generate_json（计数 ≤ 已提交）、编排器收尾为 failed/cancelled、不进入冲突/报告。
   - 迁移：旧 schema（task_runs 无 cancel_requested）→ initialize_database 后列存在、默认 0。
   - 取消端点：运行中 run 置 cancel_requested、审计记录；无运行中 run 友好报错。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `./.venv/bin/python scripts/evaluate_demo.py` 仍 3/3（小输入单批，行为不变；progress_callback total=1）。
4. `cd frontend && npm run type-check && npm run build` 通过。
报告：并发实现与线程/DB 安全边界（回调只在主线程碰 DB、cancel_check 用独立 session）、进度映射、取消协作式语义与收尾、迁移、端点契约、前端按钮。不要 git commit。
