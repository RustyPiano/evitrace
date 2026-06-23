# 任务（P0a）：LLM 客户端健壮重试——错误分类 + Retry-After + 指数退避 + jitter

背景：真实大语料抽取时上游（OpenRouter/DeepSeek 等 OpenAI 兼容端点）返回 **HTTP 429**。现状 `backend/app/services/llm_client.py` 把所有 HTTP 错误都当 `LOCAL_MODEL_UNAVAILABLE`，**立即重试、无退避、无视 Retry-After**，3 次几毫秒内全撞 429 → 整批失败 → 整轮分析炸。本任务把重试改为「按错误类型分流 + 退避」，让短暂限流能自愈。不连真实外网（测试注入假 client/假 sleep）、既有测试不回归、不写真实 key、不 git commit。

## 1) 配置（`backend/app/config.py`）
新增（Field + validation_alias + clamp 校验器，与现有同风格）：
- `llm_rate_limit_max_retries: int`，alias `LLM_RATE_LIMIT_MAX_RETRIES`，默认 `5`，clamp `0..10`。
- `llm_backoff_base_sec: float`，alias `LLM_BACKOFF_BASE_SEC`，默认 `1.0`，clamp `0.1..10.0`。
- `llm_backoff_max_sec: float`，alias `LLM_BACKOFF_MAX_SEC`，默认 `30.0`，clamp `1.0..120.0`。

## 2) 错误分类（`backend/app/services/llm_client.py` 的 `_chat_completion`）
当前 `except httpx.HTTPStatusError` 一律抛 `LOCAL_MODEL_UNAVAILABLE`。改为按 `exc.response.status_code` 分流，抛带分类 code 的 `AppError`，并在可重试且能读到 `Retry-After` 时把秒数附到异常对象上（`err.retry_after = <float|None>`；`AppError` 无该字段就 setattr）：
- **429** → code `LLM_RATE_LIMITED`，http 429，可重试；解析 `Retry-After` 头（整数秒或 HTTP-date 都尽力解析，解析失败则 None）存到 `retry_after`。
- **500/502/503/504** → code `LOCAL_MODEL_UNAVAILABLE`，http 503，可重试；尝试读 `Retry-After`（503 可能带）。
- **402** → code `LLM_INSUFFICIENT_BALANCE`，http 402，**不可重试（致命）**，message 提示「上游余额不足/欠费」。
- **400/401/403/404/422** → code `LLM_REQUEST_INVALID`，沿用原 http_status，**不可重试（致命）**，message 含状态码。
- 其它未列状态码 → 保守归为可重试 `LOCAL_MODEL_UNAVAILABLE`。
- `httpx.ConnectError/TimeoutException/HTTPError`（非 HTTPStatusError）→ 仍 `LOCAL_MODEL_UNAVAILABLE`（可重试），`retry_after=None`。
- 响应非 JSON / 结构无效 → 仍 `INVALID_MODEL_OUTPUT`（这是输出问题，不是传输问题）。

定义一个小工具：可重试 code 集合 `RETRYABLE_TRANSIENT = {"LLM_RATE_LIMITED", "LOCAL_MODEL_UNAVAILABLE"}`；致命集合 `FATAL = {"LLM_REQUEST_INVALID", "LLM_INSUFFICIENT_BALANCE"}`。

## 3) 退避与重试循环（`generate_json` 与 `generate_text`）
把现有「`for attempt in range(self.max_retries + 1)`、对 LOCAL_MODEL_UNAVAILABLE 立即 continue」的逻辑改为分类重试：

- 传输类错误（`RETRYABLE_TRANSIENT`）：用**独立计数** `transient_retries`，上限 `settings.llm_rate_limit_max_retries`。每次失败：
  - `delay = err.retry_after if err.retry_after else _backoff(transient_retries)`；
  - `_backoff(n) = min(base * (2 ** n) * (0.5 + random()*0.5)... )`——即指数退避 `base*2^n` 叠加 **±50% jitter**，并 clamp 到 `[0, llm_backoff_max_sec]`（`retry_after` 也 clamp 到 `llm_backoff_max_sec` 上限，避免上游给个超大值卡死）；
  - `self._sleep(delay)`；`transient_retries += 1`；continue；
  - 超过上限 → 抛出该 `AppError`（保留分类 code，便于上层与 P0b 区分「限流耗尽 vs 余额不足」）。
- **致命错误**（`FATAL`）：立即 `raise`，**不 sleep、不重试**。
- 解析/校验错误（`INVALID_MODEL_OUTPUT`，仅 `generate_json`；空文本，仅 `generate_text`）：保持**即时重试**（无 backoff），用**独立计数** `parse_retries`，上限沿用 `self.max_retries`；超限抛 `INVALID_MODEL_OUTPUT`。
- 用 `while True` + 两个独立计数实现，避免把传输重试和解析重试混用一个 `attempt`。

### sleep 可注入（关键，测试用）
- `__init__` 增加 `sleep_fn: Callable[[float], None] | None = None`；`self._sleep = sleep_fn or time.sleep`。
- `random` 用标准库 `random.random()`；测试通过注入固定 `random`？不需要——测试只断言 `delay` 落在合理区间或 `_sleep` 被调用的次数/参数。为可测，**把退避计算抽成纯函数** `def _compute_delay(retry_after, attempt, base, max_sec) -> float`（jitter 可作为可选参数注入，默认用 random），便于单测既能验证「有 retry_after 用 retry_after（clamp 后）」也能验证「无 retry_after 时落在 [base*2^n*0.5, base*2^n] 区间内并 ≤ max_sec」。

### 日志
- 重试时 `logger.warning("LLM retry transient code=%s attempt=%s delay=%.2fs", code, transient_retries, delay)`；致命时 `logger.warning("LLM fatal code=%s", code)`。**不得记录 url/key/Authorization**（保持现有不打印密钥的惯例）。

## 4) 不改动
- mock 路径（`self.mock_ai`）完全不变。
- `health_check`、`_chat_completion` 的成功路径、usage 日志不变。
- 调用方（orchestrator/skills）签名不变（本任务不引入 cancel-aware sleep；那属于 P0b）。

## 验证（实际执行，最终消息逐条报告；测试注入假 client/假 sleep，**绝不真睡、不连真实外网**）
1. `cd backend && ./.venv/bin/pytest -q` 全绿。新增测试（`backend/tests/unit/test_llm_client.py` 或既有对应文件）：
   - **429 带 Retry-After**：假 http_client 前 2 次返回 429（headers `Retry-After: 2`）、第 3 次 200。注入记录型 `sleep_fn`，断言：sleep 被调用 2 次、每次≈2s（被 clamp 到 max 以内）、最终成功、`generate_json` 返回校验对象。
   - **429 无 Retry-After**：连续 429 直到超 `llm_rate_limit_max_retries` → 抛 `AppError(code="LLM_RATE_LIMITED")`；断言 sleep 调用次数 == 上限、各 delay 落在指数退避+jitter 的理论区间且 ≤ `llm_backoff_max_sec`。
   - **402/400/401**：返回该状态码 → **立即抛**对应致命 code、**sleep 从未被调用**、http_client 只被请求 1 次（无重试）。
   - **5xx**：500/503 → 走 transient 退避重试路径（可设第 2 次 200 验证自愈）。
   - **解析错误即时重试**：返回 200 但 body 非合法 JSON（或 schema 不符）→ 按 `self.max_retries` 即时重试、**不调用 sleep**，超限抛 `INVALID_MODEL_OUTPUT`。
   - `_compute_delay` 纯函数单测：有/无 retry_after、clamp 上限、jitter 区间。
   - mock 路径回归：`mock_ai=True` 时不触发任何 http/sleep。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `backend/.venv/bin/python scripts/evaluate_demo.py` 仍 3/3（mock，行为不变）。
4. 前端未改动可注明（本任务不动前端）。

报告：错误分类表、退避/Retry-After 逻辑、两个独立计数的重试循环、可注入 sleep、各测试结果。**不要 git commit。**
