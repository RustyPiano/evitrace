# 任务：公平 A/B —— A 组同样获得证据编号 + 强制逐事实引用

外部评审指出当前 A/B 不公平：A 组（大模型直出）只拿到无编号的纯文本、也没被要求引用，却被按"无依据结论/无有效引用"扣分；这更多证明"平台强制了引用规则"，而非"B 的引用语义更对"。需让 A 组**同样获得 `[E-xxxx]` 证据并被要求逐事实引用、显式指出冲突**，使对照聚焦于"流程结构"而非"是否被要求引用"。不要 git commit；既有测试不回归。

## 改 `scripts/evaluate_ab.py`
### A 组提示词（`build_direct_prompt`）公平化
- 证据按 `[E-xxxx] 内容` 逐条给出（与 B 组同一套证据、同样的编号），不再用"资料1/资料2"无编号格式。
- 指令明确要求：①每条事实性结论必须在句末标注支持它的证据编号 `[E-xxxx]`；②若发现同一事件存在时间/地点/数量矛盾，必须**显式指出冲突**并各自标注来源；③只能使用给定证据，不得编造编号。
- 仍是**一次** LLM 调用、自由生成（不走结构化抽取/规则冲突/模板），代表"会引用的直出基线"。

### A 组指标（现在可公平计算）
- `valid_citation_ratio`：A 报告中合法 `E-xxxx` / 全部 `E-xxxx`（A 现在会引用，分母通常>0，指标有意义）。
- 新增 `citation_presence`：A 的事实性段落中含 `[E-xxxx]` 的比例（"引用存在率"）。
- `ungrounded_conclusions`：仍统计无引用的结论段（现在 A 被要求引用，该值反映 A 是否照做）。
- `conflict_recall`：保持宽松启发式上界（两个冲突取值是否同时出现），并在输出/文档**注明其为上界、未判定是否真正点明矛盾**。
- B 组指标不变。

### 保留朴素直出作为第三基线（A0）
- 新增 `build_naive_prompt`（即旧的无编号、无引用要求版本）与对应 A0 行；表格列出 **A0(朴素直出) / A(带引用直出) / B(证据链)** 三组，便于显示"仅给格式要求(A0→A)"与"走完整流程(A→B)"各自的贡献。
- A0/A 均需真实 LLM；mock 模式下两者都标 N/A 并说明。

### 输出
- `markdown_table` 与 `ab_result.md` 改为三组对照（A0 / A / B），含 `citation_presence`、`valid_citation_ratio`、`ungrounded_conclusions`、`conflict_recall`、`spurious_conflicts(B)`。
- 顶部说明三组定义与"conflict_recall 为宽松上界"的诚实声明。

## 测试（`backend/tests/unit/test_evaluate_ab.py` 更新/新增，不连真实模型）
- `build_direct_prompt` 含 `[E-xxxx]` 与引用要求；`build_naive_prompt` 不含。
- `citation_presence`/`valid_citation_ratio` 计算正确（构造含合法/非法编号的文本）。
- A0/A 在 mock 下被跳过为 N/A。

## 验证（实际执行，最终消息逐条报告；先用 mock 跑通结构，真实重跑由架构师在 code 合入后单独执行）
1. `cd backend && ./.venv/bin/pytest -q` 全绿。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. mock 模式 `./backend/.venv/bin/python scripts/evaluate_ab.py`：三组结构正确、A0/A 标 N/A、生成 ab_result.md、退出 0。
4. `./backend/.venv/bin/python scripts/evaluate_demo.py` 仍 3/3。
报告：A 组公平化提示词要点、三组指标口径、citation_presence 定义、mock 输出摘要。不要 git commit。
