# 代码审核（只读，禁止修改/禁止 git）：P0a LLM 客户端健壮重试

审核分支 `feat/big-task-resilience` 相对 `main` 的改动（仅 `backend/app/config.py`、`backend/app/services/llm_client.py` 及其测试、`test_config.py`）。只报真实问题，给 文件:行 + 严重级（BLOCKER/MAJOR/MINOR/NIT），末行总评 PASS / PASS-WITH-FIXES / FAIL + 合并前必修项。

## 必查项
1. **重试终止性**：transient 与 parse 两个独立计数是否都有上限、`while True` **不可能死循环**（任何分支都最终 raise 或 return）？transient 超限是否抛出**保留分类 code** 的原异常（供 P0b 区分限流耗尽 vs 余额不足）？
2. **致命不重试**：402/400/401/403/404/422 是否**立即 raise、绝不 sleep、绝不重试**？（确认 FATAL 分支在 transient 分支之后不会被 transient 误捕获——code 不在 RETRYABLE_TRANSIENT 即可。）
3. **Retry-After 正确性**：`_parse_retry_after` 对「整数秒」「HTTP-date」「空/非法」分别返回什么；HTTP-date 过去时间是否被 clamp 到 ≥0；`_compute_delay` 是否把 retry_after 也 clamp 到 `llm_backoff_max_sec`（防上游给超大值卡死）；无 retry_after 时指数退避+jitter 是否 ≤ max_sec、≥0。
4. **退避计算**：`base*2^attempt` 随 attempt 增长；jitter 是否引入（区间）；attempt 从 0 起是否符合预期（第一次重试 delay 量级）。大 attempt 下 `2**attempt` 是否会在 clamp 前溢出成极大 float（虽最终 clamp，但确认无异常）。
5. **sleep 注入**：`sleep_fn` 默认 `time.sleep`；测试是否真的没有真实 sleep（注入记录型 fn）；生产路径 sleep 发生在 worker 线程中是否可接受（本任务范围；cancel-aware 留 P0b）。
6. **分类映射**：429/5xx/402/4xx/其它/传输错误 的 code、http_status、是否带 retry_after 是否与设计一致；非 JSON 响应仍归 `INVALID_MODEL_OUTPUT`（输出问题非传输问题）。
7. **不打印敏感信息**：新日志不得含 url/api_key/Authorization。
8. **回归**：mock 路径完全不变；`generate_text` 空文本路径仍能在超限后抛 INVALID_MODEL_OUTPUT；`health_check` 不受影响；config clamp 范围合理。
9. **测试质量**：429+Retry-After 是否断言 sleep 次数/时长；429 无 header 是否断言超限抛 LLM_RATE_LIMITED 且 delay 落在退避区间；402/4xx 是否断言**零 sleep、单次请求**；5xx 自愈；解析错误即时重试不 sleep；`_compute_delay` 纯函数单测。是否存在 mock 掉关键逻辑导致假绿。

## 输出
逐条发现 + 末行总评。只报真实问题。
