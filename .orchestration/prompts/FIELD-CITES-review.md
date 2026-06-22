# 代码审核（只读，禁止修改）：字段级证据引用

独立审核新增的「字段级引用」（time/location/quantity 各带 evidence_ids）。这是向后兼容增量；最大风险是**回退逻辑错误导致引用覆盖率回归**或 **ConflictSide/TimelineItem 的 evidence_ids 变空**（schema min_length=1 会抛错）。

## 范围
`backend/app/schemas_analysis.py`、`backend/app/skills/intelligence_extract.py`(`_sanitize_field_citation`/`_quantity_text`/`_merge_extractions`/`build_timeline`/prompt/mock)、`backend/app/skills/conflict_detect.py`(`_field_evidence_ids`/`_event_side`)、`backend/app/skills/report_generate.py`(timeline 行)、`frontend/src/types/workbench.ts`、相关测试。

## 必查项（只报真实问题，给文件:行）
1. **非空保证**：任何路径下 `ConflictSide.evidence_ids` 与 `TimelineItem.evidence_ids` 是否恒非空？`_field_evidence_ids` 字段引用为空时是否确实回退到事件级 `event["evidence_ids"]`（事件级 min_length=1）？构造「字段 citation 存在但 evidence_ids 全非法」的输入，确认回退生效、不抛错。
2. **覆盖率不回归**：`_sanitize_field_citation` 当字段值存在但模型未给 citation → 是否回退事件级（非空）；字段值缺失 → 是否置 None（而非空 citation）。报告时间线/冲突行引用是否仍命中合法 `E-xxxx`，`validate_report_citations` 的 coverage/invalid 是否不变（demo 应仍 1.00/0）。
3. **字段级精确性**：time/location/quantity 冲突的 ConflictSide 是否分别取对应 `*_citation.evidence_ids`（构造 time_citation≠事件级，断言用的是字段级）。`_quantity_text` 对 None/缺 unit/非数值是否稳健。
4. **merge 合并**：`_merge_extractions` 合并同一事实事件时，字段 citation 的 evidence_ids 并集去重是否正确；existing/event 任一为 None 的分支是否正确（不丢字段、不重复）。
5. **校验回退/类型**：`FieldCitation.value` trim 为空→None；Event 新增三个可选字段默认 None、`extra=ignore` 下旧数据/旧 fixture 仍可解析；前端 TS 可选字段是否使 type-check 通过、无 UI 行为破坏。
6. **诚实边界**：是否如实保持「字段级完整性 + 来源精确化」、**未**声称语义真实性校验；文档/注释无夸大。
7. **回归**：mock `_default_mock_raw` 新增 citation 是否与现有断言一致；evaluate_demo 3/3、coverage/invalid 不变。

## 输出
每条发现：严重级（BLOCKER/MAJOR/MINOR/NIT）、文件:行、问题、最小修复建议。末行总评 PASS / PASS-WITH-FIXES / FAIL + 合并前必修项。只报真实问题。
