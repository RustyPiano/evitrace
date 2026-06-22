# 任务：修复事件归一化审核（codex）发现的 4 个 MAJOR + 1 MINOR

独立审核指出当前 `event_normalize.py` 的模糊相似度合并与设施后缀规约**过度归并 → 假冲突**、**地点过度规约 → 漏报**、且**破坏了精确 event_key 旧语义**。按下述**更保守的精确匹配设计**重做，既有测试不回归、MOCK 演示仍 3/3。不要 git commit。

核心思想：**结构化 canonical key（subject|action|object）本身就能解决 event_key 漂移问题，无需任何模糊相似度合并。** 去掉模糊合并即可消除假冲突风险，同时保留 exact event_key 旧语义。

## 1) `backend/app/utils/event_normalize.py` 重做

### `_norm(value)`：保持（NFKC + strip + casefold + 去标点）。

### 主体/动作/对象一律只用 `_norm`，不做任何设施/行政规约（修 MAJOR 1）
- `canonical_structured_key(event) -> str`：
  - `subject=_norm(subject)`、`action=_norm(action)`、`object=_norm(object)`，**均不经 normalize_location_alias / 设施后缀**。
  - 若 `subject` 且 (`action` 或 `object`) → 返回 `f"{subject}|{action}|{object}"`；否则返回 `""`。
- `canonical_event_key(event, alias_map=None) -> str`（保留此函数名，供 conflict 标签用）：优先 `canonical_structured_key`；为空则回退 `_norm(event_key)`；再回退 `_norm(title)`；都空返回 `""`。**alias_map 不再参与 subject/object 规约**（参数保留以兼容签名，但不用于 key 构造）。

### 分组：union-find，仅用两个**精确**信号，**删除模糊相似度合并**（修 MAJOR 2 + MAJOR 4 + NIT）
`group_events_for_conflict(events, alias_map=None) -> list[list[dict]]`：
- 对每个事件计算两个键：`ek=_norm(event.get("event_key"))`（可空）与 `ck=canonical_structured_key(event)`（可空）。
- 用并查集对**事件下标**做合并：
  - 所有 `ek` 相同且**非空**的事件 union 到一起（**保留精确 event_key 旧语义** —— 即使 subject 不同也按旧逻辑同组，修 MAJOR 4）。
  - 所有 `ck` 相同且**非空**的事件 union 到一起（捕获 event_key 漂移但结构化字段一致的情况）。
  - 用 `dict[键->首个下标]` 实现 O(n) 合并，**不要**两两 combinations、**不要** SequenceMatcher / 子串合并。
- 既无 `ek` 也无 `ck` 的事件 → 各自单元素组。
- 返回分组（每组 ≥1）。所有事件必须无遗漏地出现在结果中。
- 说明：因为只用精确相等信号，新逻辑只会**新增**「漂移 event_key 但 subject/action/object 完全一致」的归并，不会引入旧逻辑没有的假阳性类别。

### 地点别名：仅精确 alias 查表 + `_norm`，**移除设施后缀/行政前缀默认规约**（修 MAJOR 3）
- `normalize_location_alias(value, alias_map=None) -> str`：`n=_norm(value)`；若 `n in alias_lookup` 返回其规范值，否则返回 `n`。**删除** `ADMIN_PREFIX_RE` / `FACILITY_SUFFIXES` 的默认剥离逻辑（这些会把 东部仓库/东部基地 压成 东部 导致漏报）。区分度后缀只能由用户显式 alias 合并。
- 同步删除不再使用的 `ADMIN_PREFIX_RE`、`FACILITY_SUFFIXES`、`_event_part`、`_subject_key`、`_should_merge`、`difflib`/`itertools` 等死代码。

## 2) `backend/app/skills/conflict_detect.py`
- `detect_conflicts` 用新的 `group_events_for_conflict(events, alias_map)`。
- 每组标签 `event_key`：取该组首个非空 `event.get("event_key")`，否则 `canonical_event_key(group[0])`，否则该组任一非空者；**保证 schema `event_key` 非空**（若极端全空，跳过该组的冲突生成或用占位安全串，且不报假冲突）。
- 地点冲突比较：仍用 `normalize_location_alias(_meaningful(loc), alias_map)` 判等（现在只做 alias+norm，不会过度规约）。
- 时间/数量比较逻辑、阈值、其它 warning 全部不变。

### MINOR：空键 warning 聚合（修 MINOR）
- 不要为每个空 canonical/event_key 事件各加一条 warning。改为**汇总一条**：记录前 N（如 5）个 event_id + 总数，例如「N 个事件缺少可归一化事件键，未参与冲突比对（示例: EVT-003, EVT-007, ...）」。

## 3) 测试更新/新增（`backend/tests/unit/test_conflict_detect.py`）
- **删除/改写**依赖旧「模糊相似度合并」「设施后缀规约」的断言。
- 新增/保留覆盖：
  1. 漂移 event_key 但 subject/action/object 一致（如 raw event_key=warehouse_activity / east_warehouse_activity，但 subject=车队、action=运输、object=弹药一致）→ 经 ck 归并、检出时间/数量冲突。
  2. **不再误并**：`车队|抵达|目标区` vs `车队|未抵达|目标区`（动作不同）→ 不同组、不报假冲突；`车队|装载|东部仓库` vs `车队|卸载|东部仓库` → 不报假冲突。
  3. **地点不再过度规约**：同一事件 location=东部仓库 vs 东部基地 → **报**地点冲突（除非用户显式 alias 合并）。
  4. **精确 event_key 旧语义**：两事件 event_key 相同但 subject 不同、时间差>阈值 → 仍同组并检出冲突（回归）。
  5. 显式 alias_map 把 东仓→东部仓库，则 东仓 vs 东部仓库 不报地点冲突。
  6. 空键事件聚合为单条 warning。

## 验证（实际执行，最终消息逐条报告）
1. `cd backend && ./.venv/bin/pytest -q` 全绿。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `./.venv/bin/python scripts/evaluate_demo.py` 仍 3/3，coverage/invalid 不变。
报告：新分组算法（两精确信号 union-find）、删除的死代码、地点别名收敛为仅 alias、四个 MAJOR 与 MINOR 各自如何修复、回归结论。不要 git commit。
