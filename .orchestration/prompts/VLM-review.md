# 代码审核：EviTrace 新增"视觉理解(VLM)"特性

你是独立审核员（只读，禁止修改）。审核新增的 VLM 视觉理解特性是否正确、安全、无回归。这是在已交付系统上的增量特性（第 8 个 Skill）。

## 范围
- `backend/app/services/vision_client.py`、`backend/app/skills/visual_understand.py`、`backend/app/skills/video_parse.py`（共享 `extract_video_frames`）、`backend/app/services/parse_service.py`（多 skill/失败隔离）、`backend/app/config.py`（mock 解耦）、`backend/app/services/admin_service.py` + `registry.py`（健康）、`backend/app/utils/health_details.py`、`frontend/src/components/EvidencePanel.vue`、`.env.example`/`README.md`、`backend/tests/**`、`scripts/{build_demo_data,evaluate_demo}.py`、`demo_data/*/.caption.json`。

## 必查项
1. **安全-密钥/泄露**：VLM API key 只来自 env、绝不写入日志/响应/审计/health；视觉失败的 warning 与 health detail 经 `redact_health_detail` 脱敏（不含 key/base_url/绝对路径）。data URL 用本地文件 base64（**不外链、不联网取图**，符合 NFR-001）。业务 skill 不直接 import httpx（只在 VisionClient）。
2. **路径安全**：`visual_understand` 真实视频自抽帧写入任务派生目录是否 resolve+任务目录前缀校验（不能越界）；frame_path 不泄露绝对路径到证据/前端。
3. **mock 解耦逻辑**：`effective_mock_vision` = 显式 MOCK_VISION 优先，否则 VLM 配齐→真实、未配→mock；与 `effective_mock_media`/`effective_mock_llm` 互不影响；向后兼容（仅设 MOCK_AI 时行为不变）。
4. **优雅降级（关键）**：VLM 403/超时/未配置/ffmpeg 缺失 → 非致命 warning，不影响 document_parse/image_ocr/audio_transcribe/video_parse，任务仍可达 awaiting_review；视觉失败不会把 image/video 文件判 failed（图片主解析仍是 OCR）。
5. **共享抽帧**：`extract_video_frames` 被 video_parse 与 visual_understand 共用，无两份逻辑/无重复抽帧浪费；超时（FFMPEG_TIMEOUT_SEC）与错误处理正确。
6. **解析编排**：image→[image_ocr, visual_understand]、video→[video_parse, visual_understand] 的多 skill 运行、停用某 skill 跳过、单 skill 失败隔离是否正确；证据类型/locator（image_caption {kind:image}；video_frame_caption {kind:video_frame,timestamp_ms,frame_path}）符合既有渲染。
7. **注册表 7→8 一致性**：seed/启停/健康/测试/文档中"skill 数量"一致更新；required 仍只有 3 个分析 skill；visual_understand 非必需可停用。
8. **VLM reasoning 模型兼容**：VisionClient 不设过小 max_tokens、读取 message.content（含 list 内容兜底）——避免推理模型把额度耗在 reasoning 导致 content 空。
9. **回归**：是否破坏既有 MOCK 演示（evaluate 3/3）、既有 OCR/ASR/视频 mock 行为、前端构建；是否引入被禁止依赖。
10. 是否有把真实 key 写进 .env.example/README/提交物（必须只用占位）。

## 输出
每个发现：严重级别（BLOCKER/MAJOR/MINOR/NIT）、文件:行、问题、修复建议。最后一行总评 PASS/PASS-WITH-FIXES/FAIL + 合并前必修项。只报告真实问题。
