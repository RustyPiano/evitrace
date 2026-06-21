# 代码审核任务：EviTrace M0（项目骨架）

你是独立代码审核员（只读，禁止修改任何文件）。审核刚完成的 M0 实现是否符合 `SPEC.md` 与 `PLAN.md`。

## 审核范围（M0）
对照 `PLAN.md` 第 2 章（M0-01~M0-04）与 `SPEC.md` 第 6、16 章，逐项核对：
1. 目录结构是否与 SPEC 第 16 章一致；`backend/`、`frontend/`、`demo_data/`、`scripts/` 是否齐全。
2. `.env.example` 是否完整包含 PLAN M0-01 的全部环境变量键，且无真实 secret。
3. 后端：`/api/v1/health` 前缀正确？统一错误响应是否实现为 `{"detail":{"code","message"}}`？CORS 是否仅允许 `CORS_ORIGINS`？配置加载用 pydantic-settings？SQLite 数据目录/建表在启动时创建？`DATA_ROOT`/`DATABASE_URL` 相对路径在不同工作目录（本地从 backend/ 启动 vs Docker）下是否会导致数据库落在非预期位置——这是重点检查项。
4. 重型可选依赖（PyMuPDF/python-docx/paddleocr/faster-whisper/Pillow）是否被隔离（未在 app 启动路径 import），保证无这些依赖也能启动。是否引入任何被禁止依赖（LangChain/向量库/图库等）。
5. 前端：Router/Pinia/Axios/Element Plus 是否就位；Axios 是否有 JWT 请求拦截器与 401 处理占位；base URL 是否为 `/api/v1`；Vite 是否代理 `/api` 到后端；是否存在任何 CDN 外链（违反离线 NFR-001）。
6. Docker：Dockerfile 是否合理（后端 python:3.11-slim），compose 是否映射数据卷、前端是否代理后端；是否把模型权重打入镜像。
7. 命名一致性：API 路径、env 变量名、目录名是否与 SPEC/PLAN 完全一致（不得擅自改名）。
8. 是否有为后续里程碑埋下的明显隐患。

## 输出格式（在最终消息中，使用 Markdown）
为每个发现给出：
- **严重级别**：BLOCKER / MAJOR / MINOR / NIT
- **位置**：文件:行 或文件
- **问题**：具体描述
- **建议**：如何修复
最后给一行总评：M0 是否达到“可进入 M1”的标准（PASS / PASS-WITH-FIXES / FAIL）。
只报告真实存在的问题，不要泛泛而谈；没问题的项可不列。
