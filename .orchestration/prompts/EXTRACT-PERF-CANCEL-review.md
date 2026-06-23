# 代码审核（只读，禁止修改）：抽取并发 + 进度 + 可取消

审核新增的"真实抽取批次并发 + 进度反馈 + 协作式取消"。最高风险：①并发下的线程/DB 安全；②取消语义是否**真的立即停止后续 LLM 调用**（止血）；③回归。

## 范围
`backend/app/skills/intelligence_extract.py`、`backend/app/services/orchestrator.py`、`backend/app/api/analysis.py`、`backend/app/config.py`、`backend/app/models.py`、`backend/app/database.py`、相关测试、前端 `TaskWorkbenchView.vue`。

## 必查项（只报真实问题，给文件:行）
1. **线程/DB 安全（最关键）**：worker 线程是否**绝不触碰 SQLAlchemy session/DB**（SQLAlchemy Session 非线程安全）？`progress_callback` 与 DB 更新是否只在主线程（编排器背景任务线程）执行？`cancel_check` 是否用**独立短生命周期 session**读取（能看到取消线程已提交的 cancel_requested）、且不复用编排器主 session？ThreadPoolExecutor 每批是否各自新建 httpx client（不共享可变状态）？
2. **取消是否真止血**：取消后是否**不再发起新的 LLM 调用**？`as_completed` 循环检测到取消是否 `shutdown(cancel_futures=True)` / `future.cancel()` 阻止未开始的批次？已在飞行中的批次最多再跑当前这批（可接受），但不应继续提交剩余 271 批。是否**不进入冲突/报告**阶段。给出取消后最多还会发生多少次 LLM 调用的分析。
3. **取消标志生命周期**：新 run 启动是否重置 `cancel_requested=False`（避免历史标志误杀新 run）？取消端点是否只作用于"运行中"的最新 run、鉴权正确、无运行中 run 友好报错？协作式取消（非杀线程）是否在合理检查点生效。
4. **进度映射**：progress 是否单调、clamp 在 55..70、total=0 不除零、单批(demo)时 total=1 行为正常？current_step 文案安全（不含敏感信息）。
5. **迁移**：`task_runs.cancel_requested` ADD COLUMN 幂等、仅 SQLite、try/except 脱敏、默认 0；旧库可用。
6. **收尾/锁**：取消/异常后单运行锁是否释放（`_force_fail_unfinished_run`/finally）、run 终态正确（failed+cancelled 文案）、不重复覆盖、不残留"running"阻塞后续。
7. **回归**：mock 单批路径不变；evaluate_demo 3/3、coverage/invalid 不变；并发不破坏 `_merge_extractions` 的去重/字段引用合并/event_id 分配确定性（注意并发下合并顺序是否影响 event_id 稳定性——指出任何不确定性）。
8. **资源**：executor 是否在所有路径（成功/取消/异常）正确关闭，无线程泄漏；EXTRACT_CONCURRENCY clamp 生效。

## 输出
每条发现：严重级（BLOCKER/MAJOR/MINOR/NIT）、文件:行、问题、修复建议。末行总评 PASS / PASS-WITH-FIXES / FAIL + 合并前必修项。只报真实问题。
