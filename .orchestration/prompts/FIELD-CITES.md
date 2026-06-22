# 任务：字段级证据引用（time/location/quantity 各自携带 evidence_ids）

外部评审指出：当前引用校验只是「格式完整性」——报告里出现 `E-xxxx`、编号存在、结论段/时间线/冲突行带引用即算通过；只要附任意合法编号覆盖率就能 100%，无法体现「该证据是否真的支持这句话」。改进方向（评审建议、且不需昂贵验证模型）：**关键事实从结构化事件字段生成，每个字段带自己的 evidence_ids；报告按字段引用，不再用事件级通用证据列表。**

目标：实现**字段级引用**，向后兼容、既有测试不回归、MOCK 演示仍 3/3。不要 git commit。
诚实边界：这是把引用从「事件级完整性」细化为「字段级完整性 + 来源精确化」，**不是**语义真实性验证（语义校验需额外模型，明确不在本次范围，文档如实说明）。

## 1) Schema（`backend/app/schemas_analysis.py`，全部向后兼容、新增可选字段）
- 新增 `class FieldCitation(AnalysisBaseModel)`：`value: str | None = None`、`evidence_ids: list[str] = Field(default_factory=list)`。
- `Event` 新增可选：`time_citation: FieldCitation | None = None`、`location_citation: FieldCitation | None = None`、`quantity_citation: FieldCitation | None = None`。**保留**既有 `evidence_ids`（事件级，min_length=1 不变）与 `time_text/time_normalized/location/quantity`。
- `ConflictSide` 保持 `evidence_ids: list[str]`（min_length=1），但其取值改为「该冲突维度对应字段的 evidence_ids，缺失则回退事件级」（见第 3 点），语义不变、约束不破。
- `TimelineItem` 可加可选 `time_evidence_ids: list[str] = Field(default_factory=list)`（时间字段来源；缺则空，前端可忽略）。保持现有 `evidence_ids`（min_length=1）。

## 2) 抽取阶段（`backend/app/skills/intelligence_extract.py`）
- `_sanitize_extraction`：对每个 event 的 `time_citation/location_citation/quantity_citation`，用与事件级相同的 `_valid_evidence_ids` 逻辑校验其 `evidence_ids`（只保留真实存在的 display_id，去重）。
- **回退规则（关键，保证不回归）**：若某字段对应值存在（如 location 非空）但其 `*_citation` 缺失或校验后为空 → 用**事件级 `evidence_ids`** 作为该字段引用回退；若字段值本身为空（如无 quantity）→ 该字段 citation 置 None。
- 真实 LLM 提示词（system schema）：在 events 的 schema/示例中**新增可选**字段示例：
  `"time_citation": {"value": "14:00", "evidence_ids": ["E-0003"]}`、location_citation、quantity_citation；说明「每个事实字段尽量给出**直接支持该字段**的证据编号；不确定则省略，系统将回退到事件级」。保持「只输出 JSON」「evidence_ids 取自输入」等既有约束。
- mock：更新 `_default_mock_raw`，给两个示例事件补上 time_citation/location_citation/quantity_citation（指向 first/second），用于演示与测试。
- 合并 `_merge_extractions`：合并同一事件时，字段级 citation 的 evidence_ids 也做并集去重（与事件级一致）。

## 3) 冲突检测按字段引用（`backend/app/skills/conflict_detect.py`）
- `_event_side` 改为接受「该维度字段的 evidence_ids」：
  - time 冲突 → 用 `left/right` 的 `time_citation.evidence_ids`，缺失回退 `event["evidence_ids"]`。
  - location 冲突 → `location_citation.evidence_ids` 回退事件级。
  - quantity 冲突 → `quantity_citation.evidence_ids` 回退事件级。
- 保证 ConflictSide.evidence_ids 始终非空（回退保证）。其余比较逻辑/阈值/warning 不变。
- 若本仓库的事件归一化（EVENT-NORM）已合入，保持与其分组逻辑兼容（在同组内取字段引用）。

## 4) 报告按字段引用（`backend/app/skills/report_generate.py`）
- 时间线行（`_timeline_lines`）：引用优先用该 timeline item / event 的**时间字段** evidence（`time_evidence_ids` 或 event time_citation），缺失回退事件级 `evidence_ids`。
- 冲突行（`_conflict_lines`）：已用 `left.evidence_ids + right.evidence_ids`——现在这些已是字段级（第 3 点），自动变精确，无需额外改；确认拼接去重。
- 结论/资料概况等模板文案：维持现状（仍用事件级或首证据），本次只精确化「事实性」段落（时间线、冲突）。
- 确认 `validate_report_citations`：字段级引用都是合法 display_id，**覆盖率/invalid 不应变差**；三/四事实行仍能命中有效引用。

## 5) 校验（如实，不夸大）
- 不新增语义校验模型。可选增强：在 `validate_report_citations` 增加一个**非阻塞**统计字段（如 `field_level_citations: int` 或 `conflict_sides_with_field_citation: int`），用于报告/演示展示「冲突两侧均带字段级来源」的比例，纯计数、不改变完成度门槛。若改 `CitationCheck` 需同步前端类型与既有测试。保持向后兼容。

## 前端
- 上述均为**新增可选**字段，前端 `extra` 容忍即可。若前端有 Event/Timeline/Conflict 的 TS 接口且 strict，补充可选字段定义使 `npm run type-check` 通过；非必要不改 UI 行为（可选：证据面板/冲突卡显示字段级来源）。

## 验证（实际执行，最终消息逐条报告）
1. `cd backend && ./.venv/bin/pytest -q` 全绿。新增测试：
   - 字段级 evidence 校验 + 非法编号剔除 + 字段缺失回退事件级；
   - time/location/quantity 冲突的 ConflictSide.evidence_ids 来自对应字段（构造 time_citation≠event 级，断言冲突引用用了字段级）；
   - 报告时间线行引用用时间字段证据；
   - 回退路径：字段 citation 全缺 → 行为与旧版一致（回归）。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `./.venv/bin/python scripts/evaluate_demo.py` 仍 3/3，coverage/invalid 不变。
4. `cd frontend && npm run type-check && npm run build` 通过。
报告：schema 新增字段、回退规则、冲突/时间线字段级引用证明、诚实边界（非语义校验）、demo 不回归结论。不要 git commit。
