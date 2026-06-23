# 代码审核（只读，禁止修改/禁止 git）：P1b 相关性预筛砍量

审核分支 `feat/free-tier-volume-cut` 相对 `main` 的 P1b 改动：新增 `backend/app/utils/relevance.py`、`intelligence_extract.py` 集成、`config.py`、测试、.env.example/docs。只报真实问题，给 文件:行 + 严重级，末行总评。

## 必查
1. **召回兜底正确性（最关键，情报工具不可静默丢关键证据）**：`select_relevant` 的「每文档保底 per_doc_min」是否真的对**每个**源文档生效（含全低分文档）？top_k=0 时集成是否完全不筛（no-op）？`len<=top_k` 时不筛？空 objective 时退化为按原序前 K（不报错、可预测）？
2. **确定性**：评分/排序平分是否一律用原始 index 升序破平？`select_relevant` 返回 `kept_indices` 是否按原始 index 升序（保证批次/合并/event_id 确定）？是否存在依赖 dict 无序/集合迭代序的非确定性？
3. **BM25/打分健壮性**：空文档、空语料、avgdl=0、df=0、全相同文档是否无除零/无异常？idf 负值是否被 MIN_IDF 兜底？高信号加权是否有界（不无限保留，仅 ×(1+boost)）、正则是否会误伤/漏判常见中文日期与数量？
4. **集成正确性**：预筛在去重之后、分批之前；`objective` 变量在该作用域已定义；`filtered_items` 重建后 `input_hashes` 基于预筛后集合（续跑一致：同 top_k+objective+证据 → 同选择 → 同 hash）；warning 披露保留/丢弃量；全量证据仍入库（只影响发给 LLM 的集合）。
5. **mock/demo 回归**：mock 路径不经过预筛；demo 默认 top_k=0 → 行为不变、3/3。
6. **配置**：两个新配置 alias/clamp/默认（0=关闭）正确；.env.example/docs 与实现一致、明确「按相关性取舍、需全量设 0」。
7. **测试质量**：是否真覆盖 tokenize（中文bigram/英文）、score（相关>无关、高信号加权、空 objective、无除零）、select（top_k、相关优先、**每文档兜底**、确定性、stats）、集成（top_k 小→只抽入选、披露、top_k=0 全量、top_k>=count no-op）、mock 不变；有无假绿。

## 输出
逐条发现 + 末行总评 PASS / PASS-WITH-FIXES / FAIL。只报真实问题。
