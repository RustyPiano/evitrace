---
project: EviTrace（证链）多模态情报分析平台
version: 1.0.0
status: Execution Plan
scope: 5-day MVP
primary_language: zh-CN
last_updated: 2026-06-21
---

# EviTrace（证链）开发执行计划

## 0. 开发 Agent 执行规则

本计划用于指导编码 Agent 按依赖顺序完成项目。

必须遵守：

1. 开始任何任务前先阅读 `SPEC.md` 对应章节。
2. 只实现当前里程碑的 MUST 项，不提前加入向量库、图数据库、复杂 Agent、云模型或实时视频。
3. 每完成一个任务，运行其验收命令并更新本文件复选框。
4. API、数据结构、状态枚举和目录结构不得随意改名。
5. 所有模型返回必须先校验，再写数据库。
6. 所有资源访问必须先检查任务所有权或管理员角色。
7. 在真实模型接通前使用 `MOCK_AI=true` 打通端到端流程。
8. 任何外部组件不可用时必须返回可理解错误，不能让进程无响应。
9. 优先完成可演示闭环，再处理视觉细节和扩展功能。
10. 每个里程碑完成后必须有可运行状态，不能长期停留在无法启动的中间状态。

完成定义：

- 代码已实现；
- 单元或集成测试已通过；
- 错误路径已处理；
- README 已记录必要命令；
- 前端能展示对应状态；
- 无未解决的阻断性异常。

---

## 1. 里程碑总览

| 里程碑 | 目标 | 可演示结果 |
|---|---|---|
| M0 | 项目骨架与运行环境 | 前后端和数据库可启动 |
| M1 | 登录、权限、任务和文件 | 用户可登录、建任务、上传文件 |
| M2 | 多模态解析与证据 | 可查看带定位的证据卡片 |
| M3 | Agent 工作流与分析结果 | 可生成事件、时间线、冲突和报告 |
| M4 | 完整工作台与管理页 | 可完成整条用户操作流程 |
| M5 | 测试、演示数据和部署 | Docker 部署与对照验证可复现 |

推荐执行节奏：

- 第 1 天：M0 + M1；
- 第 2 天：M2；
- 第 3 天：M3；
- 第 4 天：M4；
- 第 5 天：M5、修复和演示。

---

## 2. M0：项目骨架与运行环境

### M0-01 创建仓库结构

**依赖**：无。

**操作**：

- 创建 `backend/`、`frontend/`、`demo_data/`、`scripts/`；
- 放入 `SPEC.md` 和 `PLAN.md`；
- 创建 `.gitignore`；
- 创建根目录 `README.md`；
- 创建 `.env.example`。

**必须存在的环境变量**：

```env
APP_NAME=EviTrace
ENV=development
SECRET_KEY=change-me
ACCESS_TOKEN_EXPIRE_HOURS=8
DATABASE_URL=sqlite:///./data/app.db
DATA_ROOT=./data
MAX_UPLOAD_MB=200
CORS_ORIGINS=http://localhost:5173
LOCAL_LLM_BASE_URL=http://host.docker.internal:11434/v1
LOCAL_LLM_API_KEY=local
LOCAL_LLM_MODEL=qwen-local
LLM_TIMEOUT_SEC=180
LLM_MAX_RETRIES=2
MOCK_AI=true
VIDEO_FRAME_INTERVAL_SEC=10
TIME_CONFLICT_MINUTES=30
FIRST_ADMIN_USERNAME=admin
FIRST_ADMIN_PASSWORD=admin123456
```

**验收**：

- [x] 根目录结构与 SPEC 一致；
- [x] `.env.example` 不包含真实 Secret；
- [x] README 至少有开发启动占位说明。

### M0-02 后端骨架

**文件**：

- `backend/app/main.py`
- `backend/app/config.py`
- `backend/app/database.py`
- `backend/app/models.py`
- `backend/app/schemas.py`
- `backend/requirements.txt`

**实现**：

- FastAPI app；
- `/api/v1/health`；
- 配置加载；
- SQLite 数据目录自动创建；
- 启动时建表；
- CORS；
- 统一错误处理框架。

**验收命令**：

```bash
cd backend
uvicorn app.main:app --reload
curl http://localhost:8000/api/v1/health
```

**验收**：

- [x] 返回 HTTP 200；
- [x] `data/app.db` 自动创建；
- [x] Swagger 可打开；
- [x] 配置错误时启动信息明确。

### M0-03 前端骨架

**实现**：

- Vue 3 + TypeScript + Vite；
- Vue Router；
- Pinia；
- Axios；
- Element Plus；
- 基础 Layout；
- `/login` 与 `/tasks` 空页面；
- Axios base URL 与 JWT interceptor。

**验收**：

```bash
cd frontend
npm install
npm run dev
```

- [x] 页面可打开；
- [x] 路由切换正常；
- [x] 无 TypeScript 编译错误。

### M0-04 Docker 开发环境

**实现**：

- `backend/Dockerfile`；
- `frontend/Dockerfile`；
- 根目录 `docker-compose.yml`；
- 映射数据目录；
- 前端代理 `/api` 到后端。

**验收**：

```bash
docker compose up --build
```

- [x] 前端可访问；
- [x] 前端能调用后端 health；
- [x] 重启容器后数据库和上传文件保留。

---

## 3. M1：登录、权限、任务和文件

### M1-01 数据模型

**依赖**：M0-02。

**实现表**：

- users；
- tasks；
- task_files；
- task_runs；
- evidence；
- analysis_results；
- skill_configs；
- audit_logs。

**要求**：

- UUID 使用字符串；
- 时间统一为 UTC 存储；
- JSON 字段先序列化为 Text；
- 创建必要索引；
- 启动时根据 Skill registry 初始化 `skill_configs`。

**测试**：

- [x] 建表成功；
- [x] user.username 唯一；
- [x] evidence 的 `(task_id, display_id)` 唯一；
- [x] 级联删除逻辑通过服务层实现并测试。

### M1-02 认证服务

**文件建议**：

- `app/services/auth_service.py`
- `app/api/auth.py`
- `app/dependencies.py`

**实现**：

- 密码哈希；
- JWT 创建和验证；
- `get_current_user`；
- `require_admin`；
- 启动时 seed 默认管理员；
- `POST /auth/login`；
- `GET /auth/me`。

**测试用例**：

- [x] 正确密码登录成功；
- [x] 错误密码 401；
- [x] 停用用户 403；
- [x] 无 token 401；
- [x] 非管理员访问 admin API 403。

### M1-03 任务 API

**实现**：

- 任务 CRUD；
- owner/admin 权限依赖；
- 状态字段；
- 运行中禁止删除；
- 审计日志。

**测试用例**：

- [x] 分析员只看到自己的任务；
- [x] 分析员访问他人任务返回 404 或 403，保持一致；
- [x] 管理员看到全部任务；
- [x] 创建任务字段校验正确；
- [x] 删除任务会清理文件目录。

### M1-04 文件存储服务

**文件建议**：`app/services/storage_service.py`。

**实现**：

- 文件格式白名单；
- MIME/扩展名检查；
- 大小限制；
- UUID 文件名；
- 任务目录创建；
- 路径安全检查；
- 删除文件；
- 安全流式返回文件。

**测试用例**：

- [x] TXT/PDF/JPG/WAV/MP4 上传成功；
- [x] EXE/SH 被拒绝；
- [x] 超大文件 413；
- [x] `../../x` 文件名不能穿越；
- [x] 无权用户不能下载文件。

### M1-05 文件与任务前端

**实现**：

- LoginView；
- 用户状态 store；
- 路由守卫；
- TaskListView；
- NewTaskView；
- 文件上传组件；
- 状态 Tag；
- 删除确认。

**验收流程**：

1. 管理员登录；
2. 创建分析员；
3. 分析员登录；
4. 创建任务；
5. 上传多种文件；
6. 刷新后任务和文件仍存在。

- [x] 全流程成功；
- [x] 401 自动退出登录；
- [x] 上传错误可见。

---

## 4. M2：多模态解析与证据卡片

### M2-01 Skill 基础框架

**文件**：

- `app/skills/base.py`
- `app/skills/registry.py`

**实现数据类**：

```python
class SkillManifest(BaseModel):
    id: str
    name: str
    version: str
    description: str
    enabled_by_default: bool
    required: bool
    input_types: list[str]
    output_type: str

class SkillContext(BaseModel):
    task_id: str
    run_id: str
    data_root: str

class SkillResult(BaseModel):
    success: bool
    warnings: list[str] = []
    errors: list[str] = []
    data: dict | list | None = None
    metrics: dict = {}
```

**实现**：

- 固定注册表；
- 从数据库读取 enabled；
- required Skill 不允许停用；
- Skill 健康检查接口。

**测试**：

- [x] 注册表包含 8 个 Skill；
- [x] 停用非必需 Skill 后不执行；
- [x] required Skill 停用请求被拒绝。

### M2-02 证据服务

**文件建议**：`app/services/result_service.py`。

**实现**：

- 任务内生成下一个 `E-xxxx`；
- 批量写入证据；
- 删除某文件旧证据；
- 分页查询；
- locator 序列化/反序列化；
- 证据 source 响应。

**测试**：

- [x] display_id 从 E-0001 开始递增；
- [x] 并发不作为首版目标，但单任务不会重复；
- [x] 证据只能被任务 owner/admin 查询。

### M2-03 文档解析 Skill

**实现顺序**：

1. TXT/MD；
2. DOCX；
3. PDF。

**具体规则**：

- TXT 使用 `charset-normalizer` 检测编码；
- DOCX 读取非空段落；
- PDF 用 PyMuPDF 按页提取；
- 每段/块最多 1000 字符；
- locator 包含页码/段落/字符范围；
- 扫描 PDF 若无文本，先标记 warning，首版可不做整页 OCR。

**fixture**：准备 1 个 TXT、1 个 DOCX、1 个两页 PDF。

**测试**：

- [x] 证据内容正确；
- [x] PDF 页码正确；
- [x] 空段落不保存；
- [x] 损坏文件标记 failed，不抛出未捕获异常。

### M2-04 图片 OCR Skill

**实现**：

- 封装 PaddleOCR；
- 模型在进程内延迟加载并缓存；
- 每个文本框一条证据；
- 保存 bbox；
- 无文本返回 warning；
- MOCK_AI 下读取 fixture OCR JSON。

**测试**：

- [x] 含文字图片至少生成一条证据；
- [x] locator 有 bbox；
- [x] 无文字图片不会伪造内容。

### M2-05 音频转写 Skill

**实现**：

- 封装 faster-whisper；
- 延迟加载模型；
- 分段输出文本和时间；
- 空分段过滤；
- 支持 WAV/MP3/M4A；
- MOCK_AI 下读取 fixture transcript JSON。

**测试**：

- [x] 证据 start_ms/end_ms 正确；
- [x] 点击时间定位所需数据完整；
- [x] 无语音文件返回 warning。

### M2-06 视频解析 Skill

**实现**：

- 检查 FFmpeg；
- 提取 WAV 音轨；
- 调用音频转写逻辑，但证据 modality 为 video；
- 每 10 秒抽帧；
- 对帧调用 OCR；
- 派生文件写入 `derived/audio`、`derived/frames`；
- 证据 locator 指向原视频时间和 frame_path；
- 不实现动作识别。

**测试**：

- [x] 短视频能生成音轨或帧证据；
- [x] frame_path 只能位于任务目录；
- [x] 无音轨视频仍可抽帧；
- [x] FFmpeg 缺失时错误明确。

### M2-07 文件解析编排

**实现**：

- 根据文件 modality 选择 Skill；
- 更新 file.status；
- 每文件解析前删除旧证据；
- 单文件失败继续；
- 汇总 warnings；
- 任务状态更新为 parsing；
- 进度按文件数更新。

**验收**：

- [x] 混合上传 5 类文件可运行；
- [x] 至少一种文件故障时其他证据仍生成；
- [x] 文件状态和 warning 在前端可见。

### M2-08 证据 UI

**实现**：

- EvidencePanel；
- 证据分页；
- 文本内容；
- PDF 页码；
- 图片 bbox 基础显示，可先只显示原图与 bbox 数值；
- 音视频播放器跳转；
- 视频关键帧缩略图。

**验收**：

- [x] 点击证据后右栏变化；
- [x] 音视频从相应秒数播放；
- [x] 无权文件 URL 不可直接访问。

---

## 5. M3：Agent、要素提取、冲突与报告

### M3-01 本地模型客户端

**文件**：`app/services/llm_client.py`。

**实现**：

- OpenAI-compatible base URL；
- 超时；
- 最多 2 次重试；
- JSON 提取和轻量修复；
- Pydantic 校验；
- 记录 token/耗时指标（若接口返回）；
- MOCK_AI；
- 健康检查。

**禁止**：

- 在业务 Skill 中直接调用 `requests/httpx`；
- 将未验证 JSON 写库；
- 把完整二进制文件交给模型。

**测试**：

- [x] MOCK_AI 输出稳定；
- [x] 非 JSON 输出重试；
- [x] 最终失败返回 `INVALID_MODEL_OUTPUT`；
- [x] 模型不可达返回 503。

### M3-02 要素与事件 Schema

**实现 Pydantic 模型**：

- Entity；
- Quantity；
- Event；
- ExtractionResult；
- TimelineItem；
- Conflict；
- CitationCheck。

**要求**：

- confidence 限制 0—1；
- evidence_ids 至少一个；
- event_id 服务端统一重编号；
- 引用不存在时拒绝保存该事件或过滤并告警。

### M3-03 Intelligence Extract Skill

**实现**：

- 按证据批次构造 prompt；
- 每批提取实体和事件；
- 合并重复实体；
- 事件按 `event_key + 证据来源` 保留；
- 生成时间线；
- 模糊时间单独分组；
- 保存 `entities_json/events_json/timeline_json`。

**简化策略**：

- 不做高级实体消歧；
- 仅进行字符串 trim、大小写统一、全半角统一；
- 时间解析失败时保留 `time_text`，`time_normalized=null`。

**测试**：

- [x] 每个事件有有效证据；
- [x] 时间线排序正确；
- [x] 模型返回未知字段不会导致服务崩溃；
- [x] 证据为空时明确失败。

### M3-04 冲突检测 Skill

**实现为纯 Python 规则**：

```text
group events by event_key
for each pair:
  compare normalized time
  compare normalized location
  compare quantity when unit equal
```

**时间规则**：

- 两个 ISO 时间差 > 30 分钟；
- 只有日期时，日期不同即冲突；
- 无法解析的不比较。

**地点规则**：

- trim、移除常见空格和标点后比较；
- 字符串完全相同视为一致；
- 不实现地名别名库。

**数量规则**：

- 单位相同且数值不同；
- 单位不同不自动判冲突，只记 warning。

**测试至少包含**：

- [x] 14:00 与 16:30 -> 时间冲突；
- [x] 14:00 与 14:10 -> 非冲突；
- [x] 地点 A 与地点 B -> 地点冲突；
- [x] 3 辆与 5 辆 -> 数量冲突；
- [x] 3 辆与 3 人 -> 不比较；
- [x] 不同 event_key 不比较。

### M3-05 报告生成与引用验证

**实现**：

1. 使用固定 Markdown 结构；
2. 调用模型生成报告正文；
3. 对引用进行正则提取；
4. 验证引用属于当前任务；
5. 计算综合结论段落覆盖率；
6. 保存报告和 citation_check；
7. 写 `data/tasks/{id}/reports/latest.md`。

**模型失败 fallback（MUST）**：

即使模型生成失败，也使用纯模板生成最小报告：

- 任务概述；
- 文件统计；
- 时间线列表；
- 冲突列表；
- “综合结论生成失败，请人工复核”。

这样任务仍可进入 `awaiting_review`，但显示 warning。

**测试**：

- [x] 无效引用能被发现；
- [x] 引用覆盖率计算正确；
- [x] 报告文件可下载；
- [x] 无模型时 fallback 可用。

### M3-06 Orchestrator

**文件**：`app/services/orchestrator.py`。

**职责**：

- 校验任务可运行；
- 生成 plan_json；
- 创建 task_run；
- 保证单机一次只运行一个任务；
- 依次执行解析、提取、冲突、报告；
- 每步更新 Task.status、progress、current_step；
- 捕获错误；
- 汇总 warning；
- 成功后状态 `awaiting_review`。

**建议进度**：

- queued 0；
- parsing 10—45；
- extracting 55—70；
- detecting_conflicts 80；
- generating_report 90；
- awaiting_review 100。

**重跑逻辑**：

- 保留原文件；
- 删除旧 evidence；
- 清空旧 analysis_result；
- 新建 run；
- 不覆盖历史 task_run。

**启动恢复**：

- 应用启动时将数据库中 running 状态 run 标记 failed；
- task.status 设为 failed；
- last_error 写“服务重启导致运行中断，请重新执行”。

**测试**：

- [x] 完整 MOCK_AI 流程完成；
- [x] 进度单调增加；
- [x] 二次启动返回 409；
- [x] 失败后可重跑；
- [x] 运行日志含 task_id/run_id。

### M3-07 Analysis API

**实现**：

- 启动分析；
- 轮询最新运行；
- 获取结果；
- 证据详情；
- 冲突状态修改；
- 报告重生成；
- 报告下载。

**测试**：

- [x] 权限覆盖全部接口；
- [x] 任务无文件时返回 409；
- [x] 任务运行中再次运行返回 409；
- [x] 非 owner 不能查看结果。

---

## 6. M4：完整前端工作台与管理页

### M4-01 工作台框架

**实现**：

- 顶部任务信息；
- 开始/重跑；
- 标记完成；
- 下载报告；
- 左中右三栏；
- 结果轮询；
- 运行中禁用冲突编辑和删除文件。

**验收**：

- [x] 刷新页面后继续显示当前任务状态；
- [x] 运行完成自动刷新结果；
- [x] 失败状态显示 last_error 和重试按钮。

### M4-02 概览与时间线

**实现**：

- 统计卡片；
- 简单纵向时间线；
- 模糊时间独立区域；
- 点击证据编号打开 EvidencePanel。

**验收**：

- [x] 时间顺序正确；
- [x] 多证据按钮均可点击；
- [x] 空结果有空状态，不报错。

### M4-03 冲突面板

**实现**：

- 按时间/地点/数量筛选；
- 左右值并排；
- 证据编号；
- 状态下拉；
- 状态修改调用 PATCH。

**验收**：

- [x] 修改状态后刷新仍保留；
- [x] 冲突数统计同步更新；
- [x] 无冲突时显示“未发现规则范围内冲突”。

### M4-04 报告面板

**实现**：

- Markdown 渲染；
- `[E-xxxx]` 转为可点击按钮/链接；
- 无效引用红色；
- 覆盖率警告；
- 重生成；
- 下载。

**安全**：

- Markdown 渲染禁用原始 HTML或进行严格 sanitize；
- 不执行脚本。

**验收**：

- [x] 引用点击正确；
- [x] 下载文件内容一致；
- [x] 报告无内容时显示原因。

### M4-05 用户管理

**实现**：

- 用户表；
- 新建用户对话框；
- 启停；
- 重置密码；
- 角色选择。

**限制**：

- 管理员不能停用当前登录账号；
- 至少保留一个启用管理员。

**测试**：

- [x] 分析员无菜单且访问路由被拦截；
- [x] 后端仍进行二次权限校验。

### M4-06 Skill 与健康页面

**Skill 页面**：

- 名称、版本、required、enabled、最近状态；
- required 开关禁用；
- 非 required 可启停。

**健康页面**：

- DB；
- 磁盘；
- LLM；
- FFmpeg；
- OCR；
- ASR。

**验收**：

- [x] 组件不可用显示错误原因；
- [x] 页面不暴露 Secret 或完整路径。

### M4-07 UI 收尾

**必须处理**：

- 加载状态；
- 空状态；
- 错误状态；
- 按钮防重复提交；
- 状态颜色一致；
- 响应式最低支持 1280×720；
- 不追求移动端适配。

---

## 7. M5：测试、演示数据、部署与验收

### M5-01 后端单元测试

**最低覆盖模块**：

- 文件类型与路径安全；
- 证据编号；
- 时间冲突；
- 地点冲突；
- 数量冲突；
- 引用验证；
- 权限依赖；
- MOCK_AI 输出校验。

**命令**：

```bash
cd backend
pytest -q
```

- [x] 所有测试通过；
- [x] 核心纯函数测试无数据库依赖。

### M5-02 API 集成测试

测试完整流程：

1. seed 管理员；
2. 管理员创建两个分析员；
3. 分析员 A 建任务并上传 fixture；
4. 分析员 B 无法访问；
5. A 启动分析；
6. 轮询至完成；
7. 获取证据、结果和报告；
8. 修改冲突状态；
9. 下载报告；
10. 管理员可访问。

- [x] 全流程自动化通过。

### M5-03 前端构建检查

```bash
cd frontend
npm run type-check
npm run build
```

- [x] 无 TypeScript 错误；
- [x] 生产构建成功；
- [x] 无硬编码开发地址。

### M5-04 演示数据

创建：

```text
demo_data/
  case_01_time_conflict/
  case_02_location_conflict/
  case_03_quantity_conflict/
```

每组：

- `brief.txt`；
- `report.pdf` 或 `report.docx`；
- `image.png`；
- `audio.wav`；
- `video.mp4`；
- `expected.json`；
- `README.md` 说明植入冲突。

为了减少制作成本，音频和视频可使用自录虚构内容；视频可使用静态背景加字幕和旁白生成。

- [x] 三组均能完成分析；
- [x] 每组至少发现预期冲突；
- [x] 四种模态都有证据。

### M5-05 对照评估脚本

**文件**：`scripts/evaluate_demo.py`。

**输出 JSON/Markdown 表格**：

- 案例名；
- 预期冲突数；
- 发现冲突数；
- 冲突召回率；
- 报告引用数；
- 有效引用数；
- 引用覆盖率；
- 无效引用数。

可选增加 baseline，但不应阻塞主系统。

- [x] 脚本可对 3 组案例输出汇总；
- [x] 结果保存为 `evaluation_result.md`。

### M5-06 Docker 生产化

**实现**：

- 后端非 reload 启动；
- 前端构建后由 Nginx 或静态服务器提供；
- 数据目录 volume；
- 健康检查；
- `.env` 配置；
- 限制容器写入目录；
- 不把模型权重打入镜像。

**验收**：

```bash
docker compose down -v
docker compose up --build -d
docker compose ps
```

- [x] 服务 healthy；
- [x] 首次管理员可登录；
- [x] 上传、分析、报告闭环通过；
- [x] 重启后数据保留。

### M5-07 README

README 必须包含：

1. 项目简介；
2. 架构图；
3. 功能截图占位；
4. 依赖要求；
5. 本地模型准备；
6. Docker 启动；
7. 开发启动；
8. 默认管理员配置；
9. MOCK_AI 使用；
10. 演示流程；
11. 测试命令；
12. 已知限制；
13. 安全边界。

- [x] 新环境按 README 可启动。

---

## 8. 关键实现伪代码

### 8.1 Orchestrator

```python
async def run_task(task_id: str, user_id: str) -> None:
    lock = acquire_single_run_lock()
    if not lock:
        raise TaskAlreadyRunning()

    run = create_run(task_id, build_plan(task_id))
    try:
        set_task_status(task_id, "parsing")
        parse_summary = parse_all_files(task_id, run.id)

        evidence = list_evidence(task_id)
        if not evidence:
            raise AnalysisFailed("没有生成可分析证据")

        set_task_status(task_id, "extracting")
        extraction = intelligence_extract.run(...)
        validate_evidence_references(extraction, evidence)

        set_task_status(task_id, "detecting_conflicts")
        conflicts = conflict_detect.run(extraction.events)

        set_task_status(task_id, "generating_report")
        report = report_generate.run(...)
        citation_check = validate_citations(report, evidence)

        save_analysis_result(...)
        finish_run_success(run.id, warnings=parse_summary.warnings)
        set_task_status(task_id, "awaiting_review")
    except Exception as exc:
        finish_run_failed(run.id, safe_error(exc))
        set_task_failed(task_id, safe_error(exc))
    finally:
        release_lock(lock)
```

### 8.2 证据编号

```python
def next_display_id(task_id: str) -> str:
    current_max = query_max_numeric_suffix(task_id)
    return f"E-{current_max + 1:04d}"
```

### 8.3 引用验证

```python
CITATION_RE = re.compile(r"E-\d{4}")

def validate_report(report: str, valid_ids: set[str]) -> CitationCheck:
    used = set(CITATION_RE.findall(report))
    invalid = sorted(used - valid_ids)
    conclusion_paragraphs = extract_section_paragraphs(report, "五、综合分析结论")
    factual = [p for p in conclusion_paragraphs if p.strip()]
    cited = [p for p in factual if CITATION_RE.search(p)]
    coverage = len(cited) / len(factual) if factual else 1.0
    return CitationCheck(...)
```

---

## 9. 测试矩阵

| 场景 | 预期结果 |
|---|---|
| 错误密码登录 | 401 |
| 停用用户登录 | 403 |
| 分析员读取他人任务 | 拒绝 |
| 上传 `.exe` | 400 |
| 上传超大文件 | 413 |
| PDF 有两页 | 证据保留正确页码 |
| 图片无文字 | warning，无虚构证据 |
| 音频无语音 | warning，不中断其他文件 |
| 视频无音轨 | 仍可抽帧 OCR |
| 模型返回代码块包裹 JSON | 清理后校验 |
| 模型连续输出非法 JSON | 任务 failed，错误可见 |
| 同事件 14:00/16:30 | 时间冲突 |
| 同事件地点 A/B | 地点冲突 |
| 同事件 3 辆/5 辆 | 数量冲突 |
| 报告引用不存在 E-9999 | invalid_citations 包含该项 |
| 运行中再次点击分析 | 409/按钮禁用 |
| 容器重启中断任务 | 标记 failed，可重跑 |
| 删除任务 | DB 和磁盘目录清理 |

---

## 10. 风险与降级策略

### 10.1 OCR 安装或模型下载困难

降级：

- 保留 `image_ocr` 接口；
- MOCK_AI 使用 fixture；
- 真实模式健康检查标记 unavailable；
- 图片文件仍可上传和展示，但解析状态 warning。

### 10.2 ASR 运行过慢

降级：

- 默认使用较小模型；
- 限制演示音频/视频在 40 秒内；
- 只在显式启动分析时加载；
- MOCK_AI 支持完整演示。

### 10.3 本地 LLM JSON 不稳定

降级顺序：

1. system prompt 强制 JSON；
2. 使用 schema 示例；
3. 清理 Markdown code fence；
4. 轻量 JSON repair；
5. 重试 2 次；
6. 报告使用模板 fallback；
7. 提取步骤仍失败则任务 failed，不伪造分析结果。

### 10.4 视频处理复杂

严格限制首版为：

- 音轨转写；
- 固定间隔抽帧；
- 帧 OCR。

不增加镜头检测、目标检测和视觉问答。

### 10.5 开发进度不足

保留优先级：

1. 登录和任务；
2. 文本/PDF；
3. 证据卡片；
4. 要素提取；
5. 冲突；
6. 报告引用；
7. 音频；
8. 视频；
9. 图片 bbox 可视化；
10. 健康页美化。

不得为了视觉效果牺牲证据引用和冲突检测。

---

## 11. 禁止事项

开发 Agent 不得：

- 引入 LangChain、AutoGen、CrewAI 等仅为展示而增加复杂度；
- 增加自由聊天主页；
- 增加互联网搜索；
- 增加自动代码执行；
- 增加向量数据库和 RAG；
- 增加复杂图谱；
- 将真实 API Key 写入仓库；
- 关闭后端权限检查，仅依赖前端；
- 在报告中生成无证据编号的确定性事实；
- 让单个文件异常导致整个进程崩溃；
- 为追求“智能”而跳过结构化 Schema 校验；
- 使用真实涉密数据作为测试材料。

---

## 12. 最终验收演示脚本

按以下顺序演示，不临场改变：

1. 管理员登录；
2. 展示用户与 Skill 管理；
3. 创建或切换到分析员；
4. 新建“多源事件研判演示”任务；
5. 上传 TXT/PDF、图片、音频、视频；
6. 点击开始分析；
7. 展示执行计划和进度；
8. 打开时间线；
9. 点击事件证据，展示 PDF 页码或音视频时间点；
10. 打开冲突页面，展示时间/地点/数量冲突；
11. 将一个冲突标记为“已确认”；
12. 打开报告，点击 `[E-xxxx]`；
13. 展示引用覆盖率和无效引用数；
14. 下载 Markdown 报告；
15. 展示分析员无法访问另一用户任务；
16. 展示 Docker 和离线模型配置；
17. 展示 3 组测试案例的评估表。

---

## 13. 最终交付清单

- [x] `SPEC.md`；
- [x] `PLAN.md`；
- [x] 完整源代码；
- [x] `.env.example`；
- [x] `docker-compose.yml`；
- [x] 后端测试；
- [x] 前端生产构建；
- [x] 3 组演示数据；
- [x] `evaluation_result.md`；
- [x] README；
- [ ] 系统截图（占位，演示时人工补充）；
- [x] 课程汇报中的架构、流程、创新点和验证结果。

完成上述清单即视为 MVP 交付完成。
