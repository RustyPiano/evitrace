# 复审（只读，禁止修改/禁止 git）：P0b 三条审核意见的修复

上一轮审核（PASS-WITH-FIXES）提出三项，现已处理。请只针对这三项的修复正确性复审，给 文件:行 + 严重级，末行总评 PASS / PASS-WITH-FIXES / FAIL。

## 待核修复
1. **P1 input_hash 纳入 task objective**（`backend/app/skills/intelligence_extract.py` 的 `batch_hash`/`objective`）：
   - hash 现在是否包含 `task.objective`？改 objective 后续跑是否会因 hash 失配而**不复用**旧目标的已完成批（避免语义混合）？分隔符是否避免歧义（如不同字段拼接产生碰撞）？同 objective 重跑是否仍稳定命中缓存（续跑正常工作）？
   - 新测试 `test_real_extraction_objective_change_invalidates_done_cache` 是否真正验证「目标变→重抽」。
2. **P2 resume_run 重置展示型字段**（`backend/app/services/orchestrator.py` 的 `resume_run`）：
   - 是否重置 `progress=0`、`total_batches/done_batches/failed_batches/estimated_input_tokens=0`、`started_at`，并**保留** `resumable=True` 与已有 `extraction_batches`？
   - 这样续跑时 `_update_state` 的 `max(run.progress, progress)` 是否不再卡在旧值；恢复后批次计数会被 set_plan/抽取结果重新写入，无过期暴露？
   - 测试 `test_resume_run_endpoint_resets_run_and_records_audit` 是否新增了 progress/批次计数=0 的断言。
3. **P3 解析跳过边界**：选择「明确接受」。`execute_run` 是否加了注释说明启发式与边界、`docs/DEPLOYMENT.md` 是否有相应说明？此选择是否会引入新风险（注意：`parse_all_files` 每文件解析前 `delete_file_evidence(run_id=...)`，即重解析本身幂等安全）。

## 附带回归
- 这些改动是否破坏既有 P0b 行为（部分结果/全失败/upsert/线程安全/迁移）？
- 是否引入与现有测试矛盾的断言？

只报真实问题。
