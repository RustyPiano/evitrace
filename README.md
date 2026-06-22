# EviTrace

EviTrace（证链）是一个离线优先的多模态情报分析工作台，用证据卡片、结构化事件、冲突检测和带引用报告，把 TXT/PDF、图片、音频、视频材料串成可复核的分析链路。

## 🚀 30 秒快速上手（演示模式）

前置：已安装 Docker。

```bash
docker compose up -d --build
```

然后按这条路径完成一次演示：

1. 打开 `http://localhost:8080`。
2. 使用演示账号登录：`admin` / `admin123456`。
3. 新建任务。
4. 上传演示样例：任选 `demo_data/case_01_time_conflict/`、`demo_data/case_02_location_conflict/` 或 `demo_data/case_03_quantity_conflict/` 中的 `brief.txt`、`report.pdf`、`image.png`、`audio.wav`、`video.mp4`。
5. 点「开始分析」。
6. 查看时间线、冲突、证据卡片。
7. 下载 Markdown 报告。

默认 `MOCK_AI=true` 是**演示 Fixture 模式**，不会连接真实云模型或外部 OCR/ASR 服务；页面顶部徽章会显示当前运行模式（演示/真实/混合）。

## 架构

```text
Browser
  |
  |  http://localhost:8080
  v
Nginx frontend container
  |-- serves Vue static assets from /usr/share/nginx/html
  |-- /api/* reverse proxy
  v
FastAPI backend container
  |-- Auth / Task / File / Analysis / Admin APIs
  |-- deterministic orchestrator
  |-- document/image/audio/video parsing skills
  |-- local LLM/VLM clients or MOCK_AI fixtures
  v
SQLite + uploads + derived frames + reports
  ./data  <->  /app/data
```

```text
upload files -> validate type/path -> store originals -> parse to evidence
  -> extract entities/events -> detect time/location/quantity conflicts
  -> generate cited Markdown report -> human review/download
```

默认端口：

- 前端：`http://localhost:8080`
- 后端：`http://localhost:8000`
- 反向代理健康检查：`http://localhost:8080/api/v1/health`

## 运行模式

- **演示 Fixture 模式**：默认 `MOCK_AI=true`。OCR/ASR/视频解析、视觉描述、要素抽取使用确定性 fixture；冲突检测和报告生成仍走真实后端链路，适合课程演示和离线评审。
- **真实模式**：`MOCK_AI=false`，并配置真实 LLM/VLM/OCR/ASR 后使用模型或本机服务。
- **混合模式**：例如云端 LLM/VLM 为真实，OCR/ASR 仍用 fixture。适合没有本机 OCR/ASR 权重时验证报告链路。

云端 LLM / VLM、本机 OCR-ASR、全真实模式、Docker 安全配置、本地裸跑后端端口 `8088` 提醒等部署细节见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

## 演示与评估

如需重新生成演示数据：

```bash
python scripts/build_demo_data.py
```

该命令需要本机 `ffmpeg`，因为会重生成演示 `video.mp4`。

运行三组 fixture 评估：

```bash
./backend/.venv/bin/python scripts/evaluate_demo.py
```

运行 A/B 对比脚手架：

```bash
./backend/.venv/bin/python scripts/evaluate_ab.py
```

默认 mock 模式只运行 B 组证据链流程，并把 A 组列标记为 N/A。若要启用 A 组真实 LLM，对应环境变量配置见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

评估结果文件：

- `evaluation_result.md`
- `scripts/ab_result.md`

## 测试命令

后端：

```bash
cd backend
./.venv/bin/pytest -q
```

注解命名检查：

```bash
cd backend
./.venv/bin/python scripts/check_annotation_names.py
```

前端：

```bash
cd frontend
npm run type-check
npm run build
```

## 文档

- [实验报告.md](实验报告.md)
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- 截图占位目录：[docs/screenshots/](docs/screenshots/)

课程汇报截图建议放入 `docs/screenshots/`，并在文件名中标明页面，例如 `login.png`、`workbench-conflicts.png`、`report-citations.png`。截图由人工补充，不属于自动测试范围。

## 安全边界

- `MOCK_AI=true` 默认离线演示，不需要公网模型访问。
- 前端资源本地打包，不加载 CDN。
- 上传接口检查扩展名、MIME/文件签名、大小、路径安全和任务权限。
- 下载、流式读取、证据查看均需要认证和任务访问权限。
- 管理操作写入审计日志。
- AI 输出只作辅助，报告必须人工复核。
- 报告引用证据 ID；无效引用会被检测并暴露。
- 不要把真实涉密或敏感数据用于测试、演示或课程截图。
