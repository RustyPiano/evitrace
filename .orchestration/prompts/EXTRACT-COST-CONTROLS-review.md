# 代码审核（只读，禁止修改）：大规模成本控制三件套

审核新增的「去重过滤 + 可配批量 + 启动超量护栏」。当前分支 `feat/extract-cost-controls`，相对 `main` 的改动即审核范围。只报真实问题，给 文件:行，每条标严重级（BLOCKER/MAJOR/MINOR/NIT），末行总评 PASS / PASS-WITH-FIXES / FAIL + 合并前必修项。

## 范围
`backend/app/config.py`、`backend/app/skills/intelligence_extract.py`、`backend/app/services/orchestrator.py`、`backend/app/api/analysis.py`、`frontend/src/views/TaskWorkbenchView.vue`、相关测试、`.env.example`、`docs/DEPLOYMENT.md`。

## 必查项（最高风险优先）
1. **去重正确性与确定性**：`_prefilter_evidence` 是否保持 kept 的「首现」顺序（关系到 `_merge_extractions` 的 `event_id` 稳定性，必须与去重前同序的子序列一致）？去重键用 `_normalize_key(text)` 是否会把**实际不同**的证据误判为重复（例如仅大小写/全半角不同但语义相同→合并是预期；但内容截然不同却 norm 相同→须指出）？空白/过短判定边界（`min_chars=0` 仅丢空白；`>0` 丢 `len(stripped)<min_chars`）是否正确？
2. **去重的副作用**：被去重/过滤的证据**仍在 DB 与证据面板**、只是不发给 LLM——确认实现确实只作用于「发给模型的列表」，没有删除/篡改入库证据或 `evidence_by_id`（`_sanitize_extraction` 的引用校验仍针对每批实际发送的证据）。确认 mock 路径（`effective_mock_llm`）完全不走 prefilter。
3. **可配批量**：`_batch_evidence` 用 `max_items/max_chars`（None 时回退 settings）是否正确；`max_chars` 下单条超长证据（`size > max_chars`）是否仍能成批（不死循环、不丢弃）——注意原逻辑 `if current and (...)`，单条超限时 current 为空仍会被放入当前批，行为是否保持。clamp 范围是否合理、`extract_min_evidence_chars=0` 默认是否等价旧行为（仅丢空白，旧行为是不丢——这是**新增**丢空白，是否会改变既有真实测试？指出任何回归）。
4. **护栏**：`start_run` 的 `RUN_TOO_LARGE` 判定位置是否在创建 run 之前（不产生半截 run）、是否在 `single_run_start_lock` 内（并发安全）、`threshold=0` 是否真正关闭、`confirm_large=True` 是否放行；`_create_run_without_user`（脚本路径）确认未被护栏波及。端点 `RunStartRequest` 默认 `confirm_large=False`、无 body 时兼容旧调用、审计字段无敏感信息。
5. **前端**：`RUN_TOO_LARGE` 分支读取 `error.response.data.detail.code/message` 是否健壮（无 optional chaining 崩溃）；确认重试 `startAnalysis(true)` 与 `analysisStarting` loading 状态在「确认/取消/再失败」各路径都能正确复位（不卡 loading、不递归泄漏）；用户取消确认时静默不报错。type-check/build 是否通过。
6. **透明披露**：丢弃证据时是否向 run.warnings 写入可读披露文案（不得静默丢弃）；文案不含敏感信息。
7. **回归**：mock 单批路径不变；evaluate_demo 3/3、coverage/invalid 不变；新增测试是否真正覆盖「去重计数、首现顺序、真实路径调用数=去重后批数、批量随配置变化、护栏拦截/放行/阈值0、端点 body 契约、mock 不变」。指出任何测试是 mock 掉了关键逻辑导致假绿。
8. **配置/文档**：四个新 env 的 alias/clamp 与 `.env.example` 注释一致；DEPLOYMENT 描述与实现一致（不夸大省钱效果——去重/调大批量降单次开销，根本省钱靠减少证据量）。

## 输出
逐条发现 + 末行总评。只报真实问题。
