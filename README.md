# EviTrace

EviTrace（证链）是一个多模态情报分析工作台。

## Development Startup

首次启动先创建本机配置文件：

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

`.env` 已被 `.gitignore` 忽略，不应提交。`.env.example` 中的 `SECRET_KEY=change-me`
和 `FIRST_ADMIN_PASSWORD=admin123456` 只允许本地演示；开发环境会打印 WARNING 后继续启动。

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload
```

M2 parsing dependency split:

- `requirements.txt` includes deterministic document parsing dependencies: PyMuPDF, python-docx,
  charset-normalizer, and Pillow.
- `requirements-optional.txt` contains heavy local model packages for real OCR/ASR. The default
  `MOCK_AI=true` mode does not require them and will not import PaddleOCR or faster-whisper.
- To run real OCR/ASR/video parsing, install optional packages separately, prepare model weights
  offline, ensure `ffmpeg` is on `PATH`, then set `MOCK_AI=false`:

```bash
cd backend
source .venv/bin/activate
pip install -r requirements-optional.txt
MOCK_AI=false uvicorn app.main:app --reload
```

重置本机首个管理员：

```bash
backend/.venv/bin/python scripts/seed_admin.py
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Docker:

```bash
docker compose up --build
```

## Production Configuration

生产部署必须先复制配置并填入强随机密钥和强管理员口令：

```bash
cp .env.example .env
```

然后设置：

- `ENV=production`
- `SECRET_KEY` 为随机强密钥，例如 `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- `FIRST_ADMIN_PASSWORD` 为非默认强口令

生产环境中，默认或过短的 `SECRET_KEY`、默认管理员口令都会拒绝启动。
