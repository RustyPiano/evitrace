# 任务：大规模资料省钱三件套——去重过滤 + 可配大批量 + 启动超量护栏

背景（已诊断）：真实抽取按「每批一次真实 LLM 调用、30 条/批、12000 字符/批」处理，成本随证据条数线性增长；且每批都重发约 1800 token 的固定 system 提示词（schema+两个完整示例）。大语料（如 61 文档→8121 证据→271 批）会产生巨额真实调用费用。本次新增三项**省钱**能力，不改变 mock 行为、既有测试不回归、不写真实 key、不 git commit：

- **① 抽取前去重 + 空白/过短过滤**（仅真实路径）：减少发给 LLM 的证据条数→减少批数。**全量证据仍照常入库与展示**，只是不把重复/空白证据重复发给模型。
- **② 批量大小可配置**：把写死的 `BATCH_MAX_ITEMS=30`/`BATCH_MAX_CHARS=12000` 改为可配置；调大→批数减少→重复 system 提示词税减少。
- **③ 启动超量护栏**：启动分析时若文件数超过阈值且未二次确认，拒绝并提示，防误传大语料意外扣费。

## 1) 配置（`backend/app/config.py`）

新增四个设置（与现有同风格：Field + validation_alias + clamp 校验器）：
- `extract_batch_max_items: int`，alias `EXTRACT_BATCH_MAX_ITEMS`，默认 `30`，clamp 到 `1..500`。
- `extract_batch_max_chars: int`，alias `EXTRACT_BATCH_MAX_CHARS`，默认 `12000`，clamp 到 `1000..120000`。
- `extract_min_evidence_chars: int`，alias `EXTRACT_MIN_EVIDENCE_CHARS`，默认 `0`，clamp 到 `0..2000`（0 = 仅丢弃完全空白证据；>0 时额外丢弃 strip 后长度 < 该值的证据）。
- `extract_max_files_confirm: int`，alias `EXTRACT_MAX_FILES_CONFIRM`，默认 `20`，clamp 到 `0..100000`（0 = 关闭护栏）。

clamp 用 `@field_validator(..., )` 返回 `min(max(value, lo), hi)`，与现有 `clamp_extract_concurrency` 同写法。

## 2) 去重过滤 + 可配批量（`backend/app/skills/intelligence_extract.py`）

### 2a) 新函数 `_prefilter_evidence`
```python
def _prefilter_evidence(
    evidence_items: list[dict[str, Any]],
    *,
    min_chars: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
```
- 按输入顺序遍历；对每条：`text = _evidence_text(evidence)`。
- 若 `not text.strip()`（完全空白）或（`min_chars > 0` 且 `len(text.strip()) < min_chars`）→ 计入 `dropped_low_signal`，跳过。
- 否则 `norm = _normalize_key(text)`（复用现有 NFKC+casefold+strip）；若 `norm` 已在 `seen` 集合 → 计入 `dropped_duplicate`，跳过；否则 `seen.add(norm)`、保留。
- 返回 `(kept, {"original": len(evidence_items), "kept": len(kept), "dropped_duplicate": d, "dropped_low_signal": s})`。
- **保持 kept 的原始相对顺序**（确保与现有 event_id 分配同序、确定性）。

### 2b) `_batch_evidence` 改为读配置
- 签名改为 `def _batch_evidence(evidence_items, *, max_items: int | None = None, max_chars: int | None = None)`。
- 函数体内：`max_items = max_items or settings.extract_batch_max_items`；`max_chars = max_chars or settings.extract_batch_max_chars`；用这两个变量替换原来的 `BATCH_MAX_ITEMS`/`BATCH_MAX_CHARS`。
- 保留模块常量 `BATCH_MAX_ITEMS = 30`、`BATCH_MAX_CHARS = 12_000`（不再被 `_batch_evidence` 直接引用，仅作为历史默认值/可被测试引用，避免破坏其它 import）。

### 2c) 在 `_run_real_extraction` 接入
- 在 `batches = _batch_evidence(evidence_items)` **之前**插入：
  ```python
  filtered_items, prefilter_stats = _prefilter_evidence(
      evidence_items, min_chars=settings.extract_min_evidence_chars
  )
  ```
  之后用 `filtered_items` 做 `_batch_evidence`。
- 若有丢弃（`dropped_duplicate + dropped_low_signal > 0`）→ 向 `warnings` 追加一条**透明披露**：
  `f"为节省真实模型调用，已跳过 {dropped_duplicate} 条重复证据、{dropped_low_signal} 条空白/过短证据（原 {original} 条 → 实际抽取 {kept} 条）"`（用 stats 字段格式化）。
- 边界：若 `filtered_items` 为空（全空白），`_batch_evidence([])` 返回 `[]`，`total=0`，主循环不执行，`merged` 为空 → 现有「真实模型未抽取到任何要素」warning 照常触发；不得抛异常。
- **mock 路径（`effective_mock_llm` 为真）完全不变**：不做 prefilter，不改 `_default_mock_raw`/fixture 行为。
- 去重只影响「发给 LLM 的证据」；被去重/过滤掉的证据**仍在 DB、仍在证据面板**，只是模型没看到、不会单独被引用——这是预期且更省钱的行为。

## 3) 启动护栏（`backend/app/services/orchestrator.py` + `backend/app/api/analysis.py`）

### 3a) `orchestrator.start_run`
- 签名加 `confirm_large: bool = False`（放在 `current_user` 之后）。
- 在已算出 `file_count` 之后、`if task.status in TASK_RUNNING_STATUSES` 检查附近（在创建 run 之前、获得 file_count 之后即可），新增：
  ```python
  threshold = settings.extract_max_files_confirm
  if threshold > 0 and file_count > threshold and not confirm_large:
      raise AppError(
          "RUN_TOO_LARGE",
          f"本次包含 {file_count} 个文件，超过确认阈值 {threshold}，"
          f"真实分析可能产生大量模型调用与费用。如确认继续，请再次确认。",
          status.HTTP_409_CONFLICT,
      )
  ```
- `_create_run_without_user`（脚本/内部路径）**不加护栏**（保持脚本可无人值守运行）。

### 3b) `analysis.start_analysis_run`
- 新增请求体模型（放本文件或 `schemas_analysis.py`，与现有风格一致）：
  ```python
  class RunStartRequest(BaseModel):
      confirm_large: bool = False
  ```
- 端点签名加 `payload: RunStartRequest = Body(default=RunStartRequest())`（`from fastapi import Body`；若放 schemas_analysis 则 import）。**不传 body 时默认 confirm_large=False，保持现有调用方兼容**。
- 调用 `orchestrator.start_run(db, task_id, current_user, confirm_large=payload.confirm_large)`。
- 审计 detail 增加 `"confirm_large": payload.confirm_large`（可选）。

## 4) 前端确认流程（`frontend/src/views/TaskWorkbenchView.vue`）
- 顶部已 `import { ElMessage } from "element-plus"` → 改为同时引入 `ElMessageBox`。
- `startAnalysis` 改为 `async function startAnalysis(confirmLarge = false)`：
  - POST 时带 body：`apiClient.post(..., { confirm_large: confirmLarge })`。
  - `catch (error)` 中：先判断后端业务码——读取 `error?.response?.data?.detail?.code`；若等于 `"RUN_TOO_LARGE"`：
    ```js
    try {
      await ElMessageBox.confirm(
        error.response.data.detail.message,
        "确认大额分析",
        { confirmButtonText: "仍要继续", cancelButtonText: "取消", type: "warning" }
      );
      await startAnalysis(true);   // 用户确认后带 confirm_large 重试
    } catch { /* 用户取消，静默 */ }
    return;
    ```
    否则维持原 `ElMessage.error(extractErrorMessage(error, "启动分析失败"))`。
  - 注意 `finally { analysisStarting.value = false }` 与重试的交互：重试是新一次 `startAnalysis(true)` 调用，会自行管理 `analysisStarting`；确认分支 `return` 前不要把 loading 卡死。建议：把 try/catch/finally 结构调整为——仅在「真正发起成功 / 非 RUN_TOO_LARGE 错误」时走原逻辑；RUN_TOO_LARGE 分支单独处理并 return。保证按钮 loading 状态最终被正确复位。
- `@click="startAnalysis"`（模板）保持不变（默认实参 false）。type-check/build 必须通过；不要硬编码密钥/URL。

## 5) 文档（`.env.example` + `docs/DEPLOYMENT.md`「性能与成本」节）
- `.env.example`：在 `EXTRACT_CONCURRENCY` 附近新增带注释的四行：
  ```
  # 抽取批量：每批=一次 LLM 调用。调大→批数少→重复提示词开销低，但超长输入可能漏抽（需验证质量）。
  EXTRACT_BATCH_MAX_ITEMS=30
  EXTRACT_BATCH_MAX_CHARS=12000
  # 抽取前过滤：丢弃 strip 后长度 < 该值的证据（0=仅丢弃完全空白）。去重始终开启。
  EXTRACT_MIN_EVIDENCE_CHARS=0
  # 启动护栏：文件数超过该值需二次确认，防误传大语料意外扣费（0=关闭）。
  EXTRACT_MAX_FILES_CONFIRM=20
  ```
- `docs/DEPLOYMENT.md`「性能与成本」节追加一小段：说明去重过滤（自动、透明披露于 warnings）、批量可调（省重复提示词税）、启动护栏（文件数阈值二次确认）三项，以及「成本随证据量线性增长，去重/调大批量降低单次开销，但要省钱根本上靠减少证据量、先小样试跑、及时『停止分析』」。

## 验证（实际执行，最终消息逐条报告；单测用可注入假 client，不连真实外网）
1. `cd backend && ./.venv/bin/pytest -q` 全绿。新增测试（建议 `backend/tests/` 内相应文件）：
   - **去重**：`_prefilter_evidence` 对内容经 `_normalize_key` 后相同的证据只保留首条、计 `dropped_duplicate`；完全空白证据计 `dropped_low_signal`；`min_chars>0` 时丢弃过短；kept 顺序 = 原序保留首现。
   - **真实路径接入**：注入计数假 client，构造含重复证据的输入 → 实际批数/调用数对应「去重后」条数；merged 结果正确；warning 含披露文案。
   - **可配批量**：monkeypatch `settings.extract_batch_max_items`/`extract_batch_max_chars`（或用 `_batch_evidence(..., max_items=, max_chars=)` 显式传参）→ 批数随配置变化；默认值复现 30/12000 行为。
   - **护栏**：`start_run` 当 file_count > 阈值 且 confirm_large=False → 抛 `RUN_TOO_LARGE`(409)；confirm_large=True → 正常创建 run；阈值=0 → 不拦截；file_count<=阈值 → 正常。端点：POST 无 body 默认 confirm_large=False；POST `{"confirm_large": true}` 放行（用 TestClient + 上传超阈值文件数或 monkeypatch 阈值为很小值如 1 来构造）。
   - **回归**：mock 单批路径不变。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `./.venv/bin/python scripts/evaluate_demo.py` 仍 3/3、coverage/invalid 不变（demo 小语料、文件数 ≤ 阈值、去重通常无丢弃）。
4. `cd frontend && npm run type-check && npm run build` 通过。

报告：去重/过滤逻辑与透明披露、批量配置接入点、护栏判定与端点契约、前端确认重试流程、各测试结果。**不要 git commit。**
