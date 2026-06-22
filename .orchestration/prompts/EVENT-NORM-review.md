# 代码审核（只读，禁止修改）：事件归一化（canonical_event_key）

独立审核新增的事件归一化分组（降低真实 LLM 输出的冲突漏检）。核心风险是**过度归并产生假冲突**（false positive）与**地点归一化过度导致漏判**（false negative）。

## 范围
`backend/app/utils/event_normalize.py`、`backend/app/skills/conflict_detect.py`、`backend/app/config.py`(新增 `EVENT_ALIAS_PATH`)、`backend/tests/unit/test_conflict_detect.py`。

## 必查项（只报真实问题，给文件:行）
1. **过度归并（最关键）**：`group_events_for_conflict` 的相似度合并是否**严格限定同一 `_norm(subject)`**？不同 subject 是否绝不合并？`_should_merge` 的子串判定 `left in right or right in left` 是否可能把同 subject 下**本应区分**的不同事件错并、从而产生**假冲突**？阈值 0.86 是否合理？给出能触发误并的输入（若有）。
2. **地点归一化**：`normalize_location_alias` 的行政前缀 `ADMIN_PREFIX_RE`、设施后缀 `FACILITY_SUFFIXES` 规约——是否存在把短地名规约成空/单字、或把两个**真实不同**地点（如 东部仓库 vs 东部基地）规约成相同导致**漏报地点冲突**的情况？`len(candidate)>=2`/`>=1` 守卫是否足够？是否可能抛异常（空串、None、纯标点）。
3. **回归**：精确相同 `event_key` 的旧用例语义是否完全不变？空 `event_key` 但无 subject/action/object/title 的事件——是否安全成为单元素组、warning 是否只对真正空键事件触发（不刷屏）、是否不再被静默丢弃但也不产生假冲突？
4. **冲突标签/约束**：合并组的 `conflict.event_key` 取值是否始终为合法非空字符串（schema `event_key` min_length=1）？merged 组 `group[0]` 取 canonical 是否稳定？union-find（find/union 路径压缩）是否正确、无环/无丢组？所有事件是否都被保留（keyed + empty + merged 无遗漏）。
5. **别名加载安全**：`_load_event_alias_map` 失败/非 JSON/非 dict 是否非致命且 warning **脱敏**（不含路径/凭证）？`lru_cache` 缓存 key 是否仅为 path（注意热更新失效——可接受但指出）？`event_alias_path` 空串→None 校验是否生效。
6. **性能**：同 subject 下 keys 两两 `combinations` + SequenceMatcher，事件量大时复杂度是否可接受（指出但不必阻塞）。

## 输出
每条发现：严重级（BLOCKER/MAJOR/MINOR/NIT）、文件:行、问题、最小修复建议。末行总评 PASS / PASS-WITH-FIXES / FAIL + 合并前必修项。只报真实问题。
