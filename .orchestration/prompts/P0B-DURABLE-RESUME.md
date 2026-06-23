# 任务（P0b）：持久化批次 + 部分结果 + 断点续跑 + 预算surfacing

背景：真实大语料抽取（~271 批）目前**全程驻内存、全有或全无**：一批最终失败就抛穿 → 整轮 run failed → 已完成 200+ 批结果全丢、重跑又从头烧钱。本任务把抽取做成**可持久、可部分、可续跑**：每批结果即时入库；单批永久失败不炸全局→产出部分结果+披露；run 可断点续跑（只补未完成批、复用已完成批）；并把批数/预算 surfacing 到前端。依赖 P0a（已合入本分支：LLM client 已能区分 LLM_RATE_LIMITED/LOCAL_MODEL_UNAVAILABLE 可重试 vs LLM_REQUEST_INVALID/LLM_INSUFFICIENT_BALANCE 致命）。

**两条铁律（最高优先，违背即 FAIL）**：
1. **线程安全**：worker 线程**只调 LLM、返回结果或抛异常，绝不碰 DB/session**。所有批次持久化只在**主收集循环**（编排器后台线程，即调用 skill 的那个线程）里发生。
2. **确定性**：合并永远按 `batch_index` 升序；给定「当前存在的批次集合」→ `event_id` 分配确定可复现（续跑补齐全部批后整份结果会重算并替换，允许与部分版不同）。

mock 路径完全不变、demo 3/3、不写真实 key、不 git commit。

## 1) 数据模型（`backend/app/models.py`）
### 新表 `ExtractionBatch`
```python
class ExtractionBatch(Base):
    __tablename__ = "extraction_batches"
    __table_args__ = (UniqueConstraint("run_id", "batch_index", name="uq_extraction_batch_run_index"),)
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=uuid_text)
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("task_runs.id"), nullable=False, index=True)
    batch_index: Mapped[int] = mapped_column(Integer, nullable=False)
    input_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # "done" | "failed"
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)   # 本批 sanitized ExtractionResult JSON
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at / updated_at（同其它表，default=utc_now / onupdate=utc_now）
```
加入 `__all__`。新表由 `Base.metadata.create_all` 自动建（新库无需迁移）。

### `TaskRun` 新增列
- `resumable: Mapped[bool]`（default False, server_default "0", nullable=False）
- `total_batches: Mapped[int]`（default 0, server_default "0", nullable=False）
- `done_batches: Mapped[int]`（default 0, server_default "0", nullable=False）
- `failed_batches: Mapped[int]`（default 0, server_default "0", nullable=False）
- `estimated_input_tokens: Mapped[int]`（default 0, server_default "0", nullable=False）

## 2) 迁移（`backend/app/database.py` 的 `_migrate_sqlite_schema`）
对 `task_runs` 五个新列各做幂等 ADD COLUMN（仿现有 `cancel_requested` 写法，try/except、脱敏日志、仅 SQLite）：
```
ALTER TABLE task_runs ADD COLUMN resumable BOOLEAN NOT NULL DEFAULT 0
ALTER TABLE task_runs ADD COLUMN total_batches INTEGER NOT NULL DEFAULT 0
ALTER TABLE task_runs ADD COLUMN done_batches INTEGER NOT NULL DEFAULT 0
ALTER TABLE task_runs ADD COLUMN failed_batches INTEGER NOT NULL DEFAULT 0
ALTER TABLE task_runs ADD COLUMN estimated_input_tokens INTEGER NOT NULL DEFAULT 0
```
（`extraction_batches` 表不需 ALTER，create_all 已建。）

## 3) 抽取 skill 持久化/续跑（`backend/app/skills/intelligence_extract.py`）
### 持久化接口（定义在 `skills/base.py`，与 `RunCancelled` 同处）
```python
class ExtractionPersistence(Protocol):
    def load_done(self) -> dict[int, tuple[str, dict]]: ...        # {batch_index: (input_hash, result_json_dict)}
    def record_batch(self, batch_index: int, input_hash: str, status: str,
                     result: dict | None, error_code: str | None, error_message: str | None) -> None: ...
    def set_plan(self, total_batches: int, estimated_input_tokens: int) -> None: ...
```
（用 `typing.Protocol` 或抽象基类皆可；skill 只调用这三个方法。）

### `IntelligenceExtractSkill.run` / `_run_real_extraction` 增参
- `run(..., persistence: ExtractionPersistence | None = None)`，透传给 `_run_real_extraction`。
- 定义模块常量 `PROMPT_VERSION = "extract-v1"`（提示词或 schema 变更时手动 bump，使旧缓存失效）。
- `input_hash(batch)`：`sha256` of `PROMPT_VERSION + "|" + model + "|" + "\n".join(f"{e['display_id']}:{_evidence_text(e)}" for e in batch)`（稳定、可复现）。

### `_run_real_extraction` 新流程（有界窗口保留，叠加持久化 + 优雅降级）
1. prefilter（已有）→ `batches = _batch_evidence(filtered_items)`；`total=len(batches)`。
2. 计算每批 `input_hash` 与该批的预估输入字符数（`len(system_prompt)+len(user_prompt)`）；`estimated_input_tokens = 总字符数 // 3`（粗略，明确是估算）。
3. 若 `persistence`：`persistence.set_plan(total, estimated_input_tokens)`（**在主线程**，开跑前调用，让前端早早看到批数/预算）；`done_map = persistence.load_done()`。否则 `done_map = {}`。
4. **预填已完成批**：对每个 index，若 `index in done_map` 且 `done_map[index][0] == input_hash[index]` → 直接把其 `result_json_dict` 反序列化为 ExtractionResult 放入 `results[index]`、`done += 1`、`progress_callback(done,total)`；该批**不再提交 LLM**。
5. 其余未完成批走原有**有界窗口并发**（≤ `extract_concurrency` 在飞；提交前 cancel_check）。worker `extract_batch` 仍**纯调 LLM**、返回 `(sanitized_result, warnings)` 或抛异常。
6. **主收集循环**（主线程）逐个处理 completed future：
   - 成功：`results[index]=sanitized`；`persistence.record_batch(index, hash, "done", sanitized.model_dump(mode="json"), None, None)`（若 persistence）；`done+=1`；`progress_callback`。
   - **失败（捕获 `Exception` 但 `RunCancelled` 必须继续向上抛、不当作批失败）**：记 `failed_indices.add(index)`；`persistence.record_batch(index, hash, "failed", None, <error_code 若 AppError 则 exc.code 否则 type 名>, str(exc)[:500])`；**continue，不抛穿**。继续收集其余批。
   - 收集完一波后 cancel_check（真则 raise RunCancelled）；再补投递到窗口满。
   - `finally: executor.shutdown(wait=False, cancel_futures=True)`（保留）。
7. 合并：`extractions = [results[i] for i in sorted(results)]`（只含成功批，确定性序）→ `_merge_extractions`。
8. 统计：`done_count=len(results)`、`failed_count=total-done_count`（=len(failed_indices)）。
   - 若 `failed_count > 0`：warnings 追加 `f"部分抽取失败：{done_count}/{total} 批成功、{failed_count} 批失败（可在工作台『继续分析』续跑补齐）"`。
   - 若 `done_count == 0 且 total > 0`：照旧追加「未抽取到任何要素」并让上层据 stats 判失败。
9. **返回值扩展**：`_run_real_extraction` 返回 `(merged, warnings, stats)`，`stats = {"total": total, "done": done_count, "failed": failed_count}`。`run()` 把 stats 放进 `SkillResult.metrics`（如 `batch_total/batch_done/batch_failed`），并在 `data` 里照旧给 entities/events/timeline。**mock 路径**：stats 取 `{"total":1,"done":1,"failed":0}`，行为不变。

> 注意：record_batch/load_done/set_plan 全部在**主线程**（步骤 3/4/6 都在收集循环或其外，绝不在 worker 内）。worker 只跑 `extract_batch`。

## 4) 编排器（`backend/app/services/orchestrator.py`）
### 持久化实现
实现一个 `_RunBatchPersistence`（用编排器 `execute_run` 的 `db` 与 `run_id`）：
- `load_done()`：查 `ExtractionBatch.status=="done"` 的行 → `{batch_index: (input_hash, json.loads(result_json))}`。
- `record_batch(...)`：按 `(run_id, batch_index)` **upsert**（存在则更新 status/result_json/error/attempt_count+1/updated_at，不存在则插入）；`db.commit()`。
- `set_plan(total, est)`：写 `run.total_batches=total`、`run.estimated_input_tokens=est`、commit。
全部在后台线程调用（execute_run 所在线程），与 `db` 同线程，安全。

### `execute_run` 改造
- **解析可跳过（续跑）**：进入 parse 阶段前，若该 run 已有证据（`db.query(Evidence).filter(Evidence.run_id==run.id).count() > 0`）→ **跳过 `parse_all_files`**，直接复用既有证据（log "resume: reuse N evidence"），progress 直接到 45。否则照常解析。
- 抽取调用：`IntelligenceExtractSkill().run(context, payload, progress_callback=extract_progress, cancel_check=cancel_check, persistence=_RunBatchPersistence(db, run.id))`。
- 抽取后：从 SkillResult.metrics 读 batch_total/done/failed → 写 `run.total_batches/done_batches/failed_batches`。
- **部分/失败判定**（不引入新状态，用 `resumable` 标志）：
  - `done==0 且 total>0`（全失败）→ 视为失败：raise AppError("ANALYSIS_FAILED", "全部抽取批次失败，可在工作台续跑")，但在 except 收尾里把 `run.resumable=True`（见下）。
  - `failed>0 且 done>0`（部分）→ **继续**走冲突/报告（用已得 events 产出部分报告），最终 `RUN_STATUS_SUCCEEDED`/`awaiting_review`，但置 `run.resumable=True`，warnings 已含部分披露。
  - `failed==0`（全成功）→ 照旧 succeeded，`run.resumable=False`。
- **AnalysisResult upsert**：结束写结果时，若该 run_id 已有 AnalysisResult（续跑场景）→ 更新其各字段；否则新建。（避免重复行。）
- **收尾里的 resumable**：`except RunCancelled` 与通用 `except Exception` 分支中，对「抽取相关失败/取消」把 `run.resumable=True`（取消也允许续跑补齐）。`_force_fail_unfinished_run` 保持，但不要把 resumable 又抹掉。
- 进度文案：`extract_progress` 的 current_step 改为 `f"extracting {done}/{total}"`（已有）；可附失败数。

### `recover_interrupted_runs`
- 把「running/queued 中断」的 run 标 failed 时，**同时置 `resumable=True`**、message 用现有 INTERRUPTED_MESSAGE（语义：中断可续跑）。这样进程重启后已完成批仍在库，用户可续跑只补剩余。

## 5) 续跑 API（`backend/app/api/analysis.py`）
- `POST /tasks/{task_id}/runs/{run_id}/resume`：
  - `ensure_task_access`；取该 run，不存在 404。
  - 若 `not run.resumable` → 409 `RUN_NOT_RESUMABLE` 「该运行不可续跑」。
  - `orchestrator` 侧需要一个 `resume_run(db, task_id, run_id, current_user)`：校验单运行锁（`run_guard.ensure_no_active_run(db)`、无其它运行中任务）；重置 run：`status=RUN_STATUS_QUEUED, current_step="queued", cancel_requested=False, error_message=None, finished_at=None`（**保留 resumable=True 直到成功**、保留已有 extraction_batches）；task.status=queued；commit。
  - 审计 `analysis_resumed`；`background_tasks.add_task(orchestrator.execute_run, task_id, run_id)`；返回 `{data:{run_id, status:"queued"}, message}`。
- `serialize_run`（orchestrator）补字段：`resumable, total_batches, done_batches, failed_batches, estimated_input_tokens`。

## 6) 前端（`frontend/src/views/TaskWorkbenchView.vue` + 类型）
- `types`（`RunStatus`/对应接口）加：`resumable?: boolean; total_batches?: number; done_batches?: number; failed_batches?: number; estimated_input_tokens?: number`。
- 当最新 run 为终态（failed 或 succeeded）且 `resumable` → 显示「继续分析（续跑）」按钮 → `POST /tasks/{id}/runs/{run_id}/resume` → 置 loading、`startPolling()`；失败 toast。
- 进度区展示：`提取 {done_batches}/{total_batches}`，若 `failed_batches>0` 标注「失败 N（可续跑）」；若 `estimated_input_tokens>0` 显示「预计输入 ≈X token（估算）」。
- type-check/build 通过；不硬编码密钥/URL。

## 7) 文档（`docs/DEPLOYMENT.md` 性能与成本节追加一小段）
说明：抽取按批持久化、单批失败不再炸全局、可在工作台「继续分析」续跑（只补未完成批、复用已完成批、不重复烧钱）、进程中断后可续跑；以及 429 退避（P0a）配合续跑使大任务可恢复。

## 验证（实际执行，最终消息逐条报告；单测注入假 client/假持久化，不连真实外网、不真睡）
1. `cd backend && ./.venv/bin/pytest -q` 全绿。新增测试：
   - **批持久化+续跑**：注入假 client（按批返回不同 events）+ 真·内存或 SQLite 持久化；第一次跑令第 k 批抛异常 → 该批 record 为 failed、其余 done、返回部分结果 + 披露 warning、stats.failed==1；**第二次（续跑）**用同输入：load_done 命中已完成批（client 不再被这些批调用，计数核对）、失败批重跑成功 → 全 done、合并完整、event_id 确定。
   - **线程安全约束**（设计层）：worker 不接触 db——通过「record_batch 只在收集循环被调用」的测试/断言或代码结构保证；可用一个会在非主线程调用时报错的假持久化来断言只在主线程调用。
   - **input_hash 失配**：done 行 hash 与当前不一致 → 不复用、重新抽取。
   - **全失败**：所有批失败 → run 走失败路径且 `resumable=True`、无 AnalysisResult 或不产报告。
   - **迁移**：旧 schema（task_runs 无新列、无 extraction_batches 表）→ initialize_database 后列与表存在、默认值正确。
   - **resume 端点**：resumable=True 的 run 可续跑（重置+排队+审计）；resumable=False → 409；有运行中任务 → 409。
   - **recover_interrupted_runs**：running 中断 → failed + resumable=True。
   - **AnalysisResult upsert**：续跑后同 run_id 只有一行结果（更新而非新增）。
   - **回归**：mock 单批路径不变；conflict/report 不受影响。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `backend/.venv/bin/python scripts/evaluate_demo.py` 仍 3/3、coverage/invalid 不变。
4. `cd frontend && npm run type-check && npm run build` 通过。

报告：数据模型/迁移、持久化接口与**主线程约束**、续跑流程（解析跳过/load_done 复用/失败补跑）、部分结果与 resumable 语义、AnalysisResult upsert、resume 端点契约、recover 改动、前端续跑按钮与 surfacing、各测试结果。**不要 git commit。**
