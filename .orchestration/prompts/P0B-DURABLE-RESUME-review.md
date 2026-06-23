# 代码审核（只读，禁止修改/禁止 git）：P0b 持久化批次 + 部分结果 + 断点续跑

审核分支 `feat/big-task-resilience` 相对 `main` 的改动（含 P0a 已合入；本次重点是 P0b：models/database/orchestrator/intelligence_extract/skills.base/analysis API/前端/测试）。只报真实问题，给 文件:行 + 严重级，末行总评 PASS / PASS-WITH-FIXES / FAIL + 必修项。

## 最高风险必查
1. **线程安全（最关键）**：`record_batch / load_done / set_plan` 是否**全部只在主线程**（编排器后台线程 / skill 主收集循环）被调用，worker 线程内的 `extract_batch` 是否**绝不触碰 DB/session/persistence**？`_RunBatchPersistence` 复用 `execute_run` 的 `db`，与该 db 是否始终同线程？给出反例风险。
2. **续跑正确性与确定性**：`input_hash`（PROMPT_VERSION+model+证据内容）是否稳定可复现？`load_done` 命中且 hash 一致才复用、失配则重抽——是否正确？合并按 `batch_index` 升序、给定存在批集合 `event_id` 是否确定？续跑时 `_batch_evidence` 必须复现与首次相同的批次划分（依赖证据顺序 by display_id + 相同 prefilter/批量配置）——是否成立？配置变更导致 hash 失配是否安全（全部重抽，不崩）？
3. **部分/失败/续跑状态机**：全失败(done==0,total>0)→ run failed + resumable=True + 不写 AnalysisResult；部分(failed>0,done>0)→ 继续冲突/报告 + succeeded/awaiting_review + resumable=True；全成功→ resumable=False。取消/异常/中断→ resumable=True。这些是否一致、无矛盾？`_force_fail_unfinished_run`（finally）是否会**误抹 resumable** 或把已 succeeded/failed 的 run 再改写？（注意 except 已先置 failed，故 finally 的 status∈{queued,running} 条件应为假。）
4. **AnalysisResult upsert**：按 run_id 查找更新或新建——续跑后是否**只有一行**结果、字段被正确替换、task_id 不丢？
5. **解析跳过**：续跑时 `Evidence.run_id` 已有证据则跳过 `parse_all_files`——是否会漏掉「解析中途失败、证据不全」的情形（可接受但请指出）；progress 跳到 45 是否单调安全。
6. **resume 端点/锁**：`resume_run` 是否在 `single_run_start_lock` 内、校验 resumable/归属/单运行锁、重置字段正确（保留 resumable=True 与已有 extraction_batches）；非 resumable→409、跨任务 run→404、有运行中→409。
7. **迁移/模型**：5 个新列幂等 ADD COLUMN（仅 SQLite、try/except、脱敏）；`extraction_batches` 由 create_all 建；旧库升级安全；server_default 与默认一致。
8. **回归**：mock 单批路径不变（stats=1/1/0）；demo 3/3；冲突/报告不受影响；`serialize_run` 新字段不破坏既有前端；多次 `db.commit()`（record_batch/set_plan/_update_state）导致 ORM 对象 expire 后再访问 `run.*` 是否安全（无 DetachedInstance/StaleData）。
9. **资源/性能**：executor 各路径关闭；271 批每批一次 commit 的代价是否可接受（说明即可）。
10. **测试质量**：是否真覆盖「续跑复用已完成批（client 不再被这些批调用，计数核对）+ 失败批重抽 + event_id 确定 + 全失败 + resume 端点 + recover + upsert 单行 + 迁移」；有无 mock 掉关键逻辑导致假绿；线程安全是否有断言（如非主线程调用 persistence 即报错的测试）。

## 输出
逐条发现 + 末行总评。只报真实问题。
