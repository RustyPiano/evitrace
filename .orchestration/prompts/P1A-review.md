# 代码审核（只读，禁止修改/禁止 git）：P1a 进度/全局冷却/熔断

审核分支 `feat/free-tier-volume-cut` 相对 `main` 的改动（P1a：`intelligence_extract.py` 的 `_run_real_extraction` 主循环、`orchestrator.py` 的 extract_progress、`config.py`、测试、.env.example/docs）。最高风险是**并发主循环的正确性**。只报真实问题，给 文件:行 + 严重级，末行总评 PASS / PASS-WITH-FIXES / FAIL。

## 必查（按风险）
1. **无死循环 / 无忙等 / 不提前退出**：`while pending or (next_idx < total and not aborted)` 配合冷却分块 sleep——
   - 冷却期（pending 空、未 aborted、now<cooldown_until）是否**分块 sleep 0.5s 并 cancel-aware**、monotonic 单调推进必然到期、不忙等？
   - aborted 后是否能**及时退出**（in-flight 跑完即停，不再提交、不空等整个冷却）？给出 aborted 路径的退出论证。
   - 是否存在「pending 空 + 无法提交 + 仍有未处理批」导致**提前 break 丢批**或**卡死**的情形？
2. **冷却语义**：429（带/不带 retry_after）是否只门控**新提交**、不杀在飞批？`cooldown_until` 取 max 累积是否正确？无 retry_after 用 `extract_rate_limit_cooldown_sec` 兜底？
3. **熔断语义**：`consecutive_rate_limited` 仅 LLM_RATE_LIMITED 累加、成功或非限流失败归零；达阈值 `aborted=True` 后不再提交未开始批；未提交批**不计 failed**（failed=processed_failed 仅实际失败）；阈值=0 关闭。
4. **进度语义**：progress_callback(done,failed,total) 在 done 与 failed 都调用、预填缓存批也调用；orchestrator processed=done+failed、progress 单调 clamp≤70、live 写 run 批次计数（后台线程、复用 db，安全）。
5. **确定性/线程安全**：合并仍按 batch_index 升序；persistence/progress 仍只在主线程；worker 仍只调 LLM；executor 各路径 shutdown。
6. **stats/编排器**：metrics 增 batch_aborted；resumable = done>0 且(failed>0 或 aborted)；done==0 → 失败+resumable；aborted+done>0 → 部分结果+resumable + 披露 warning。
7. **取消**：冷却分块等待与收集循环中 cancel_check 仍及时抛 RunCancelled。
8. **回归**：mock 单批不变；happy path 进度到 total、合并完整、event_id 确定；既有并发/取消/续跑测试是否已正确更新签名且仍真实覆盖（非假绿）。
9. **clamp/配置**：两个新配置范围合理。

## 输出
逐条发现 + 末行总评。只报真实问题。
