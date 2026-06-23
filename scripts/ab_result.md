# EviTrace A/B Evaluation

由 evaluate_ab.py 生成。

- 生成时间：2026-06-23T09:12:59
- 案例数：3
- 运行模式：`hybrid`
- LLM：`real` / `deepseek-v4-flash`
- Vision：`mock`
- OCR：`fixture`
- ASR：`fixture`

三组定义：A0(朴素直出) 为旧版无编号、无引用要求的一次 LLM 直出；A(带引用直出) 为同一证据编号、逐事实引用要求的一次 LLM 直出；B(证据链) 为 EviTrace 证据链完整管线。
`citation_presence` 为事实性段落中出现 `E-xxxx` 引用的比例；`valid_citation_ratio` 为报告中合法 `E-xxxx` 引用数 / 全部 `E-xxxx` 引用数。
`conflict_recall*` 为宽松启发式上界：只判断两个预期冲突取值是否同时出现，未判定报告是否真正点明矛盾。
`spurious_conflicts(B)` 仅适用于 B 组结构化冲突输出。

## A0 vs A vs B

| Case | Group | citation_presence | valid_citation_ratio | ungrounded_conclusions | conflict_recall* | spurious_conflicts(B) |
|---|---|---:|---:|---:|---:|---:|
| case_01_time_conflict | A0(朴素直出) | 0.00 | N/A | 4 | 1.00 | N/A |
| case_01_time_conflict | A(带引用直出) | 0.62 | 1.00 | 3 | 1.00 | N/A |
| case_01_time_conflict | B(证据链) | 0.86 | 1.00 | 0 | 1.00 | 0 |
| case_02_location_conflict | A0(朴素直出) | 0.00 | N/A | 4 | 1.00 | N/A |
| case_02_location_conflict | A(带引用直出) | 0.67 | 1.00 | 3 | 1.00 | N/A |
| case_02_location_conflict | B(证据链) | 0.86 | 1.00 | 0 | 1.00 | 0 |
| case_03_quantity_conflict | A0(朴素直出) | 0.00 | N/A | 9 | 0.00 | N/A |
| case_03_quantity_conflict | A(带引用直出) | 0.70 | 1.00 | 3 | 0.00 | N/A |
| case_03_quantity_conflict | B(证据链) | 0.86 | 1.00 | 0 | 1.00 | 0 |
| **Summary** | A0(朴素直出) | 0.00 | N/A | 17 | 0.67 | N/A |
| **Summary** | A(带引用直出) | 0.67 | 1.00 | 9 | 0.67 | N/A |
| **Summary** | B(证据链) | 0.86 | 1.00 | 0 | 1.00 | 0 |
