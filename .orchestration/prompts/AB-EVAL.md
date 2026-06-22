# 任务：A/B 对照实验脚手架（证据链 vs 大模型直出）+ 修正指标表述

外部评审指出：当前 100% 指标只证明**确定性管线**正确，未与「大模型直出报告」做对照，无法量化 EviTrace 的实际优势。需新增 A/B 评测脚手架，并在文档中如实区分「管线验证集指标」与「真实模型效果」。不要 git commit；既有测试/演示不回归。

## A/B 定义（同一套案例、同一个 LLM）
- **B 臂（EviTrace 证据链）**：跑现有完整管线（解析→证据→抽取→冲突→报告），得结构化冲突 + 报告 markdown + 引用校验。
- **A 臂（大模型直出）**：把同一案例的全部证据文本拼接，**一次** LLM 调用，提示「根据以下资料写一份情报分析报告」——**不**给证据编号体系、**不**做结构化抽取/冲突/引用约束，模拟「RAG 直接生成整篇报告」。

## 脚本 `scripts/evaluate_ab.py`
1. **复用** `scripts/evaluate_demo.py` 的案例与夹具装载方式（读同样的演示案例目录、`expected.json`、`configure_environment`/`install_fixtures` 等；导入或参照，不要重复造数据）。在隔离临时 DB + DATA_ROOT 下运行。
2. **运行模式**：脚本开头打印 `run_mode_metadata()`（mode/llm/vision/ocr/asr）。A 臂需要**真实 LLM**（`settings.effective_mock_llm == False`）：若当前为 mock LLM，则**跳过 A 臂**并明确打印「A 臂需真实 LLM，已跳过；仅运行 B 臂与管线指标」——绝不用 mock 文本伪造 A 臂数字。B 臂在任何模式都跑。
3. **B 臂指标**（每案例 + 汇总）：
   - `conflict_recall` = 命中的预期冲突 / 预期冲突总数（用 expected.json 的植入冲突；匹配按 type + 双方取值/事件，复用 evaluate_demo 的匹配口径）。
   - `spurious_conflicts` = 检出但不匹配任何预期的冲突数。
   - `valid_citation_ratio` = 报告中合法 `E-xxxx`（属于本案证据）/ 报告中全部 `E-xxxx`。
   - `ungrounded_conclusions` = 结论段落中无任何引用的段落数（用 `validate_report_citations`：`conclusion_paragraph_count - cited_conclusion_paragraph_count`）。
4. **A 臂指标**（仅真实 LLM 时）：对自由文本报告：
   - `conflict_recall`（启发式）：对每个预期冲突，若其**两个冲突取值**都出现在报告文本中（NFKC/casefold 容错）则记为「提及」。记 recalled/total。这是宽松上界（仅判提及，不判是否真正点出矛盾），文档需注明。
   - `valid_citation_ratio`：从自由文本抽 `E-xxxx`；A 臂未获编号体系，通常为 0 或无效（分母为 0 时记 N/A）。
   - `ungrounded_conclusions`：自由文本无证据编号体系，按「含事实断言但无 `E-xxxx` 的段落数」统计（可复用 citations 的段落切分 + 正则）。
5. **输出**：
   - stdout 打印「A vs B」每案例与汇总对照表。
   - 写 `scripts/ab_result.md`（Markdown 表格 + 运行模式 + 案例数 + 生成时间占位说明「由 evaluate_ab.py 生成」；**不要**写死/编造真实模型数字——只写本次实际运行得到的值；mock 跳过 A 臂时表中 A 列标 N/A 并注明原因）。
   - 退出码：脚本执行成功即 0（这是评测工具，不因 A 臂跳过而失败）。
6. **安全**：A 臂经现有 `LocalLLMClient`（不要直接 import httpx）；不打印任何 key；隔离 DB/DATA_ROOT，结束清理。

## 文档：如实修正指标表述
- `实验报告.md`：在 §7.2 演示评估指标处**新增一句明确边界**：这些是「**确定性管线验证集**上的流程完成率/预设冲突召回/引用格式覆盖」，**非**真实多模态模型识别准确率；真实模型效果由 §7.3 端到端联调（定性）与新增 A/B 对照（定量，见 `scripts/evaluate_ab.py` / `scripts/ab_result.md`）佐证。新增一小节 §7.4「A/B 对照实验（证据链 vs 大模型直出）」，说明方法与指标口径，结果以脚本实际产出为准（可引用 ab_result.md；若尚无真实运行数据，注明「需在真实 LLM 在线时运行 evaluate_ab.py 填入」）。
- `README.md`：在评估相关处加同样的一句边界说明 + 指向 `scripts/evaluate_ab.py` 的用法（如何在真实 LLM 下跑 A/B）。
- **不要**夸大；不要把 mock/跳过的 A 臂当作真实结果。已有「未对答案打分/临时隔离 DB」等表述保留。

## 验证（实际执行，最终消息逐条报告）
1. `cd backend && ./.venv/bin/pytest -q` 仍全绿（若给 evaluate_ab 抽出的可测函数加少量单测更好，但不强制连真实模型）。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. 在**当前 mock 模式**实际运行 `./backend/.venv/bin/python scripts/evaluate_ab.py`：B 臂跑通、A 臂正确跳过并打印原因、生成 `scripts/ab_result.md`、退出码 0。
4. `./backend/.venv/bin/python scripts/evaluate_demo.py` 仍 3/3（不回归）。
报告：脚本结构、A/B 指标口径与 A 臂启发式的局限、mock 下的实际输出摘要、文档改动位置与原文/改后表述。不要 git commit。
