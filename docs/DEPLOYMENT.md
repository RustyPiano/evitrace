# EviTrace 部署与真实模型配置

本文档承接 README 中下沉的部署细节：云端 LLM/VLM、本机 OCR/ASR、全真实模式、Docker 演示、本地开发启动和安全配置。

## 依赖

- Docker Compose：用于快速演示部署。
- Python 3.11：用于本地后端开发和测试。
- Node.js 20+：用于本地前端开发和构建。
- `ffmpeg`：用于重生成演示 `video.mp4`、真实视频解析和视频关键帧 VLM 描述。
- 可选真实 OCR/ASR 依赖位于 `backend/requirements-optional.txt`；Docker 演示镜像默认不安装这些依赖。

默认 `MOCK_AI=true` 时，不需要 LLM、OCR、ASR 或模型权重。

## Docker 演示启动

```bash
docker compose up --build -d
docker compose ps
```

打开：

- 前端：`http://localhost:8080`
- 后端健康检查：`http://localhost:8000/api/v1/health`
- Nginx 代理健康检查：`http://localhost:8080/api/v1/health`

无 `.env` 时，Docker 演示默认：

- `ENV=development`
- `MOCK_AI=true`
- `DATA_ROOT=/app/data`
- `DATABASE_URL=sqlite:////app/data/app.db`
- `FIRST_ADMIN_USERNAME=admin`
- `FIRST_ADMIN_PASSWORD=admin123456`

数据持久化到 `./data`，包括 SQLite DB、上传文件、派生帧、报告和 Docker entrypoint 自动生成的 secret 文件。

提供的后端 Docker 镜像面向 `MOCK_AI=true` 演示和 HTTP 适配实验。它只安装核心 API 依赖，不安装系统 `ffmpeg`、`backend/requirements-optional.txt`、PaddleOCR、faster-whisper 或模型权重。若 `OCR_BASE_URL` 和 `ASR_BASE_URL` 指向宿主机 HTTP 服务，OCR/ASR 仍可真实调用。真实视频解析仍要求后端运行环境中有 `ffmpeg`。Compose healthcheck 只是 API 存活检查，不代表真实 OCR/ASR/video/LLM/VLM 就绪。

Compose 会自动读取本地 `.env`，可覆盖密码、模型配置、CORS、超时和 `MOCK_AI`。

停止容器：

```bash
docker compose down
```

重置本地 Docker 演示数据：

```bash
docker compose down -v
rm -rf data
mkdir -p data
```

## 本地开发启动

创建本地开发配置：

```bash
cp .env.example .env
python - <<'PY'
from pathlib import Path
import secrets

path = Path(".env")
text = path.read_text()
text = text.replace("SECRET_KEY=change-me", f"SECRET_KEY={secrets.token_urlsafe(48)}")
path.write_text(text)
PY
```

后端：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload
```

从项目根目录重置首个管理员密码：

```bash
backend/.venv/bin/python scripts/seed_admin.py
```

前端：

```bash
cd frontend
npm install
npm run dev
```

开发地址：

- 前端：`http://localhost:5173`
- 后端：`http://localhost:8000`

## 本地模型准备

完全本地真实 AI 模式需要你自行准备本地服务和权重：

- OpenAI 兼容本地 LLM 端点：
  - `LOCAL_LLM_BASE_URL`，例如 `http://host.docker.internal:11434/v1`
  - `LOCAL_LLM_API_KEY`
  - `LOCAL_LLM_MODEL`
- OpenAI 兼容视觉模型端点，用于图片和视频关键帧描述：
  - `VLM_BASE_URL`
  - `VLM_API_KEY`
  - `VLM_MODEL`，例如支持图像输入的 Qwen-VL 或 GLM-4V 模型
- OCR：
  - 优先：`OCR_BASE_URL`，宿主机可用 `http://127.0.0.1:8000`，Docker 中访问宿主机可用 `http://host.docker.internal:8000`
  - 回退：`OCR_MODEL_DIR`，包含本地 PaddleOCR `det/` 和 `rec/` 目录，可选 `cls/`
- ASR：
  - 优先：`ASR_BASE_URL`，宿主机可用 `http://127.0.0.1:8001`，Docker 中访问宿主机可用 `http://host.docker.internal:8001`
  - 回退：`ASR_MODEL_DIR`
  - `ASR_MODEL_SIZE`，默认 `small`
- 媒体 HTTP 超时：
  - `MEDIA_TIMEOUT_SEC`，默认 `180`，用于 OCR/ASR HTTP 推理和健康探测
- 视频解析：
  - 运行环境中必须能调用 `ffmpeg`

文本 LLM 和视觉 VLM 是两个独立端点。DeepSeek 等文本端点可用于抽取和报告，但视觉理解需要接受图片输入的模型。应用不会在运行时下载模型权重。完全本地真实模式下，请先保持 `MOCK_AI=true`，直到本地依赖安装并验证完毕。

真实媒体模式中，`MOCK_MEDIA=false`，或 `MOCK_AI=false` 且 `MOCK_MEDIA` 为空时，OCR/ASR 会优先调用 `OCR_BASE_URL` 或 `ASR_BASE_URL`。如果 URL 为空，后端回退到进程内 PaddleOCR 或 faster-whisper 路径，并要求本地模型目录存在。`MOCK_MEDIA=true` 始终使用确定性媒体 fixture，不调用 HTTP 服务或进程内 OCR/ASR 库。

视觉理解独立于本地 OCR/ASR。`MOCK_VISION` 为空时是自动模式：如果 `VLM_BASE_URL`、`VLM_API_KEY` 和 `VLM_MODEL` 都已设置，图片和视频视觉描述使用真实 VLM；否则使用 caption fixture。这与 `MOCK_MEDIA` 独立，因此本地 OCR/ASR 可继续 mock，而云端 VLM 可真实调用。

## 使用云端 OpenAI 兼容模型（无本地模型时）

如果只有云端 OpenAI 兼容 LLM/VLM，例如 DeepSeek 文本端点加 SiliconFlow 视觉端点，但没有本地 PaddleOCR 或 faster-whisper，可以让文本 LLM 和视觉 VLM 走真实云端，OCR/ASR/视频解析继续走确定性 fixture。

示例 `.env`：

```env
MOCK_AI=false
MOCK_LLM=false
MOCK_MEDIA=true
MOCK_VISION=
LOCAL_LLM_BASE_URL=https://api.deepseek.com/v1
LOCAL_LLM_API_KEY=<put-your-key-in-private-.env-only>
LOCAL_LLM_MODEL=deepseek-chat
VLM_BASE_URL=https://api.siliconflow.cn/v1
VLM_API_KEY=<put-your-vlm-key-in-private-.env-only>
VLM_MODEL=Qwen/Qwen3.6-35B-A3B
```

此模式下，TXT/PDF 仍由本地解析流程真实提取文本证据，云端 LLM 负责要素事件抽取和报告生成；OCR、ASR、视频关键帧/音轨解析使用 fixture；视觉理解由完整的 `VLM_*` 配置自动切到真实 VLM。视频真实视觉会从原视频按 `VIDEO_FRAME_INTERVAL_SEC` 抽帧；如果 ffmpeg 不可用或 VLM 返回 403、超时、余额不足等错误，视觉理解会降级为 warning，不影响 OCR/ASR/文档解析和任务完成。

VLM 与文本 LLM 是两个独立端点。DeepSeek 等文本模型端点不能替代视觉端点；SiliconFlow 等 VLM 端点需要账户有可用余额。API key 只放在已被 gitignore 的本机 `.env` 中，不要写入代码、README 示例以外的文件、测试 fixture、提交记录或终端输出。

## 本机 HTTP OCR/ASR 服务

如果本机已启动 OCR/ASR HTTP 微服务，真实媒体模式会优先调用这些服务，不再在后端进程内加载 PaddleOCR 或 faster-whisper：

```env
MOCK_AI=false
MOCK_MEDIA=false
OCR_BASE_URL=http://127.0.0.1:8000
ASR_BASE_URL=http://127.0.0.1:8001
MEDIA_TIMEOUT_SEC=180
```

Docker 中后端容器访问宿主机服务时使用：

```env
OCR_BASE_URL=http://host.docker.internal:8000
ASR_BASE_URL=http://host.docker.internal:8001
```

适配服务的 `GET /health` 需返回 JSON：`{"status":"ok","warmed":true}` 或 `{"status":"ok","warmed":false}`。后端健康检查以 `status == "ok"` 判定 OCR/ASR HTTP 服务可用，并读取 `warmed` 作为布尔预热状态。

全真实模式示例：

```env
MOCK_AI=false
MOCK_MEDIA=false
OCR_BASE_URL=http://127.0.0.1:8000
ASR_BASE_URL=http://127.0.0.1:8001
LOCAL_LLM_BASE_URL=https://api.deepseek.com/v1
LOCAL_LLM_API_KEY=<put-your-key-in-private-.env-only>
LOCAL_LLM_MODEL=deepseek-chat
VLM_BASE_URL=https://api.siliconflow.cn/v1
VLM_API_KEY=<put-your-vlm-key-in-private-.env-only>
VLM_MODEL=Qwen/Qwen3.6-35B-A3B
```

本机 OCR 服务占用 `8000`，会与后端默认开发端口冲突。本地裸跑后端时请换端口，例如：

```bash
cd backend
uvicorn app.main:app --reload --port 8088
```

旧的进程内 OCR/ASR 回退路径需要安装可选依赖，并留空 `OCR_BASE_URL` 和 `ASR_BASE_URL`：

```bash
cd backend
source .venv/bin/activate
pip install -r requirements-optional.txt
MOCK_AI=false uvicorn app.main:app --reload
```

## 性能与成本（真实模型，大输入务必看）

真实模式下要素抽取按 **30 条证据/批、每批一次 LLM 调用**。证据量越大，调用次数与 token 成本**线性增长**——例如 61 个文档约产生 8121 条证据 → 约 271 次真实 LLM 调用/次分析。注意：

- **成本随证据量线性增长**：大语料一次分析可能消耗上百万 token。`EXTRACT_CONCURRENCY`（默认 4，1..16）只影响**速度**（并发批次数），不降低总 token。
- **省钱三件套**：真实抽取前会自动跳过重复证据和空白/过短证据，并在 run warnings 中透明披露跳过数量；`EXTRACT_BATCH_MAX_ITEMS` / `EXTRACT_BATCH_MAX_CHARS` 可调大以减少批数和重复 system 提示词开销；`EXTRACT_MAX_FILES_CONFIRM` 会在文件数超过阈值时要求工作台二次确认，避免误传大语料直接扣费。
- **相关性预筛（opt-in）**：`EXTRACT_RELEVANCE_TOP_K=0` 默认关闭；大语料/免费档限流时可设为如 `300`，在去重后、抽取前按任务目标用本地 BM25 取最相关 top-K，从根因上减少批数。它会按相关性取舍证据，因此会在 run warnings 中披露原始数、保留数和丢弃数；为降低召回风险，预筛启用时每文档至少保留 `EXTRACT_RELEVANCE_PER_DOC_MIN` 条最高分证据，并对日期/时间/数量等冲突检测高信号文本做有界加权。预筛只影响发给 LLM 的证据集合，全量证据仍入库、证据面板仍可见；批次 hash 基于实际发送内容，续跑会沿用同一预筛结果。需要全量分析时设回 `0`。
- **进度**：抽取阶段进度会从 55% 按已处理批次（成功+失败）推进到 70%（`extracting i/N`，有失败时显示失败数）；失败批不会让进度假死。
- **限流保护**：LLM 429 会触发全局抽取冷却，优先使用上游 Retry-After，否则使用 `EXTRACT_RATE_LIMIT_COOLDOWN_SEC`（默认 5 秒）；连续限流失败达到 `EXTRACT_RATE_LIMIT_CIRCUIT_BREAKER`（默认 8 批，0=关闭）后停止提交剩余批，已完成部分保留，工作台可续跑。
- **批次持久化与续跑**：真实抽取会把每批 sanitized 结果立即写入数据库。单批永久失败不会再炸掉整轮分析；已成功批次会产出部分结果并在 warnings 中披露，工作台会显示批数、失败批数和估算输入 token。点击「继续分析（续跑）」只补未完成批次，复用已完成批次，避免从头重复烧钱；进程中断后也会标记为可续跑。LLM 429/本地模型暂不可用的退避重试、全局冷却、熔断与续跑配合，使大任务可以恢复完成。已知边界：续跑会复用该运行已生成的证据；若上次恰在**解析**阶段中途中断、只写入了部分证据，续跑将基于这部分证据继续——此时请改用「重新分析」走全新一轮。绝大多数中断发生在抽取阶段，已被批级续跑覆盖。
- **可随时止血**：分析进行中在工作台点「停止分析」（`POST /tasks/{id}/runs/cancel`）即协作式取消——未开始的批次立即不再调用 LLM（最多再完成 `EXTRACT_CONCURRENCY` 个在飞批次），不进入冲突/报告阶段。
- **务必避免用 `--reload` 跑真实分析**：`uvicorn --reload` 在任何文件变动时重启进程，会**中断正在运行的长任务**（运行被标记“服务重启导致运行中断”，需重跑）。真实/长任务请用不带 `--reload` 的命令，例如：
  ```bash
  cd backend && MOCK_AI=false ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8088
  ```
- 控制成本的常用做法：先用较小的文档子集试跑；确认效果后再放大；在质量可接受时调大批量，并尽量减少证据量。

去重和调大批量能降低单次分析的重复开销，但成本根本上仍随证据量增长。要真正省钱，应减少输入证据量、先小样试跑，并在发现误跑时及时「停止分析」。

## 生产和安全配置

Docker 演示默认账号是 `admin / admin123456`，仅用于本地演示。

`.env.example` 同样使用 `admin / admin123456` 和 `SECRET_KEY=change-me` 作为本地占位。真实部署必须改掉这些值，并设置 `ENV=production`。在 `ENV=production` 中，后端会拒绝默认管理员密码；弱 `SECRET_KEY` 也会被拒绝，除非 Docker entrypoint 已先生成强 secret 并注入进程环境。

真实部署至少设置：

```env
ENV=production
SECRET_KEY=<strong random value>
FIRST_ADMIN_USERNAME=<admin username>
FIRST_ADMIN_PASSWORD=<strong non-default password>
CORS_ORIGINS=<allowed origins>
```

启用真实 LLM/媒体前，还需设置对应模型端点、模型目录或 HTTP OCR/ASR 服务。使用提供的 Docker 镜像时，建议保持 `MOCK_AI=true`，除非已经把 `OCR_BASE_URL`/`ASR_BASE_URL` 指向宿主机 HTTP 服务，或扩展镜像安装可选 OCR/ASR 依赖并挂载模型目录。真实视频解析还需要加入系统 `ffmpeg`。

如果 `SECRET_KEY` 为空、`change-me` 或短于 32 字节，Docker entrypoint 会在 `./data/.secret_key` 生成强 key 并在重启时复用。显式设置强 `SECRET_KEY` 会优先使用 `.env` 中的值。

不要提交 `.env`、模型权重、上传文件、报告或生成的 secret。
