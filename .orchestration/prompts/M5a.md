# 任务：实现 EviTrace 里程碑 M5（第 1 部分：测试、演示数据、对照评估、前端构建检查）

M0–M4 已完成（全栈闭环，127 测试通过，前端可构建，MOCK_AI 默认）。本次做 **M5-01/02/03/04/05**（测试覆盖、演示数据、评估脚本、前端构建检查）。**不做** M5-06 Docker 生产化与 M5-07 README 终稿（留给下一部分）。

## 开始前必读
- `PLAN.md` 第 7 章（M5-01~05）、第 8 章、第 9 章测试矩阵。
- `SPEC.md` §14（验证与测试数据：演示数据/标注 expected.json/对照方式）、§15（验收标准，尤其 §15.2 质量：coverage≥0.9、invalid==0、植入冲突发现≥80%、四模态证据）、§5.7 冲突、§9.5 MOCK。
- **关键：理解既有 MOCK 机制**（先读代码确认）：
  - 每文件 sidecar fixture（OCR/ASR/video）：`backend/app/skills/utils.py` `sidecar_fixture()` 在任务 `original/` 目录按候选名查找：`{stored_name}.mock.json`、`{stored_name}.{suffix}.json`、`{original_name}.{suffix}.json`、`{stem}.{suffix}.json`。suffix 约定：图片 `ocr`、音频 `asr`、视频 `video`。
  - 提取 fixture：`backend/app/skills/intelligence_extract.py` 读 `data/tasks/{task_id}/mock/extraction.json`；事件/实体可用 `match`（证据内容子串）解析为真实 display_id，或用 `evidence_ids`。
  - `document_parse` 始终真实解析 TXT/MD/PDF/DOCX（无需 fixture）。

## 设计目标（演示要可信且确定性）
每个演示案例展示一个**跨模态**植入冲突：真实文本证据（brief/report 由 document_parse 真实解析）与 mock 的图片/音频/视频证据之间，经**真实冲突规则引擎**检出冲突，报告带真实 `[E-xxxx]` 引用。MOCK 仅替代「模型提取」与 OCR/ASR/视频解码，其余（解析、证据定位、冲突规则、引用验证、报告结构、权限、闭环）均为真实逻辑。

## M5-04 演示数据 `demo_data/`
创建三组（目录名严格如下）：
```
demo_data/
  case_01_time_conflict/
  case_02_location_conflict/
  case_03_quantity_conflict/
```
每组包含（虚构、非涉密内容）：
- `brief.txt`：含植入事实之一（如案例1写明“…于 14:00 …”）。
- `report.pdf`（或 `report.docx`）：补充资料，含另一处事实。
- `image.png`：含文字的图片（真实 PNG）。
- `audio.wav`：真实 WAV（可静音/简单波形，时长≤40s）。
- `video.mp4`：真实 MP4（ffmpeg 可用，可用静态背景+字幕生成，时长≤40s；必须含合法 `ftyp`，能通过上传 magic 校验）。
- sidecar fixtures（注入 mock 模态内容）：`image.ocr.json`、`audio.asr.json`、`video.video.json`（结构匹配各 skill 期望；音频/视频含 start_ms/end_ms、视频含帧）。让冲突的另一侧出现在某个模态里（如案例1音频转写出“16:30”）。
- `extraction.json`：定义实体/事件（含植入冲突的两侧，同一 `event_key`，用 `match` 子串引用真实/ mock 证据内容，使引用落在真实 display_id 上；事件 time_normalized 用 ISO）。覆盖三类：
  - case_01：时间冲突（如 14:00 vs 16:30，跨文本与音频）。
  - case_02：地点冲突（地点A vs 地点B，跨文本与图片/视频）。
  - case_03：数量冲突（如 3 辆 vs 5 辆，跨文本与音频/视频）。
- `expected.json`：按 SPEC §14.2 结构（expected_conflicts:[{type,left,right}]、required_evidence_modalities:["text","image","audio","video"] 等）。
- `README.md`：说明本案例植入的冲突与四模态分布。

**生成脚本 `scripts/build_demo_data.py`**：用 Python 可重复生成上述媒体文件（PDF 用 PyMuPDF、DOCX 用 python-docx、PNG 用 Pillow 写入文字、WAV 用标准库 `wave`、MP4 用 ffmpeg 子进程，ffmpeg 不可用时跳过 mp4 并告警）。文本/sidecar/extraction/expected/README 可由脚本写出或直接提交静态文件（择一，保证 `demo_data/` 内容齐全且可重现）。生成的媒体必须能通过后端上传 magic 校验。

## M5-05 对照评估脚本 `scripts/evaluate_demo.py`
- 对三组案例执行**完整真实流程**（用 FastAPI TestClient 或对运行中的后端发 HTTP；MOCK_AI=true）：
  1. seed/登录管理员，创建一个分析员并登录（或直接用管理员）；
  2. 每案例：创建任务→上传该案例 5 个媒体文件→把该案例的 sidecar fixtures 复制进任务 `original/`、`extraction.json` 复制进任务 `mock/`（脚本知道 task_id 与 data_root）→启动分析→轮询至 awaiting_review→取 results；
  3. 读取 `expected.json` 对照：发现冲突数 / 预期冲突数 → 冲突召回率；报告引用数 / 有效引用数 / 引用覆盖率 / 无效引用数；四模态是否均有证据。
- 输出 JSON 与 Markdown 表格，保存 `evaluation_result.md`（列：案例名、预期冲突数、发现冲突数、冲突召回率、报告引用数、有效引用数、引用覆盖率、无效引用数、四模态齐全）。
- 可选 baseline（不阻塞主系统）。
- 脚本要稳健：清理/隔离用临时数据目录或独立任务，不污染开发库；结束打印汇总。

## M5-01 后端单元测试（补齐最低覆盖）
确认/补齐以下模块有单元测试（多数已存在，缺则补，纯函数测试不依赖 DB）：文件类型与路径安全、证据编号、时间冲突、地点冲突、数量冲突、引用验证、权限依赖、MOCK_AI 输出校验。`cd backend && ./.venv/bin/pytest -q` 全绿。

## M5-02 API 集成测试（完整流程，SPEC §14.3 / PLAN M5-02）
补一个端到端集成测试覆盖：seed 管理员→管理员创建两个分析员→分析员A 建任务并上传 fixtures→分析员B 无法访问（404）→A 启动分析→轮询至完成→获取证据/结果/报告→修改冲突状态→下载报告→管理员可访问。（可复用既有 test_analysis_api，但要补齐“两个分析员 + B 不可访问 + 管理员可访问”的完整链路。）

## M5-03 前端构建检查
`cd frontend && npm run type-check && npm run build` 通过；确认**无硬编码开发地址**（无 `localhost:8000` 等写死在源码里的后端地址；应走相对 `/api` 或代理/配置）。报告检查结果。

## 验证（实际执行，最终消息报告）
1. `cd backend && ./.venv/bin/pytest -q` 全绿，报告总数。
2. 运行 `python scripts/build_demo_data.py` 生成演示数据（报告生成的文件与任何 ffmpeg 警告）。
3. 运行 `python scripts/evaluate_demo.py` 并附 `evaluation_result.md` 关键内容：**三组案例均完成分析、各自发现预期冲突（召回率达标）、coverage≥0.9 且 invalid==0、四模态均有证据**。若某项不达标，说明原因并修正 fixtures/extraction 直到达标。
4. 前端 type-check + build 通过、无硬编码地址。
不要运行 git commit。报告文件清单、evaluation_result.md 摘要、对 fixture/extraction 设计的说明、遗留项。
