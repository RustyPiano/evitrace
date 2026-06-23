# 任务（P1b）：相关性预筛砍量（无向量库 + 召回兜底 + 透明披露）

背景：62 个小文件 → 去重后仍 4237 条证据 → 142 批，免费档限流跑不完。本任务在抽取前**按任务目标做相关性预筛**，把 4237 砍到 top-K，使批数大降、在免费档可控完成。**这是对召回敏感的功能**（情报工具不能静默丢关键证据），因此：**默认关闭（opt-in）、多重召回兜底、warnings 透明披露丢弃量**。无新依赖、纯 Python、确定性、mock 路径不变、demo 3/3、不写真实 key、不 git commit。

## 1) 配置（`backend/app/config.py`，Field+alias+clamp）
- `extract_relevance_top_k: int`，alias `EXTRACT_RELEVANCE_TOP_K`，默认 `0`（0=关闭预筛），clamp `0..100000`。
- `extract_relevance_per_doc_min: int`，alias `EXTRACT_RELEVANCE_PER_DOC_MIN`，默认 `1`，clamp `0..1000`（预筛启用时每个源文档至少保留的最高分证据数，防整篇文档被丢）。

## 2) 新模块 `backend/app/utils/relevance.py`（纯函数、可单测、无依赖）
- `def tokenize(text: str) -> list[str]`：NFKC + casefold；提取 **CJK 字符 bigram**（连续 CJK 串内相邻两字，长度1则取单字）+ ASCII 词（正则 `[a-z0-9]+`）。用于中英混合的词项重叠，不依赖 jieba。
- `def score_documents(objective: str, docs: list[str]) -> list[float]`：实现紧凑 **BM25**（k1=1.5, b=0.75）：
  - query 词项 = `set(tokenize(objective))`；语料 = 各 docs 的 tokens。
  - idf 用标准 BM25 公式（带 +0.5 平滑、max(…, 极小正数) 防负/零）。
  - 每文档分 = Σ_term idf·(tf·(k1+1))/(tf + k1·(1-b+b·dl/avgdl))。
  - **高信号加权**：若该 doc 文本命中日期/时间或数量（数字+单位/“辆/人/枚/架/艘/公里/时/分”等，或 ISO/常见中文日期、HH:MM）→ 分数 ×(1+`HIGH_SIGNAL_BOOST`)（如 0.25）。日期/数字是冲突检测的燃料，提升其入选概率（**有界**，不无限保留）。
  - 返回与 docs 等长的分数列表；空 objective → 全 0（调用方据此退化为「按原序取前 K」或不筛，见下）。
- `def select_relevant(items, objective, top_k, per_doc_min, doc_key) -> tuple[list[int], dict]`：
  - `items`: 证据列表；`doc_key(item)->str` 取源文档标识（用 file id/original_name）。
  - 计算 `score_documents(objective, [text(item) for item])`。
  - 选取规则（确定性，平分用原始 index 升序破平）：
    1. 按分数降序取前 `top_k` 的索引集合 `selected`。
    2. **每文档兜底**：对每个文档，若其在 selected 中的条目数 < `per_doc_min`，补入该文档分数最高的若干条直至达到 per_doc_min（该文档不足则全取）。
  - 最终 `kept_indices` = selected ∪ 兜底，**按原始 index 升序**返回（保持与现有批次/合并/event_id 的确定性）。
  - 返回 stats：`{"original": len(items), "kept": len(kept_indices), "dropped": len(items)-len(kept), "top_k": top_k, "per_doc_min": per_doc_min}`。
  - `objective` 为空或全 0 分：按原序取前 `top_k`（仍受 per-doc 兜底）——保证可预测、不报错。

## 3) 集成（`backend/app/skills/intelligence_extract.py` 的 `_run_real_extraction`）
- 在现有 `_prefilter_evidence`（去重/空白）**之后**、`_batch_evidence` **之前**加入：
  ```python
  top_k = settings.extract_relevance_top_k
  if top_k > 0 and len(filtered_items) > top_k:
      objective = str(task.get("objective") or "")
      kept_idx, rel_stats = select_relevant(
          filtered_items, objective, top_k,
          settings.extract_relevance_per_doc_min,
          doc_key=lambda e: str((e.get("file") or {}).get("id") or (e.get("file") or {}).get("original_name") or ""),
      )
      filtered_items = [filtered_items[i] for i in kept_idx]
      warnings.append(
          f"已按相关性预筛：从 {rel_stats['original']} 条相关排序保留 {rel_stats['kept']} 条"
          f"（每文档≥{rel_stats['per_doc_min']}，top_k={rel_stats['top_k']}），"
          f"其余 {rel_stats['dropped']} 条未进入本次分析；如需全量请调大或关闭 EXTRACT_RELEVANCE_TOP_K"
      )
  ```
- 若 `top_k==0` 或 `len(filtered_items)<=top_k` → 不筛（no-op），行为完全不变。
- **mock 路径不经过此处**（仅 `_run_real_extraction`），保持不变。
- 注意：相关性预筛只决定「发给 LLM 的证据」；全量证据仍入库、证据面板仍可见（与去重同语义）。input_hash 基于发送批次内容计算，预筛改变集合时 hash 自然变化（续跑一致性不受影响）。

## 4) 文档（`.env.example` + `docs/DEPLOYMENT.md`）
- `.env.example`：在抽取相关项附近加：
  ```
  # 相关性预筛（按任务目标排序只抽取最相关的 top-K 条证据，0=关闭）。
  # 大语料/免费档限流时建议开启（如 300）：批数大降、可控完成；会按相关性丢弃其余证据，
  # 已做每文档保底+高信号(日期/数量)加权+warnings 披露丢弃量。需要全量分析则设 0。
  EXTRACT_RELEVANCE_TOP_K=0
  EXTRACT_RELEVANCE_PER_DOC_MIN=1
  ```
- `docs/DEPLOYMENT.md` 性能与成本节加一小段：解释相关性预筛是 opt-in 的根因级砍量手段、召回兜底（每文档保底+高信号加权）、透明披露、以及它与去重/续跑/限流冷却如何配合让免费档大语料可控完成；明确「这是按相关性取舍，需全量时设 0」。

## 验证（实际执行，最终消息逐条报告；单测纯函数+注入假 client，不连外网）
1. `cd backend && ./.venv/bin/pytest -q` 全绿。新增测试：
   - `relevance.tokenize`：中文 bigram + 英文词；NFKC/casefold。
   - `score_documents`：含 objective 词项/高信号的文档分数 > 无关文档；空 objective 全 0；无除零异常。
   - `select_relevant`：top_k 生效；相关文档优先入选；**每文档兜底**（构造某文档全部低分仍保留 per_doc_min 条）；确定性（平分按 index）；stats 正确；objective 空时按原序取前 K。
   - 集成：注入计数假 client，`extract_relevance_top_k` 设小（如 2）+ 多文档证据 → 实际抽取批只覆盖入选证据（generate_json 仅就入选批被调用）、warning 含披露、其余证据未发送；`top_k=0` → 全量发送（无预筛）；`top_k>=count` → no-op。
   - 回归：mock 单批不变；去重→预筛两段 stats/warnings 并存正确。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `backend/.venv/bin/python scripts/evaluate_demo.py` 仍 3/3（demo 小语料、默认 top_k=0 → 不筛，行为不变）。
4. 前端未改可注明。
报告：tokenize/BM25/高信号加权、select 规则与召回兜底、集成点与披露、默认关闭语义、各测试结果。**不要 git commit。**
