# 任务：事件归一化（canonical_event_key）降低真实输出的冲突漏检

外部评审指出：冲突检测先按**完全相同的 `event_key`** 字符串分组（`backend/app/skills/conflict_detect.py` 第 144-148 行），且**空 event_key 的事件被整体跳过**。真实 LLM 输出常出现同一事件的 event_key 漂移（如 `warehouse_activity` / `east_warehouse_activity` / `warehouse_vehicle_event`），导致它们落入不同组、永不比较 → 冲突漏检。地点比较只做规范化字符串相等，无法处理别名（东部仓库 / 东仓 / 东部物资仓库 / A市东部仓库）。

目标：在冲突检测前对事件做**归一化分组**，提升真实输出下的冲突召回，同时**严格控制过度归并导致的误报**。不要 git commit；既有测试不回归；MOCK 演示 evaluate 仍 3/3。

## 设计（务必保守，宁可漏并不可错并）
新增 `backend/app/utils/event_normalize.py`，纯 Python、无外部依赖（可用标准库 `difflib`、`unicodedata`、`re`）：

### 1) `canonical_event_key(event: dict, alias_map: dict[str,str] | None = None) -> str`
- 规范化函数 `_norm(s)`：`unicodedata.normalize("NFKC", s).strip().casefold()`，再去除空白与标点（复用/参照 conflict_detect 已有 `LOCATION_PUNCTUATION_RE` 风格）。
- 主键 = 由结构化字段拼装：`_norm(subject)` + "|" + `_norm(action)` + "|" + `_norm(object)`。
- 若 subject 为空或 (action 与 object 均为空) → 回退到 `_norm(event_key)`；若仍为空 → `_norm(title)`；都为空 → 返回 `""`。
- 对 subject/object 中出现的地点别名，若提供 `alias_map`，先用别名规范化（见第 3 点）。

### 2) `group_events_for_conflict(events: list[dict], alias_map=None, similarity_threshold: float = 0.86) -> list[list[dict]]`
- 第一步：按 `canonical_event_key` 精确分组。**空 canonical key 的事件不再被丢弃**，而是各自单独成组（单元素组不会产生冲突，但不再静默丢弃；可在调用方对仍为空者发一条 warning）。
- 第二步（**保守相似度合并**）：仅在**同一 `_norm(subject)`** 内，对不同 canonical key 的组做合并候选；当两 canonical key 满足「其一为另一子串」**或** `difflib.SequenceMatcher(None,a,b).ratio() >= similarity_threshold` 时，用并查集合并。**不同 subject 一律不合并**（避免把不同事件凑成假冲突）。subject 为空的组不参与相似度合并。
- 返回分组后的事件列表（每组 ≥1 个事件）。

### 3) 地点别名（降低假地点冲突 + 帮助归并）
- `normalize_location_alias(value, alias_map) -> str`：先 `alias_map` 精确映射（大小写/NFKC 不敏感），再做结构化规约（去除常见行政前缀 `X市/X区/X县` 与常见设施后缀 `仓库/物资仓库/仓/基地/营地` 的轻量处理）。**结构化规约必须保守**，只在明显安全时套用；不确定就原样返回。
- alias_map 来源：可选配置文件，路径用新增配置项 `EVENT_ALIAS_PATH`（`app/config.py`，默认 None；空串→None validator 同 OCR 风格）。文件为 JSON：`{"surface": "canonical", ...}`。未配置则 alias_map 为空，仅结构化规约生效。**绝不内置特定军事地名词典**（避免硬编码业务），仅给机制 + 文档示例。

## 接入 conflict_detect
- `detect_conflicts` 改为用 `group_events_for_conflict(events, alias_map)` 取代当前「按 raw event_key 分组、空 key 丢弃」逻辑。每组内仍用现有 `itertools.combinations` 两两比较时间/地点/数量（**比较逻辑、阈值、warning 全部保持**）。
- 地点冲突比较：用 `normalize_location_alias` 规范化后再判等，别名相同 → 不报冲突（减少误报）；规范化后不同才报。
- conflict 的 `event_key` 字段：填该组的代表 canonical key（或组内首个非空原始 event_key，二选一，保持 schema 合法、稳定）。
- alias_map 在 skill 内按需加载一次（读 `EVENT_ALIAS_PATH`，失败则空 map + 脱敏 warning，非致命）。

## 透明性（可选但推荐）
- 在 `intelligence_extract` 合并后或 timeline 构建时，为每个 event/timeline item 附加 `canonical_event_key` 字段（便于前端/报告显示归并依据）。若改 schema，保持**向后兼容**（新增可选字段，默认 None），并同步前端 type-check 不破。如改动牵涉前端类型，补类型；不想动前端则只在后端结果 JSON 附加（前端 `extra` 容忍）。

## 必须验证的「召回提升」证据（单测，使用构造数据，不连真实模型）
新增测试证明：
1. 三个事件 event_key 漂移（warehouse_activity / east_warehouse_activity / warehouse_vehicle_event）但 subject/action/object 一致或高度相似 → 归一化后落入同组，且其中存在时间(>30min)或数量差异 → **被检出冲突**（旧逻辑下漏检）。
2. 地点别名（东部仓库 vs 东仓，经 alias_map）→ **不**误报地点冲突。
3. 不同 subject 的相似 key → **不**被错误合并（无假冲突）。
4. 空 event_key 且有 subject/action/object 的两事件 → 仍能归一化分组并检出冲突（旧逻辑会丢弃）。
5. 旧的精确同 event_key 用例语义不变（回归）。

## 验证（实际执行，最终消息逐条报告）
1. `cd backend && ./.venv/bin/pytest -q` 全绿（含上述新增）。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `./.venv/bin/python scripts/evaluate_demo.py` 仍 3/3，coverage/invalid 不变（演示数据 event_key 已一致，归一化不应改变其结果）。
4. 若动前端：`cd frontend && npm run type-check && npm run build` 通过。
报告：新增模块 API、保守合并策略、别名机制（配置项 + 无内置业务词典）、召回提升测试、回归结论。不要 git commit。
