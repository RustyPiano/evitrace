# 任务（P1a）：进度按已处理推进 + 全局 429 冷却 + 持续限流熔断

背景（已确诊）：免费档模型限流，一次 142 批里 118 批 429 失败。三个硬伤：①进度只在批次**成功**时推进（失败批不推进）→ 进度条假死在 ~57%；②各批独立退避、彼此仍并发猛打，限流窗口里互相踩；③119 个注定失败的批各退避 5 次（每次最多 30s）→ 几十分钟「慢性死亡」。本任务在**不改并发主结构的前提下**修这三点。依赖 P0a：限流异常 `AppError(code="LLM_RATE_LIMITED")` 上带 `retry_after` 属性（`getattr(exc,"retry_after",None)`，秒或 None）。不连真实外网、不真睡（测试注入）、mock 路径不变、demo 3/3、不写真实 key、不 git commit。

## 范围
`backend/app/skills/intelligence_extract.py`（`_run_real_extraction`）、`backend/app/services/orchestrator.py`（`extract_progress` 回调）、`backend/app/config.py`、相关测试、`.env.example`/`docs`。

## 1) 配置（`config.py`，Field+alias+clamp 校验器，同现有风格）
- `extract_rate_limit_cooldown_sec: float`，alias `EXTRACT_RATE_LIMIT_COOLDOWN_SEC`，默认 `5.0`，clamp `0.0..120.0`（无 Retry-After 时的全局冷却兜底秒数）。
- `extract_rate_limit_circuit_breaker: int`，alias `EXTRACT_RATE_LIMIT_CIRCUIT_BREAKER`，默认 `8`，clamp `0..1000`（连续多少个限流失败后停止提交剩余批；0=禁用熔断）。

## 2) 进度回调改为按「已处理 = 成功+失败」推进
- `progress_callback` 签名改为 `Callable[[int, int, int], None]`，参数 `(done, failed, total)`。
- `_run_real_extraction`：每**记录完一个批次结果**（无论 done 或 failed），都调用 `progress_callback(done, failed, total)`（含预填的已完成缓存批：预填阶段也按 done 调用）。
- `orchestrator.execute_run` 的 `extract_progress(done, failed, total)`：`processed = done + failed`；`progress = min(70, 55 + int(15 * processed / max(total, 1)))`；`current_step = f"extracting {processed}/{total}"`（failed>0 时追加 ` 失败{failed}`）。**顺便**把 `run.done_batches=done`、`run.failed_batches=failed` 一起写（live 反映，不再等抽取结束才更新）——仍在后台线程、复用 db，安全。
- mock 路径**保持不变**（当前就不调用 progress_callback，不要新增调用）；stats 仍 `{"total":1,"done":1,"failed":0,"aborted":False}`。

## 3) 全局 429 冷却（避免并发在限流窗口互相踩）
在 `_run_real_extraction` 维护共享 `cooldown_until: float`（用 `time.monotonic()`，初始 0）与可注入的 `sleep_fn`（默认 `time.sleep`）/`monotonic_fn`（默认 `time.monotonic`，便于测试）。
- 当某批失败且 `exc.code == "LLM_RATE_LIMITED"`：`wait_s = getattr(exc, "retry_after", None) or settings.extract_rate_limit_cooldown_sec`；`cooldown_until = max(cooldown_until, monotonic() + wait_s)`。
- **提交前遵守冷却**：`submit_until_window_full` 在 `executor.submit` 之前，若 `monotonic() < cooldown_until` → 本轮不再提交（return），把提交推迟到冷却结束。
- **主循环避免空转/早退**：当没有在飞 future（`pending` 空）但仍有未提交批（`next_idx < total` 且未熔断）且处于冷却中 → **分块 sleep**（每段 ≤0.5s，循环检查 `cancel_check`，到期或取消即退出）直到 `monotonic() >= cooldown_until`，再继续提交。确保：不会因冷却导致 `while` 提前结束、不会忙等、cancel 仍及时。

## 4) 持续限流熔断（避免几十分钟假死）
- 维护 `consecutive_rate_limited: int`：批 done → 归 0；批 failed 且 code==LLM_RATE_LIMITED → +1（其它 error_code 的失败不计入熔断，但仍记录 failed）。
- 若 `settings.extract_rate_limit_circuit_breaker > 0` 且 `consecutive_rate_limited >= 阈值`：设 `aborted = True`，**停止提交任何新批**（submit 直接 return），让已在飞批跑完后退出主循环。剩余未提交批**不记录为 failed**（它们是「未处理」，续跑时会跑）。
- 退出后：若 `aborted`，向 warnings 追加 `f"上游持续限流，已停止提交剩余批次（已完成 {done} 批、失败 {failed} 批，共 {total} 批；请降低并发/减少证据后在工作台『继续分析』续跑）"`。
- **stats 语义**：返回 `{"total": total, "done": done_count, "failed": failed_count, "aborted": aborted}`。其中 `failed_count` 只统计**实际记录为 failed** 的批（不含因熔断未提交的）。`done_count + failed_count` 可能 < total（熔断时）。`_merge_extractions` 只合并已完成批，确定性不变。

## 5) 编排器对 aborted 的处理（`execute_run`）
- 读 `extract_result.metrics`：除 batch_total/done/failed 外，新增读取 `batch_aborted`（skill 把 stats["aborted"] 放进 metrics["batch_aborted"]，bool）。
- 现有判定保持：`done==0 且 total>0` → 失败+resumable+无结果；`done>0` 且（failed>0 **或 aborted**）→ 部分结果+resumable（产出已得部分的冲突/报告）；全成功且未 aborted → resumable=False。
- 即：**aborted 视作「部分完成、可续跑」**，run 置 resumable=True，warnings 已含披露。

## 6) 主循环目标结构（参考，保持有界窗口 + 上述冷却/熔断）
```python
processed_done = 0; processed_failed = 0
consecutive_rl = 0; cooldown_until = 0.0; aborted = False
# 预填已完成缓存批（按 done 计数并回调 (done,0,total)）
def can_submit() -> bool:
    return not aborted and monotonic_fn() >= cooldown_until
def submit_window():
    nonlocal next_idx
    while len(pending) < concurrency and next_idx < total and can_submit():
        if next_idx in results: next_idx += 1; continue
        if cancel_check and cancel_check(): raise RunCancelled()
        f = executor.submit(extract_batch, batches[next_idx]); fut_index[f]=next_idx; pending.add(f); next_idx += 1
try:
    submit_window()
    while pending or (next_idx < total and not aborted):
        if not pending:
            # 全部在飞已清空但仍有待提交：可能在冷却中 → 分块等待（cancel-aware），否则直接补投
            if not can_submit():
                remaining = cooldown_until - monotonic_fn()
                if remaining > 0: 
                    chunk = min(0.5, remaining)
                    if cancel_check and cancel_check(): raise RunCancelled()
                    sleep_fn(chunk); continue
            submit_window()
            if not pending:  # 仍无法提交（已 aborted）→ 退出
                break
            continue
        completed, pending = wait(pending, return_when=FIRST_COMPLETED)
        for future in completed:
            index = fut_index.pop(future)
            try:
                sanitized, w = future.result()
            except RunCancelled: raise
            except Exception as exc:
                code = exc.code if isinstance(exc, AppError) else type(exc).__name__
                if persistence: persistence.record_batch(index, input_hashes[index], "failed", None, code, str(exc)[:500])
                processed_failed += 1
                if code == "LLM_RATE_LIMITED":
                    consecutive_rl += 1
                    wait_s = getattr(exc, "retry_after", None) or settings.extract_rate_limit_cooldown_sec
                    cooldown_until = max(cooldown_until, monotonic_fn() + wait_s)
                    if settings.extract_rate_limit_circuit_breaker and consecutive_rl >= settings.extract_rate_limit_circuit_breaker:
                        aborted = True
                else:
                    consecutive_rl = 0
                if progress_callback: progress_callback(processed_done, processed_failed, total)
                continue
            results[index] = sanitized
            if persistence: persistence.record_batch(index, input_hashes[index], "done", sanitized.model_dump(mode="json"), None, None)
            consecutive_rl = 0
            processed_done += 1
            if progress_callback: progress_callback(processed_done, processed_failed, total)
        if cancel_check and cancel_check(): raise RunCancelled()
        submit_window()
finally:
    executor.shutdown(wait=False, cancel_futures=True)
```
（以上为指导；请保证：无忙等、无死循环、cancel 及时、确定性合并、线程安全——persistence/progress 仍只在主线程调用。）

## 验证（实际执行，最终消息逐条报告；注入假 client/sleep/monotonic，不真睡、不连真实外网）
1. `cd backend && ./.venv/bin/pytest -q` 全绿。新增/更新测试：
   - **进度按已处理推进**：构造 4 批、第 2 批失败 → progress_callback 收到的 `(done,failed,total)` 序列最终达到 `done+failed==total`；done 与 failed 计数正确。
   - **全局冷却**：注入假 monotonic + 记录型 sleep；某批返回带 retry_after 的 LLM_RATE_LIMITED → 断言冷却窗口内不再提交新批（提交时刻 ≥ cooldown_until）、冷却结束后继续；用假 monotonic 推进时间。
   - **熔断**：阈值设小（如 2），假 client 连续 429 → 断言达到阈值后**不再提交剩余批**（generate_json 调用数受限）、stats["aborted"] True、done+failed < total、warnings 含披露、抛 RunCancelled 不发生（熔断不是取消）。
   - **cancel 仍及时**：冷却分块等待期间 cancel_check 变 True → 迅速抛 RunCancelled。
   - **编排器**：aborted 且 done>0 → 部分结果 + run.resumable=True；done==0 → failed+resumable。
   - **回归**：happy path（无限流）progress 到 total、合并完整、event_id 确定；mock 单批不变；既有并发/取消/续跑测试更新签名后通过。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `backend/.venv/bin/python scripts/evaluate_demo.py` 仍 3/3。
4. `cd frontend && npm run type-check && npm run build` 通过（若动了前端文案/字段）。
报告：进度语义、冷却与熔断逻辑、主循环无死循环/忙等的论证、cancel-aware、stats.aborted 与编排器处理、各测试结果。**不要 git commit。**
