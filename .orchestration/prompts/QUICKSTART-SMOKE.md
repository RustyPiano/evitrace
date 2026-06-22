# 任务：README 30 秒快速上手 + 后端全链路 e2e 冒烟测试

外部评审 P2：README 开头被长篇云模型配置淹没，缺「30 秒快速启动」；且缺端到端冒烟测试。本任务只做这两项（截图由人工另行补，不在此范围）。不要 git commit；既有测试不回归。

## 1) README 重构（突出快速上手，长配置下沉）
- 在 `README.md` **顶部**新增「## 🚀 30 秒快速上手（演示模式）」：
  - 前置：Docker。
  - 步骤：`docker compose up -d --build` → 打开 `http://localhost:8080` → 用演示账号登录（`admin` / `admin123456`）→ 新建任务 → 上传演示样例（指明样例位置，如 `scripts`/演示数据目录中的示例文件或 `data/` 说明）→ 点「开始分析」→ 查看时间线/冲突/证据 → 下载 Markdown 报告。
  - 一句话点明：默认 `MOCK_AI=true` 为**演示 Fixture 模式**，顶部徽章会显示当前运行模式（演示/真实/混合）。
- 把现有**长篇**「云端 LLM / VLM / 本机 OCR-ASR / 全真实」配置段落**移动**到新文件 `docs/DEPLOYMENT.md`（中文部署文档），README 仅保留一句指引 + 链接到该文档。保持内容不丢、仅迁移与精简；占位 key 仍为占位（**不得**出现真实 key）。
- README 保留：项目简介、架构一图/简述、运行模式说明、测试与评估命令（`pytest`、`evaluate_demo.py`、新增 `evaluate_ab.py`）、链接到 `实验报告.md` 与 `docs/DEPLOYMENT.md`。
- 确认 README 内所有端口/账号/路径与实际一致（前端 8080、后端 8000、本地裸跑后端换 8088 的提醒保留在部署文档）。

## 2) 后端全链路 e2e 冒烟测试
- 新增 `backend/tests/integration/test_e2e_smoke.py`，用现有 TestClient + 测试夹具（参照现有 `test_analysis_api.py` 等如何触发并完成一次分析；MOCK 模式下证据/抽取走 fixture）。
- 覆盖完整 happy path，逐步断言：
  1. 登录（演示管理员）拿 token；
  2. 新建任务；
  3. 上传一个文件（用测试夹具里的样例，复用现有上传测试的构造方式）；
  4. 触发分析运行，并驱动其完成到 `awaiting_review`（按现有集成测试的同步驱动方式，如直接调用 orchestrator.execute_run 或测试既有的运行触发路径）；
  5. `GET /tasks/{id}/results` 返回事件/时间线/冲突/报告，断言报告含六个二级标题且含运行模式元数据行；
  6. `GET /tasks/{id}/evidence`（及 `/evidence/index`）返回证据，断言 display_id 形如 `E-0001`；
  7. `GET /tasks/{id}/report/download` 返回 200 + `text/markdown` + 合理文件名头；
  8. `GET /api/v1/system/mode` 返回运行模式（断言为 mock 演示）。
- 断言关键不变量：报告 `citation_check` 的 `invalid_citation_count == 0`；至少 1 条证据；运行状态终态正确。
- 不连真实外网/服务（纯 mock 演示路径）。

## 验证（实际执行，最终消息逐条报告）
1. `cd backend && ./.venv/bin/pytest -q` 全绿（含新增 e2e 冒烟）。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `cd frontend && npm run type-check && npm run build` 通过（若未动前端可注明跳过）。
4. `./backend/.venv/bin/python scripts/evaluate_demo.py` 仍 3/3。
报告：README 改动结构（新增快速上手、迁移到 docs/DEPLOYMENT.md 的内容清单）、e2e 冒烟覆盖的步骤与断言、无真实 key 自证。不要 git commit。
