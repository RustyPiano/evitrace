# 任务：让 EviTrace 真实云端 LLM（OpenAI 兼容）端到端可用 + 解耦 LLM/媒体 mock

用户暂无法本地部署模型，改用云端 OpenAI 兼容模型（DeepSeek）替代**本地 LLM**。已做真实端到端测试，发现两类真实问题，并需要一个配置解耦。请精确修复并保证既有测试不回归。**不要把任何 API key 写入代码或提交物**（密钥只在运行时通过环境变量传入）。

## 背景（已实测确认）
- 真实 LLM 连通正常（HTTP 200）。但 `intelligence_extract` 真实模式产出 0 实体/0 事件——原因：系统提示词只说“严格输出符合 schema 的 JSON”却**从未告诉模型 schema 长什么样**。实测 DeepSeek 抽出了正确信息但用了自创字段名：
  ```json
  {"events":[{"unit":"第3装甲连","time":"2026-06-01T14:00:00","location":"A镇","vehicle_count":3,"source":"E-0002"}, ...]}
  ```
  而我们的 `ExtractionResult/Event` 需要的是 `event_key/title/evidence_ids/...`，于是 ValidationError，最终事件为空。
- `report_generate` 真实模式总是走 fallback（warning：“模型报告结构不完整，已使用模板降级”），因为模型没产出严格的六个标题（`_has_required_report_sections` 要求 `## 一、…`～`## 六、…`）。

## 修复 1：intelligence_extract 真实模式提示词补全 schema（`backend/app/skills/intelligence_extract.py` `_run_real_extraction`）
- 重写 system/user 提示词，**显式给出目标 JSON schema 与一个具体示例**，字段名必须与 `app/schemas_analysis.py` 的 `ExtractionResult/Entity/Event/Quantity` 完全一致：
  - 顶层：`{"entities":[Entity...], "events":[Event...]}`
  - Entity：`{"type": 取值之一 person|organization|location|event|object|time|quantity, "name": str, "confidence": 0~1或null, "evidence_ids": ["E-0001"...]}`
  - Event：`{"event_key": "主体-动作-对象 的规范化短文本(用于归并同一事件)", "title": str, "subject": str|null, "action": str|null, "object": str|null, "time_text": "原始时间表述"|null, "time_normalized": "ISO8601 如 2026-06-01T14:00:00"|null, "location": str|null, "quantity": {"value": number, "unit": str}|null, "evidence_ids": ["E-0001"...](至少一个), "confidence": 0~1或null}`
- 关键语义写进提示词：① `evidence_ids` 必须取自输入里给出的 `[E-xxxx]` 编号；② **同一真实事件在不同证据中出现时，必须使用相同的 `event_key`**（这样规则引擎才能比对出时间/地点/数量冲突）——这是冲突检测的前提；③ 无法确定的字段填 null，不要编造；④ 只输出 JSON，不要 Markdown/代码围栏/解释。给一个与上面证据类似的 1-2 事件完整示例。
- 防御性：真实模式若某批 `generate_json` 多次校验失败会抛 INVALID_MODEL_OUTPUT（保持现状，让任务失败而非伪造）；但如果整个真实抽取最终 entities+events 全为空，向 SkillResult.warnings 追加一条明确 warning（如“真实模型未抽取到任何要素，请检查模型/提示词”），便于排查（不要因此伪造数据）。
- 可选（低风险才做）：为 `generate_json` 路径加 `response_format={"type":"json_object"}`（OpenAI/DeepSeek 兼容），但要兼容不支持该参数的本地服务——若不确定就**不要**改 client，只靠提示词修复（实测仅靠提示词即可，因为模型已返回干净 JSON，只是字段名错）。

## 修复 2：report_generate 真实模式提示词强制六段标题（`backend/app/skills/report_generate.py`）
- 真实模式提示词中明确要求模型**逐字输出**这六个二级标题：`## 一、任务概述`、`## 二、资料概况`、`## 三、事件时间线`、`## 四、主要冲突`、`## 五、综合分析结论`、`## 六、未确认事项`；并要求“一、二、五、六”中的事实性陈述带 `[E-xxxx]` 证据引用（“三、四”系统会用结构化数据覆盖，模型可留占位）。目的：让真实报告通过 `_has_required_report_sections`，不再每次降级到模板。
- 保留：生成后系统用结构化数据覆盖“三、四”（已实现 `_with_structured_fact_sections`）；保留 AI 声明与 fallback（模型确实失败时仍降级）。

## 修复 3：解耦 LLM-mock 与 媒体-mock（让真实 LLM + mock OCR/ASR/视频 可共存）
用户有云 LLM 但无本地 OCR(PaddleOCR)/ASR(faster-whisper)，需支持「LLM 真实、媒体走 fixture」。
- `app/config.py`：新增 `MOCK_LLM`、`MOCK_MEDIA` 两个可选布尔环境变量；当未显式设置时**默认回退到 `MOCK_AI`** 的值。提供解析后的有效值（如属性 `effective_mock_llm` / `effective_mock_media`）。`.env.example` 增补这两项与注释，并给出「云 LLM + mock 媒体」配置示例（如 `MOCK_AI=false`、`MOCK_MEDIA=true`、`LOCAL_LLM_BASE_URL/KEY/MODEL` 指向云端）。
- 接线：`llm_client`（默认 mock 判定）改用 `effective_mock_llm`；`image_ocr`/`audio_transcribe`/`video_parse` 的 mock-vs-real 判定改用 `effective_mock_media`；`registry` 健康探测与 `/admin/health` 中 LLM 用 effective_mock_llm、OCR/ASR/ffmpeg 用 effective_mock_media；保留各自的构造参数覆盖能力。
- **向后兼容**：仅设 `MOCK_AI` 时，两者都跟随它，现有所有测试行为不变。
- 测试：新增单测覆盖默认回退与组合（`MOCK_AI=false,MOCK_MEDIA=true` → 媒体走 mock、LLM 走真实判定；`MOCK_AI=true` → 全 mock）。不要发起真实网络请求（用现有可注入 mock 或仅断言判定标志/分支选择）。

## 文档
- README 增补一节「使用云端 OpenAI 兼容模型（无本地模型时）」：示例 env（`MOCK_AI=false`、`MOCK_MEDIA=true`、`LOCAL_LLM_BASE_URL`/`LOCAL_LLM_API_KEY`/`LOCAL_LLM_MODEL`），说明此模式下文本/PDF 真实解析 + 云 LLM 抽取/报告 + OCR/ASR/视频用确定性 fixture；提醒 key 放 `.env`（已 gitignore）不要提交。

## 验证（实际执行，最终消息报告；不要发起真实外网调用做单测）
1. `cd backend && ./.venv/bin/pytest -q` 全绿（报告总数，应≥137 + 新增）。
2. `cd frontend && npm run type-check && npm run build` 通过（若动了前端，应只动很少）。
3. AST 3.11 安全：`./.venv/bin/python scripts/check_annotation_names.py` 通过（如改了带注解文件）。
4. `./backend/.venv/bin/python scripts/evaluate_demo.py` 仍 3/3（MOCK 路径不回归）。
5. 报告：修改文件清单、两处提示词关键改动摘要、解耦设计与默认回退、README 增补位置。
不要运行 git commit；不要写入或打印任何真实 API key。
