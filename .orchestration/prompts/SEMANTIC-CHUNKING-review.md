# 代码审核（只读，禁止修改/禁止 git）：解析语义分块

审核分支 `feat/semantic-chunking` 相对 `main` 的改动：`document_parse.py`（`_hard_split`/`_merge_to_chunks` + txt/docx/pdf 接入）、`config.py`、测试、docs。只报真实问题，给 文件:行 + 严重级，末行总评。

## 必查
1. **偏移正确性（最关键，关系到证据定位/citation match）**：合并块 `char_start/char_end` 是否准确指向源文本（txt/md 文档相对、pdf 页相对、docx 名义累加）？`_hard_split` 的偏移（含 `base_start`、strip leading/trailing）是否连续、不重叠、并集覆盖原文非空部分、无越界？content（"\n\n".join 或硬切片）是否仍使每个原始段落/句子是其子串（保 `_resolve_match` 子串解析）？
2. **无死循环/无丢内容**：`_hard_split` 的 `i` 是否每轮严格前进（含无边界、全空白窗口情形）？`_merge_to_chunks` 是否不丢段、不重复段、超长 unit 先 flush 再硬切、末尾 flush？空输入/空段/全空白 → 空结果不报错。
3. **边界硬切质量**：boundary 选取（≥max_chars*0.6 的最后一个 `[\n。！？!?.]`）是否合理；找不到边界时退化为 max_chars 硬切；不会产生 0 长或纯空白块。
4. **PDF 逐页 + page 维度**：仍逐页、不跨页合并、`page` 号正确、`paragraph=None`；整页无空行时 `_paragraph_spans` 返回整页 1 段并被正确合并/硬切。
5. **DOCX 名义偏移**：合成偏移（start/end + join sep）自洽、不影响下游（offsets 名义、content 为 join 文本）。
6. **配置**：两个新配置 alias/clamp/默认；代码用 `max(max_chars, target)` 保证 ≥target；monkeypatch 生效。
7. **回归**：`MAX_BLOCK_CHARS`/`_chunk_text` 移除后无悬挂引用；证据创建链路不变；mock 流程（`_default_mock_raw` 用 evidence[0]/[1]，单证据时 fallback）仍工作；demo 3/3（match 文本子串解析兼容合并块）。集成测试把「≥2 evidence」改「≥1」是否因合并合理（而非掩盖 bug）。
8. **测试质量**：合并、target 拆分、硬切边界/偏移、配置生效是否真覆盖；有无假绿。

## 输出
逐条发现 + 末行总评 PASS / PASS-WITH-FIXES / FAIL。只报真实问题。
