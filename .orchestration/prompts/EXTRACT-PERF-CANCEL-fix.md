# 任务：修复抽取并发审核发现的 BLOCKER + MAJOR

审核 FAIL。`backend/app/skills/intelligence_extract.py` 的 `_run_real_extraction` 当前一次性 `submit` 全部批次 + `as_completed`，导致：①取消止血不紧（依赖 `shutdown(cancel_futures=True)` 取消队列，边界模糊；且批次异常时 `finally` 用 `cancel_futures=False` 会把剩余批次跑完，违背成本控制）；②`as_completed` 完成顺序非确定 → 合并顺序与 `event_id` 分配不稳定。改为**有界投递窗口 + 按批次序合并**。不要 git commit；既有测试不回归、demo 3/3。

## 改 `_run_real_extraction`（有界窗口）
用 `concurrent.futures` 的 `wait(..., return_when=FIRST_COMPLETED)` 实现**最多 `extract_concurrency` 个在飞**的滑动窗口：

要点：
- `batches = _batch_evidence(evidence_items)`；`total=len(batches)`。
- 维护 `pending: set[Future]`、`fut_index: dict[Future,int]`、`results: dict[int, ExtractionResult]`、`warnings`、`done=0`、`next_idx=0`。
- **预投递**：当 `len(pending) < concurrency and next_idx < total`：提交前先 `if cancel_check and cancel_check(): raise RunCancelled()`；`f=executor.submit(extract_batch, batches[next_idx])`；`fut_index[f]=next_idx`；`pending.add(f)`；`next_idx+=1`。
- **主循环**：`while pending:`
  - `completed, pending = wait(pending, return_when=FIRST_COMPLETED)`
  - 对每个 `future in completed`：`idx=fut_index.pop(future)`；`sanitized, w = future.result()`（异常向上抛，见下）；`results[idx]=sanitized`；`warnings.extend(w)`；`done+=1`；`if progress_callback: progress_callback(done,total)`。
  - 处理完这批 completed 后：`if cancel_check and cancel_check(): raise RunCancelled()`。
  - **再补投递**到窗口满：同预投递（含提交前 cancel_check）。
- **异常/取消/正常退出统一收尾**（`finally`）：`executor.shutdown(wait=False, cancel_futures=True)`——确保**未开始的批次一律取消**，不再发起新 LLM 调用（取消止血、异常 fail-fast 都满足）。`future.result()` 抛非取消异常时，沿用现有语义向上传播（run() 捕获→ success=False），但 finally 已取消剩余批次，不会再烧钱。
- 这样**取消后最多再完成 `extract_concurrency` 个在飞批次**（已发出的 HTTP 无法强杀，可接受），未开始的全部取消。

## 按批次序合并（确定性）
- 收集完成后：`extractions = [results[i] for i in sorted(results)]`，再 `_merge_extractions(extractions)`。
- 取消时 `results` 只含已完成批次（按已完成 idx 排序）——取消路径直接 `raise RunCancelled`，不需要合并（编排器会丢弃该次结果）。正常路径用全部 `sorted(results)` 保证与串行同序、`event_id` 稳定。

## 验证（实际执行，最终消息逐条报告；单测用可注入假 client，不连真实外网）
1. `cd backend && ./.venv/bin/pytest -q` 全绿。新增/更新测试：
   - **取消止血**：注入会计数并可阻塞的假 client + 一个在第 1 批完成后即返回 True 的 cancel_check；断言取消后**新提交的批次数 ≤ 已完成 + extract_concurrency**（不会把全部 N 批都发出去）、抛 RunCancelled。
   - **fail-fast**：某批 result 抛异常时，剩余未开始批次不再被调用（计数受限），run() 返回 success=False。
   - **确定性**：乱序完成（假 client 对不同批次返回不同延时/顺序）下，合并后 event 顺序与 event_id 同「串行按 batch 序」结果一致。
   - 并发 happy path：progress_callback 调用 total 次、done 单调到 total、结果合并完整。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `backend/.venv/bin/python scripts/evaluate_demo.py` 仍 3/3、coverage/invalid 不变（单批 total=1）。
4. `cd frontend && npm run type-check && npm run build` 通过（若未动前端可注明）。
报告：有界窗口实现、取消/异常收尾（cancel_futures=True）、确定性合并、各测试结果。不要 git commit。
