# EviTrace A/B Evaluation

由 evaluate_ab.py 生成。

- 生成时间：2026-06-23T00:43:52
- 案例数：3
- 运行模式：`real`
- LLM：`real` / `deepseek-v4-flash`
- Vision：`real`
- OCR：`http`
- ASR：`http`

A 臂为同案证据文本一次性直出报告；冲突召回为宽松启发式上界，只判断两个预期冲突取值是否同时出现，不判断是否真正指出矛盾。
B 臂为 EviTrace 证据链完整管线，统计结构化冲突、报告引用合法性和结论段落引用覆盖。

## A vs B

| Case | A conflict recall | B conflict recall | B spurious conflicts | A valid citation ratio | B valid citation ratio | A ungrounded conclusions | B ungrounded conclusions |
|---|---:|---:|---:|---:|---:|---:|---:|
| case_01_time_conflict | 1.00 | 1.00 | 0 | N/A | 1.00 | 8 | 0 |
| case_02_location_conflict | 1.00 | 1.00 | 0 | N/A | 1.00 | 11 | 0 |
| case_03_quantity_conflict | 1.00 | 0.00 | 1 | N/A | 1.00 | 11 | 0 |
| **Summary** | 1.00 | 0.67 | 1 | N/A | 1.00 | 30 | 0 |
