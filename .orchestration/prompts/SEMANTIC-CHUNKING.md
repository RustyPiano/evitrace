# 任务：解析语义分块——把短段落合并到目标尺寸（治本「过度切分」）

背景（已确诊）：`backend/app/skills/document_parse.py` 对文本过度切分——txt/md 每「空行段落」一条证据、docx 每非空段落一条、pdf 每 1000 字一窗一条。导致 62 个小文件产生 ~8121 条证据（~131 条/文件）。本任务改为**目标尺寸的语义合并分块**：把连续短段落贪心合并到目标字数的「富块」，超长单元按边界硬切。统一 txt/md/docx/pdf 四类。**只改 `document_parse`（文本文档）**，不动 OCR/ASR/视频分块。

收益：证据数大降、每条证据语义更完整（抽取质量更好）、抽取批次按字符预算装满（批数下降）。demo 的 mock fixture 用 `"match"` 文本子串解析 evidence_id（非硬编码 display_id），合并后句子仍是块内容子串 → **demo 不受影响**，但仍须实跑确认 3/3。不写真实 key、不 git commit。

## 1) 配置（`backend/app/config.py`，Field+alias+clamp，同现有风格）
- `parse_chunk_target_chars: int`，alias `PARSE_CHUNK_TARGET_CHARS`，默认 `800`，clamp `100..8000`（合并目标：连续段落累加到该字数即收一块）。
- `parse_chunk_max_chars: int`，alias `PARSE_CHUNK_MAX_CHARS`，默认 `1600`，clamp `200..16000`（单个超长段落的硬切上限；代码内用 `max(parse_chunk_max_chars, parse_chunk_target_chars)` 保证 ≥ target）。

## 2) 分块算法（`backend/app/skills/document_parse.py`）
保留 `_paragraph_spans(text)`（空行切段，返回 `(text,start,end)`，document/page 相对偏移）。新增：

### `_hard_split(text, base_start, max_chars) -> list[tuple[str,int,int]]`
把单个超长 unit 切成 ≤max_chars 的片，**优先在边界处断**：
- 从 `i=0` 起，`end=min(i+max_chars, n)`；若 `end<n`，在 `window=text[i:end]` 内寻找位置 ≥ `max_chars*0.6` 的最后一个边界字符（`[\n。！？!?\.]` 之一）的结束位置，作为 `end`（找不到则用 max_chars 硬切）。
- 片 = `text[i:end]`；用 strip 后的非空白范围算 `char_start/char_end`（相对 `base_start`，参照现有 `_chunk_text` 的 leading/trailing 处理）；跳过纯空白片。
- 返回 `(piece_text_stripped, base_start+chunk_start, base_start+chunk_end)` 列表；`i=end` 继续。

### `_merge_to_chunks(spans, target, max_chars) -> list[tuple[str,int,int]]`
贪心合并：
```
max_chars = max(max_chars, target)
chunks=[]; cur=[]; cur_start=None; cur_end=None; cur_len=0
flush(): 若 cur 非空 → chunks.append(("\n\n".join(cur), cur_start, cur_end)); 清空
for (t,s,e) in spans:
    if len(t) > max_chars:
        flush()
        chunks.extend(_hard_split(t, s, max_chars))   # 已是块
        continue
    if cur and cur_len + len(t) > target:
        flush()
    if not cur: cur_start = s
    cur.append(t); cur_end = e; cur_len += len(t)
flush()
return chunks
```
- chunk 内容 = `"\n\n".join(段落原文)`（可读、且每段原文仍是其子串，保 match 解析）。
- `char_start`=首段 start，`char_end`=末段 end。

### 各 parser 改为「切段 → 合并 → 每块一证据」
- `_parse_text`：`spans=_paragraph_spans(text)` → `chunks=_merge_to_chunks(spans, settings.parse_chunk_target_chars, settings.parse_chunk_max_chars)` → `for index,(content,start,end) in enumerate(chunks,1): items.append(_evidence(content, None, index, start, end))`。
- `_parse_docx`：把非空段落收成 spans（合成累加偏移：`start=offset; end=offset+len(text); offset = end + 2`），再 `_merge_to_chunks` → 每块 `_evidence(content, None, index, start, end)`。
- `_parse_pdf`：**逐页**：`spans=_paragraph_spans(page_text)`（页相对偏移；若整页无空行→返回整页 1 段，超长则被 `_merge_to_chunks` 内 `_hard_split`）→ `_merge_to_chunks(...)` → 每块 `_evidence(content, page_index, None, start, end)`。**保持 page 维度**（不跨页合并），page 号不变。
- `_evidence(...)` 签名/locator 结构不变（`{kind:text, page, paragraph, char_start, char_end}`，paragraph 现为块序号）。
- 删除/替换旧 `MAX_BLOCK_CHARS=1000` 与 `_chunk_text`（被 `_merge_to_chunks`/`_hard_split` 取代；若其它处引用 `_chunk_text` 则一并改）。

## 3) 不变量与兼容
- 仍跳过纯空白；content 非空。
- 偏移语义：txt/md 文档相对、pdf 页相对、docx 名义累加——与现状一致。
- 证据创建/入库链路（`parse_service` → `result_service.create_evidence_batch`）不变：每块 → 一条 Evidence。
- 下游 `_resolve_match`（按 `match in content` 子串解析）天然兼容合并块。
- 与抽取期去重/相关性预筛/批量正交：合并只改「证据粒度」，更粗的块让批次按 `BATCH_MAX_CHARS` 装满 → 批数下降。

## 4) 文档（`docs/DEPLOYMENT.md` 性能与成本节，加一小段）
说明：文本解析采用目标尺寸语义分块（连续短段落合并为富块、超长按边界硬切），由 `PARSE_CHUNK_TARGET_CHARS`/`PARSE_CHUNK_MAX_CHARS` 控制；相比旧版「每段/每1000字一条」大幅减少证据条数、提升每条语义完整度，与去重/相关性预筛/限流冷却协同降低大语料批数与成本。

## 验证（实际执行，最终消息逐条报告）
1. `cd backend && ./.venv/bin/pytest -q` 全绿。**更新/新增**测试（`backend/tests/unit/test_document_parse_skill.py`）：
   - 更新 `test_txt_parse_splits_on_blank_lines_and_skips_empty_blocks`：短的 "Alpha paragraph\n\n\nBeta paragraph" 现合并为 **1 条**，content 含两段（`"Alpha paragraph"` 与 `"Beta paragraph"` 均为子串），locator paragraph=1、char_start/end 跨两段。
   - 更新 `test_docx_parse_reads_non_empty_paragraphs`：两短段合并为 1 条（content 含两段文本）。
   - 保留/确认 `test_pdf_parse_preserves_page_numbers`：每页短文 → 每页 1 块、page=[1,2]（逐页不跨页）。
   - 新增 **合并**：多条短段落（总长 < target）→ 1 块；累计超过 target → 切成多块（块边界在段落处）。
   - 新增 **硬切**：单个超长段落（> max_chars）→ 多块、每块 ≤ max_chars、优先在句末/换行断、偏移连续不重叠、并集覆盖原文非空部分。
   - 新增 **配置生效**：monkeypatch target/max → 块数随之变化；默认值行为可复现。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `backend/.venv/bin/python scripts/evaluate_demo.py` 仍 **3/3**、recall/coverage/invalid 不变（demo 用 match 文本解析；如个别 case 因合并导致引用解析变化，**优先确认 match 文本仍是合并块子串**，一般无需改 fixture；若确有必要，调整 demo fixture 的 match 文本而非削弱合并）。
4. `cd frontend && npm run type-check && npm run build`（若未动前端可注明跳过）。
报告：分块算法（合并+边界硬切）、四类 parser 接入、locator 语义、证据数下降的直观示例、各测试结果、demo 3/3。**不要 git commit。**
