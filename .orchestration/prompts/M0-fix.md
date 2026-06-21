# 任务：修复 EviTrace M0 审核发现的问题

M0 已实现并提交。Opus 与 Codex 双重审核发现以下问题（已由架构师复现/确认）。请**精确修复**，不要顺手改动无关代码，不做 M1+ 功能。修复后必须实际验证。

## 必修（BLOCKER）

### 1. `CORS_ORIGINS` 作为环境变量会导致后端崩溃（已复现）
现象：`backend/app/config.py` 中 `cors_origins: list[str]`。pydantic-settings 对复杂类型字段会先对环境变量值做 JSON 解码，普通字符串 `http://localhost:5173` 不是合法 JSON，会在 source 层抛 `SettingsError`（早于 `field_validator(mode="before")`），后端无法启动。Docker（compose 注入 `CORS_ORIGINS`）会直接挂掉。
复现命令：`cd backend && CORS_ORIGINS="http://localhost:5173" ./.venv/bin/python -c "from app.config import get_settings; print(get_settings().cors_origins)"` → `SettingsError`。
修复：给该字段加 `NoDecode`，让原始字符串透传到你已写好的 `parse_cors_origins(mode="before")` 验证器。例如：
```python
from typing import Annotated
from pydantic_settings import BaseSettings, SettingsConfigDict, NoDecode
...
cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173"], validation_alias="CORS_ORIGINS")
```
保持 `parse_cors_origins` 同时兼容逗号分隔字符串与列表。修复后用上面的复现命令验证返回 `['http://localhost:5173']` 且不报错。

### 2. 数据路径/`.env` 加载依赖当前工作目录（CWD 敏感）
现象：`DATA_ROOT=./data`、`DATABASE_URL=sqlite:///./data/app.db`、`env_file=(".env","../.env")` 都相对 CWD。本地从 `backend/` 启动落到 `backend/data/`，从仓库根启动落到 `根/data/`，Docker 落到 `/app/data`，三者不一致，排障困难。SPEC §6.3 规定数据应在仓库根的 `data/`。
修复（两部分）：
- **config.py**：计算固定项目根 `PROJECT_ROOT = Path(__file__).resolve().parents[2]`（即仓库根，含 backend/）。新增解析逻辑：对 `data_root` 与 sqlite 的相对路径，若为相对路径则锚定到 `PROJECT_ROOT`，绝对路径原样使用。对外暴露解析后的**绝对** data 目录与 sqlite 绝对 URL（例如属性 `data_root_path: Path` 和 `resolved_database_url: str`）。`env_file` 也用绝对路径锚定到 `PROJECT_ROOT`（如 `PROJECT_ROOT/".env"`），不要再用 `"../.env"` 这种相对上跳。
- **database.py**：改用 config 暴露的绝对 data 路径与绝对 database URL 来 `mkdir` 与 `create_engine`，不要再直接 `Path(settings.data_root)` / `make_url(settings.database_url)` 用相对值。
- **docker-compose.yml**：因容器内代码布局为 `/app/app/...`（`parents[2]` 不等于仓库根），给 backend 增加 `environment:` 覆盖为**绝对**路径，确保数据落在 volume：
  ```yaml
  environment:
    DATA_ROOT: /app/data
    DATABASE_URL: sqlite:////app/data/app.db   # 注意 sqlite 绝对路径是四个斜杠
  ```
  保留 `volumes: ["./data:/app/data"]`。验证：本地从仓库根或从 backend/ 启动，DB 都落在 `仓库根/data/app.db`；容器内落在 `/app/data/app.db`。

## 必修（MAJOR）

### 3. 异常处理器把内部错误细节外泄给客户端
现象：`backend/app/main.py` 的 `SQLAlchemyError` / 通用 `Exception` handler 用 `str(exc)` 作为返回 `message`，会把 SQL、内部细节回传前端（违反 SPEC §12 / NFR-005）。
修复：对 5xx（DATABASE_ERROR / INTERNAL_SERVER_ERROR）对外返回固定中文文案（如「服务器内部错误，请稍后重试」），详细异常只用 logging 写服务端日志（含异常类型与简短堆栈）。`AppError` 与 4xx 校验错误可保留其明确 message。

### 4. `get_settings()` 未捕获 `SettingsError`
现象：只 catch 了 `ValidationError`，而上面第 1 类问题抛的是 `SettingsError`，不会转成清晰的 `RuntimeError`。
修复：同时捕获 `pydantic_settings.SettingsError`（与 `ValidationError`），统一转成清晰的「Invalid application configuration: ...」启动错误。

## 建议修（MINOR）

### 5. 空目录会在 git 中丢失
`demo_data/` 与 `scripts/` 为空目录，提交后不被 git 跟踪。各加一个 `.gitkeep` 占位（内容可为空或一行说明）。

## 验证（必须实际执行并在最终消息报告结果）
1. CORS：运行第 1 条的复现命令，确认现在返回列表且不报错；再额外测 `CORS_ORIGINS="http://a.com, http://b.com"` 能解析成两个元素。
2. 路径：分别从仓库根和从 `backend/` 启动后端（或用 python 打印 `settings.data_root_path` / resolved db url），确认两者一致指向 `仓库根/data`；删除旧的 `backend/data/`（如有）后重启确认 DB 建在 `仓库根/data/app.db`。
3. health：`uvicorn app.main:app` 启动并 `curl http://localhost:8000/api/v1/health` 返回 200。
4. 异常外泄：构造一个会触发 500 的场景或代码审查确认 `str(exc)` 不再出现在响应体。
5. `docker compose config` 仍合法。
6. 前端无需改动；如有改动需 `npm run build` 通过。
不要运行 git commit。最终消息报告每条修复与验证结果。
