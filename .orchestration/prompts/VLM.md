# 任务：新增"视觉理解"Skill（VLM 对关键帧/图片做画面描述），补齐"视频只有OCR"的短板

现状问题（已确认）：`video_parse` 对关键帧只做 OCR（仅提取文字），无法理解画面语义；`image_ocr` 对图片同样只读文字。需要新增一个**视觉理解（VLM）能力**：用 OpenAI 兼容的视觉模型对图片/视频关键帧生成场景描述（场景/目标/车辆/人员/动作），作为新的证据卡，与 OCR(文字)、ASR(音频) 互补，并自动进入要素抽取/冲突/报告链路。先读相关代码再实现，保持既有测试不回归。**不要把任何真实 API key 写入代码或提交物**。

## 必读
- `app/skills/{base,registry,image_ocr,video_parse,audio_transcribe,utils}.py`、`app/services/{parse_service,llm_client}.py`、`app/config.py`、`app/skills/intelligence_extract.py`（看证据如何被消费）、`app/services/admin_service.py`（健康）、`frontend/src/components/EvidencePanel.vue`、`backend/tests/unit/test_skill_registry.py`、`.env.example`、`README.md`。
- SPEC §5.4（证据/locator）、§5.9（Skill 系统）、§9.5（MOCK）、§12（安全/离线）、NFR-001。

## 设计（请按此实现）

### 1) 独立 VLM 客户端 `app/services/vision_client.py`
- `VisionClient`，OpenAI 兼容 Chat Completions，**支持图像输入**：消息用多模态 content 数组 `[{"type":"text","text":...},{"type":"image_url","image_url":{"url":"data:image/<ext>;base64,..."}}]`（本地帧/图片读出后转 base64 data URL，离线，不外链）。
- 配置（新增，独立于文本 LLM）：`VLM_BASE_URL`、`VLM_API_KEY`、`VLM_MODEL`、复用 `LLM_TIMEOUT_SEC`。
- 方法 `describe_image(image_path, prompt) -> str`：返回画面描述文本。
- MOCK 感知：受 `settings.effective_mock_media` 控制（视觉理解属"媒体"能力）。MOCK 时不联网，返回确定性占位描述（可结合文件名/帧序号），或读取 sidecar fixture（见下）。
- 真实模式：若 `VLM_MODEL/VLM_BASE_URL` 未配置 → 抛明确 RuntimeError（调用方据此降级为 warning，不崩、不影响 OCR/ASR）。错误信息脱敏（复用 `health_details.redact_health_detail`），超时/不可达给清晰错误。**业务 skill 不得直接 import httpx 调 VLM**，都走 VisionClient。

### 2) 新增第 8 个 Skill：`visual_understand`（`app/skills/visual_understand.py` + 注册）
- `SkillManifest(id="visual_understand", name="视觉理解", version="1.0.0", description="对图片与视频关键帧生成画面描述", enabled_by_default=True, required=False, input_types=["jpg","jpeg","png","mp4"], output_type="evidence_list")`。
- 在 `registry.py` 注册为第 8 个 skill（非必需、可启停）。**更新所有"7 个 skill"的断言/文档为 8**（test_skill_registry、启动 seed、admin skills 测试、README/SPEC 注解处如有）。required 仍只有 3 个分析 skill。
- 健康探测：`check_skill_health` 增加 `visual_understand` 分支——`effective_mock_media=True` 时 skipped/healthy；真实模式校验 VLM 配置存在（缺则 unavailable，错误脱敏）。

### 3) 接入解析编排（图片 + 视频帧都要能被描述）
- **图片**：让 image 模态除 `image_ocr`(文字证据) 外，再产出**画面描述证据**。实现方式：在 `parse_service.parse_all_files` 中支持"一个文件可运行多个适用 skill"——image 文件先跑 `image_ocr`，若 `visual_understand` 启用则再跑视觉描述，合并证据；单个 skill 失败只 warning、不影响另一个。证据：`modality="image"`, `evidence_type="image_caption"`, `locator={"kind":"image"}`（整图，无 bbox 或 bbox=null），content=描述文本。
- **视频**：`video_parse` 已抽帧并对帧做 OCR；**复用同一批帧**，当 `visual_understand` 启用时对每个关键帧再调 VisionClient 生成描述，产出 `evidence_type="video_frame_caption"`, `modality="video"`, `locator={"kind":"video_frame","timestamp_ms":...,"frame_path":...}`。不要为视频另起一套抽帧（避免重复/资源浪费）。视觉描述失败只 warning，OCR/音轨证据照常。
- 仍保证：解析阶段不写死任务/run 终态；单文件/单 skill 失败隔离；帧/派生路径安全（沿用现有 resolve+前缀校验）。

### 4) MOCK fixtures
- 沿用现有 sidecar 机制（`app/skills/utils.py` 的候选名查找），新增 suffix `caption`：图片 `image.caption.json`（如 `{"caption":"..."}` 或 `{"captions":["..."]}`），视频 `video.caption.json`（按帧 `{"frames":[{"timestamp_ms":...,"caption":"..."}]}`）。找不到则用内置确定性默认描述（保证 MOCK 下也能产出画面描述证据，便于无 VLM 演示）。给 demo_data 三组各补一个合理的 caption sidecar（描述与该案例场景一致，例如车辆数量/地点，可与冲突呼应但不要伪造与 OCR/ASR 矛盾的内容）。

### 5) 前端 EvidencePanel
- 识别新 `evidence_type`（image_caption / video_frame_caption）：image_caption 显示原图 + 描述文本；video_frame_caption 显示关键帧缩略图 + 描述 + 可跳转视频 timestamp_ms（复用现有 video_frame 渲染）。给 evidence_type 标签映射加中文名（"画面描述"/"视频画面描述"）。`npm run type-check && build` 通过；无 CDN。

### 6) 配置/文档
- `.env.example`：新增 `VLM_BASE_URL=`、`VLM_API_KEY=`、`VLM_MODEL=`（占位/注释），并在"云端模型"一节说明：文本 LLM 与视觉 VLM 是**两个独立端点**（你的 DeepSeek 是纯文本，做视觉需另配支持图像的 VLM，如 Qwen-VL/GLM-4V 等）；无 VLM 时保持 `MOCK_MEDIA=true` 走 fixture。
- README：在多模态/云端章节补"视觉理解(VLM)"说明 + 配置示例 + 离线/key 安全提醒；并在"已知限制"里说明这是关键帧描述(非时序动作识别/目标跟踪)。

## 验证（实际执行，最终消息报告；不要发起需要真实 VLM key 的外网单测）
1. `cd backend && ./.venv/bin/pytest -q` 全绿（报告总数与新增；含 registry 8-skill、visual_understand 健康、parse 多-skill、caption 证据相关测试）。
2. AST 3.11 安全：`./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `cd frontend && npm run type-check && npm run build` 通过。
4. `./backend/.venv/bin/python scripts/evaluate_demo.py` 仍 3/3（不回归；若 demo 现在多出 caption 证据，确保 expected/评估不被破坏）。
5. 说明：MOCK 下图片/视频会新增"画面描述"证据；真实模式需配 VLM_*，缺失时该 skill 优雅降级（warning，不崩，OCR/ASR 不受影响）。
不要运行 git commit；不要写入或打印真实 API key。最终消息报告：改动文件、注册表 7→8 的影响面、证据类型与 locator、降级行为、文档位置。
