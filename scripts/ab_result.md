# EviTrace A/B Evaluation

由 evaluate_ab.py 生成。

- 生成时间：2026-06-22T23:49:25
- 案例数：3
- 运行模式：`mock`
- LLM：`mock`
- Vision：`mock`
- OCR：`fixture`
- ASR：`fixture`
- A 臂状态：N/A，A 臂需真实 LLM，已跳过；仅运行 B 臂与管线指标

A 臂为同案证据文本一次性直出报告；冲突召回为宽松启发式上界，只判断两个预期冲突取值是否同时出现，不判断是否真正指出矛盾。
B 臂为 EviTrace 证据链完整管线，统计结构化冲突、报告引用合法性和结论段落引用覆盖。

## A vs B

| Case | A conflict recall | B conflict recall | B spurious conflicts | A valid citation ratio | B valid citation ratio | A ungrounded conclusions | B ungrounded conclusions |
|---|---:|---:|---:|---:|---:|---:|---:|
| case_01_time_conflict | N/A | 1.00 | 0 | N/A | 1.00 | N/A | 0 |
| case_02_location_conflict | N/A | 1.00 | 0 | N/A | 1.00 | N/A | 0 |
| case_03_quantity_conflict | N/A | 1.00 | 0 | N/A | 1.00 | N/A | 0 |
| **Summary** | N/A | 1.00 | 0 | N/A | 1.00 | N/A | 0 |
