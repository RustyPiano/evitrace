# EviTrace

EviTrace（证链）是一个离线优先的多模态情报分析工作台，用证据卡片、结构化事件、冲突检测和带引用报告，把 TXT/PDF、图片、音频、视频材料串成可复核的分析链路。

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
  |-- local LLM client or MOCK_AI fixtures
  v
SQLite + uploads + derived frames + reports
  ./data  <->  /app/data
```

Data flow:

```text
upload files -> validate type/path -> store originals -> parse to evidence
  -> extract entities/events -> detect time/location/quantity conflicts
  -> generate cited Markdown report -> human review/download
```

## Screenshots

截图占位目录：`docs/screenshots/`。课程汇报截图建议放入该目录，并在文件名中标明页面，例如 `login.png`、`workbench-conflicts.png`、`report-citations.png`。

## Requirements

- Docker Compose for the zero-config demo deployment.
- Python 3.11 for local backend development and tests.
- Node.js 20+ for local frontend development and builds.
- ffmpeg is required to (re)generate demo `video.mp4` files and for real video parsing with `MOCK_AI=false`.
- Optional real OCR/ASR dependencies are in `backend/requirements-optional.txt`; they are not installed in the Docker demo image.

Default `MOCK_AI=true` mode runs without LLM, OCR, ASR, or model weights.

## Local Model Preparation

Real AI mode is offline-first and expects you to prepare local services and weights yourself:

- OpenAI-compatible local LLM endpoint:
  - `LOCAL_LLM_BASE_URL`, for example `http://host.docker.internal:11434/v1`
  - `LOCAL_LLM_API_KEY`
  - `LOCAL_LLM_MODEL`
- OCR model directory:
  - `OCR_MODEL_DIR` containing local PaddleOCR `det/` and `rec/` directories, optional `cls/`
- ASR model directory:
  - `ASR_MODEL_DIR`
  - `ASR_MODEL_SIZE`, default `small`
- Video parsing:
  - `ffmpeg` must be available in the runtime environment

The application does not download model weights at runtime. Keep `MOCK_AI=true` until those local dependencies are installed and verified.

## 使用云端 OpenAI 兼容模型（无本地模型时）

如果只有云端 OpenAI 兼容 LLM（例如 DeepSeek），但没有本地 PaddleOCR、faster-whisper 或视频解析依赖，可以让 LLM 走真实云端、媒体解析继续走确定性 fixture。示例 `.env`：

```env
MOCK_AI=false
MOCK_LLM=false
MOCK_MEDIA=true
LOCAL_LLM_BASE_URL=https://api.deepseek.com/v1
LOCAL_LLM_API_KEY=<put-your-key-in-private-.env-only>
LOCAL_LLM_MODEL=deepseek-chat
```

此模式下，TXT/PDF 仍由本地解析流程真实提取文本证据，云端 LLM 负责要素事件抽取和报告生成；OCR、ASR、视频关键帧/音轨解析使用 fixture，适合没有本地媒体模型的端到端演示与测试。API key 只放在已被 gitignore 的本机 `.env` 中，不要写入代码、README 示例以外的文件或提交记录。

## Docker Startup

Zero-config MOCK demo:

```bash
docker compose up --build -d
docker compose ps
```

Open:

- Frontend: `http://localhost:8080`
- Backend health: `http://localhost:8000/api/v1/health`
- Through nginx: `http://localhost:8080/api/v1/health`

Without a `.env`, Docker defaults to:

- `ENV=production`
- `MOCK_AI=true`
- `DATA_ROOT=/app/data`
- `DATABASE_URL=sqlite:////app/data/app.db`
- `FIRST_ADMIN_USERNAME=admin`
- `FIRST_ADMIN_PASSWORD=EviTrace-Demo-Admin-2026!`

Data persists in `./data`, including SQLite DB, uploads, derived frames, reports, and the auto-generated Docker secret file.

The provided backend Docker image is for `MOCK_AI=true` demos. It installs core API dependencies only; it does not install system `ffmpeg`, `backend/requirements-optional.txt`, PaddleOCR, faster-whisper, or model weights. The compose healthcheck is an API liveness check and does not prove real OCR/ASR/video/LLM readiness.

Compose automatically reads a local `.env` if present. That lets you override passwords, model settings, CORS, timeouts, and `MOCK_AI`. For a hardened Docker demo using the provided image, set at least:

```env
ENV=production
SECRET_KEY=<strong random value>
FIRST_ADMIN_USERNAME=<admin username>
FIRST_ADMIN_PASSWORD=<strong non-default password>
```

Keep `MOCK_AI=true` with the provided image. Set `MOCK_AI=false` in Docker only after extending the backend image with system `ffmpeg` and `backend/requirements-optional.txt`, mounting prepared `OCR_MODEL_DIR` and `ASR_MODEL_DIR` paths, and pointing `LOCAL_LLM_*` to an OpenAI-compatible local model service.

If `SECRET_KEY` is empty, `change-me`, or shorter than 32 bytes, the backend Docker entrypoint generates a strong key at `./data/.secret_key` and reuses it on restart. Setting a strong `SECRET_KEY` in `.env` takes precedence.

Stop containers:

```bash
docker compose down
```

Reset all local Docker demo data:

```bash
docker compose down -v
rm -rf data
mkdir -p data
```

## Development Startup

Create local development config:

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

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload
```

Reset the first admin password from the project root:

```bash
backend/.venv/bin/python scripts/seed_admin.py
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Development URLs:

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`

For local real OCR/ASR mode:

```bash
cd backend
source .venv/bin/activate
pip install -r requirements-optional.txt
MOCK_AI=false uvicorn app.main:app --reload
```

Ensure `ffmpeg` is installed on the host and available on `PATH` before running local real video parsing.

## Admin And Security

Docker demo with no `.env` uses `admin / EviTrace-Demo-Admin-2026!`.

The development `.env.example` uses `admin / admin123456` and `SECRET_KEY=change-me` only as local placeholders. In `ENV=production`, the backend rejects the default admin password and weak secrets unless Docker entrypoint generation replaces the weak secret before app startup.

Before any real deployment, change:

- `SECRET_KEY`
- `FIRST_ADMIN_USERNAME`
- `FIRST_ADMIN_PASSWORD`
- `CORS_ORIGINS`
- local model endpoint and model directory settings

Do not commit `.env`, model weights, uploads, reports, or generated secrets.

## MOCK_AI Mode

`MOCK_AI=true` is the default demo path. It keeps the whole API and UI workflow active while using deterministic fixtures:

- OCR/ASR/video parsing reads sidecar fixture JSON when available.
- Entity and event extraction reads `mock/extraction.json` when available.
- Conflict detection and report generation run locally and deterministically.
- No public network or cloud model is required.

Set `MOCK_AI=false` only after installing optional OCR/ASR packages, preparing offline model directories, making ffmpeg available, and pointing `LOCAL_LLM_*` to an OpenAI-compatible local model service.

## Demo Flow

Generate demo data if the directory is missing or stale:

```bash
python scripts/build_demo_data.py
```

This command requires `ffmpeg` because it regenerates the demo `video.mp4` files.

Run the automated three-case evaluation:

```bash
cd backend
source .venv/bin/activate
cd ..
python scripts/evaluate_demo.py
```

The script writes `evaluation_result.md`.

Workbench demo checklist:

1. Log in as admin.
2. Open user and Skill administration.
3. Create or switch to an analyst.
4. Create task `多源事件研判演示`.
5. Upload TXT/PDF, image, audio, and video files from one `demo_data/case_*` directory.
6. Start analysis.
7. Watch the execution plan and progress.
8. Open the timeline tab.
9. Click event evidence and inspect PDF page, media timestamp, or frame locator.
10. Open conflicts and review time, location, and quantity conflicts.
11. Mark one conflict as confirmed.
12. Open the report and click an `[E-xxxx]` citation.
13. Check citation coverage and invalid citation count.
14. Download the Markdown report.
15. Show that another analyst cannot access the task.
16. Show Docker and offline model configuration.
17. Show the three-case evaluation table.

## Test Commands

Backend tests:

```bash
cd backend
./.venv/bin/pytest -q
```

Frontend type-check and production build:

```bash
cd frontend
npm run type-check
npm run build
```

Docker production demo:

```bash
docker compose down -v
docker compose up --build -d
docker compose ps
```

Python 3.11 import check inside the backend image:

```bash
docker compose exec backend python -c "import app.main"
```

Evaluation:

```bash
python scripts/evaluate_demo.py
```

## Known Limits

This MVP intentionally does not include real-time stream ingestion, vector database retrieval, complex knowledge graphs, face recognition, geospatial map layers, multi-Agent free planning, distributed job queues, or fine-grained tenant isolation. Real OCR/ASR/LLM quality depends on locally supplied models and is outside the Docker MOCK demo image.

## Security Boundary

- Offline by default: the app does not need public network access in `MOCK_AI=true`.
- Frontend assets are bundled locally; no CDN is loaded.
- Uploads enforce extension, MIME/signature checks, size limits, path safety, and task permission checks.
- Download and streaming APIs require authentication and task access.
- Admin operations are audit logged.
- AI output is assistive only and must be reviewed by a human.
- Reports must cite evidence IDs; invalid citations are tracked and surfaced.
- Do not use real classified or sensitive data for tests, demos, or coursework screenshots.
