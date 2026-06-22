# 任务：实现 EviTrace 里程碑 M5（第 2 部分：Docker 生产化与 README）

M0–M5a 已完成（全栈闭环 + 演示数据 + 评估脚本，128 测试通过，evaluation 三案例达标）。本次做 **M5-06（Docker 生产化）与 M5-07（README）**。本机 Docker 与 ffmpeg 均可用。

## 开始前必读
- `PLAN.md` 第 7 章 M5-06/07、第 13 章交付清单。
- `SPEC.md` §6.4 部署、§11 NFR-001 离线/NFR-002 可部署/NFR-003 可恢复、§12 安全、§16 仓库结构。
- 现状：根 `docker-compose.yml`（M0 开发版，backend env_file `.env`，frontend dev server）、`backend/Dockerfile`（python:3.11-slim，CMD uvicorn 无 reload）、`frontend/Dockerfile`（dev server）、`.env.example`、`.env`（本机已生成，gitignored）。先读这些。

## M5-06 Docker 生产化
目标：`docker compose up --build -d` 能**零配置启动**一个可演示的 MOCK 系统（无需手改文件），同时支持用 `.env` 覆盖以生产加固。

要求：
1. **后端镜像**：python:3.11-slim，非 reload 启动（已是）；只 COPY 需要的代码，不打入模型权重；安装 `requirements.txt`（不装 requirements-optional 的重型 ML，MOCK 演示不需要）。容器内 `WORKDIR /app`，数据落 `/app/data`（绝对 DATA_ROOT/DATABASE_URL，已在 compose 处理）。
2. **前端镜像（生产）**：多阶段构建——`node` 阶段 `npm ci && npm run build`，`nginx:alpine` 阶段 serve `dist/`；提供 `frontend/nginx.conf`：SPA history 回退（`try_files $uri /index.html`）、把 `/api` 反代到 `backend:8000`、不加载任何 CDN（离线）。
3. **docker-compose.yml（生产可用且零配置可跑）**：
   - 用 `environment:` 内联设置可演示默认值（`ENV`、`MOCK_AI=true`、`DATA_ROOT=/app/data`、`DATABASE_URL=sqlite:////app/data/app.db`、`FIRST_ADMIN_USERNAME/PASSWORD`、LLM/视频等），使无 `.env` 也能启动；同时支持可选 `.env` 覆盖（若用 env_file，确保缺失 `.env` 不致 compose 失败——可用 `env_file` 的可选语法或仅用 environment + 文档说明）。
   - **SECRET_KEY 强密钥零配置方案**：推荐后端容器 entrypoint：若 `SECRET_KEY` 为空/默认弱值，则在数据卷 `/app/data/.secret_key` 生成并持久化一个随机强密钥后导出（重启保持一致，满足 NFR-003 token 持久；避免演示用 change-me）。这样可让 `ENV=production` 也能安全零配置启动；或退一步用 `ENV=development` 演示 + 文档要求生产改 `.env`。择一并在 README 说明。
   - 数据卷：`./data:/app/data` 持久化（重启保留 DB + 上传 + 报告）。
   - **healthcheck**：backend（curl `/api/v1/health`）、frontend（nginx 根或 /）；frontend `depends_on: backend: condition: service_healthy`。
   - 限制容器写入目录（只数据卷可写，其余只读 if 可行：`read_only` + tmpfs 可选，不要因此破坏运行）；`restart: unless-stopped`。
4. 不把 `.env`/secret 提交；`.dockerignore` 排除 venv/node_modules/data/.git 等以加速构建。

**验证（关键，必须实际执行并报告真实输出）**：
- **Docker/Python 3.11 启动验证（重点，验证此前修过的 3.11 注解隐患）**：构建后端镜像并在容器内执行 `python -c "import app.main"`（或直接看容器 healthy），确认 3.11 下 app 能 import/启动成功。
- `docker compose down -v && docker compose up --build -d && docker compose ps`：服务 healthy。
- 首个管理员可登录（curl `/api/v1/auth/login`）。
- MOCK 闭环：建任务→上传→启动分析→轮询 awaiting_review→下载报告（可用 curl 脚本，经 nginx 的 `/api`）。
- 重启后数据保留：`docker compose restart`（或 down 不带 -v 再 up），DB/上传/报告仍在。
- 若某步因本机资源/时长受限无法完成，明确说明卡在哪、已完成到哪，不要假报成功。

## M5-07 README（根 `README.md`，覆盖 PLAN M5-07 全部 13 项）
1. 项目简介（EviTrace 一句话定义 + 核心价值）；2. 架构图（ASCII 或 mermaid 文本，逻辑架构 + 数据流，无外链图）；3. 功能截图占位（指向 docs/screenshots/ 占位说明）；4. 依赖要求（Python 3.11/Node、ffmpeg 真实模式可选、可选 ML 依赖）；5. 本地模型准备（OpenAI-compatible LLM、OCR/ASR 模型目录 env，离线权重自备，MOCK 默认）；6. Docker 启动；7. 开发启动（后端 venv + uvicorn、前端 npm）；8. 默认管理员配置 + 安全提示（生产改 SECRET_KEY/口令）；9. MOCK_AI 使用（默认 true，真实模式切 false 的前提）；10. 演示流程（结合 demo_data + evaluate_demo.py + 工作台操作 17 步要点）；11. 测试命令（pytest、type-check、build、evaluate）；12. 已知限制（首版不含：实时流、向量库、复杂图谱、人脸识别、多 Agent 自由规划等）；13. 安全边界（离线、权限、文件白名单/路径安全、AI 辅助需人工复核、报告引用约束、不连公网）。
- 保证「新环境按 README 可启动」：命令真实可用、与代码一致（端口、路径、脚本名）。

## 验证（实际执行，最终消息报告每条真实结果）
1. 上述 Docker 验证全部命令与输出（含 3.11 import 验证、compose ps healthy、登录、MOCK 闭环、重启保留）。
2. README 自检：列出的命令与仓库实际一致（venv 路径、脚本路径、端口）。
3. `cd backend && ./.venv/bin/pytest -q` 仍全绿；`cd frontend && npm run build` 仍通过（确认未破坏）。
不要运行 git commit。报告所有产物、真实验证输出、与生产加固相关的决定、遗留项。
