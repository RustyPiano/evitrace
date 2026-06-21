# EviTrace

EviTrace（证链）是一个多模态情报分析工作台。当前仓库处于 M0 阶段，只包含项目骨架、基础运行环境、健康检查和前端占位页面。

## Development Startup

Backend placeholder:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Frontend placeholder:

```bash
cd frontend
npm install
npm run dev
```

Docker placeholder:

```bash
docker compose up --build
```
