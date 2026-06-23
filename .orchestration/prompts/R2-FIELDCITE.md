# 任务：字段级引用诚实化（value 强制 + explicit/fallback 标记 + 显式引用率）

外部评审指出 `_sanitize_field_citation` 两个问题：①模型可给出与事件字段不一致的 `value`（如事件 time=14:00 但 citation.value=16:30），代码却原样保留模型的 value；②字段引用为空时静默回退到事件级全部 `evidence_ids`，于是"100% 引用合法"可能掩盖"其实是自动回退、模型没真正指明哪条证据支持该字段"。不要 git commit；既有测试不回归、demo 3/3。

## 1) Schema（`backend/app/schemas_analysis.py`）
- `FieldCitation` 新增 `citation_origin: Literal["explicit", "fallback"] | None = None`（向后兼容，默认 None）。

## 2) `_sanitize_field_citation`（`backend/app/skills/intelligence_extract.py`）
- **value 强制等于事件字段**：返回的 `value` **始终**用传入的 `fallback_value`（即已规范化的事件字段：time_text/time_normalized、location、quantity 文本），**忽略模型另给的 `raw_citation["value"]`**（避免展示与事件不符的值）。
- **explicit/fallback 判定**：
  - 若该字段值存在且 `raw_citation` 提供了**校验后非空**的 `evidence_ids` → `evidence_ids` 用模型给的（校验后），`citation_origin="explicit"`。
  - 若字段值存在但模型未给/校验后为空 → `evidence_ids` 回退事件级，`citation_origin="fallback"`。
  - 字段值不存在 → 返回 None（不变）。
- 保证回退后 evidence_ids 仍非空（事件级 min_length=1）。`_merge_extractions` 合并字段引用时：若两侧 origin 不同，合并后只要任一为 explicit 即记 explicit（并集 evidence_ids）。

## 3) 显式引用率统计（`backend/app/utils/citations.py` + 报告）
- 报告生成处已有 events（payload["events"]）。新增一个纯函数（如 `field_citation_stats(events) -> dict`）统计全部事件的 time/location/quantity 字段引用中 explicit vs fallback 的数量，得：`field_citation_total`、`field_citation_explicit`、`field_explicit_ratio`（total 为 0 时记 1.0 或 None，二选一并注释）。
- 在 `CitationCheck`（schemas）新增可选字段：`field_citation_total: int = 0`、`field_citation_explicit: int = 0`、`field_explicit_ratio: float | None = None`（向后兼容）。`report_generate.run` 计算后并入 `citation_check`。前端类型同步（可选展示）。
- 诚实表述：这是"字段显式引用占比"，仍非语义真实性校验。

## 4) 前端（`frontend/src/types/workbench.ts` + 冲突/证据展示，最小改动）
- 类型补 `citation_origin`、CitationCheck 新字段。
- 在冲突卡或证据引用处，对 `citation_origin === "fallback"` 的字段给一个轻量提示（如灰色"事件级回退"小标或 title 提示），explicit 不特别标注。非必需做满，但 type-check/build 必须过；不强求大改 UI。

## 验证（实际执行，最终消息逐条报告）
1. `cd backend && ./.venv/bin/pytest -q` 全绿。新增测试：
   - 模型给出与事件字段不一致的 value → 最终 value 等于事件字段（模型 value 被忽略）；
   - 字段有显式有效 evidence_ids → origin=explicit；缺失 → 回退事件级且 origin=fallback、evidence_ids 非空；
   - `field_citation_stats` 计数正确；全 explicit / 全 fallback / 混合三种情形。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `./.venv/bin/python scripts/evaluate_demo.py` 仍 3/3，coverage/invalid 不变（fixture 的字段引用应为 explicit，explicit_ratio 应=1.0）。
4. `cd frontend && npm run type-check && npm run build` 通过。
报告：value 强制策略、explicit/fallback 判定与合并、显式引用率统计、前端提示，验证结果。不要 git commit。
