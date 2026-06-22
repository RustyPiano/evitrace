---
project: EviTrace（证链）多模态情报分析平台
version: 1.0.0
status: Implementation Ready
scope: 课程作业 MVP，可离线部署
primary_language: zh-CN
last_updated: 2026-06-21
---

# EviTrace（证链）多模态情报分析平台——完整开发规格书

## 0. 文档用途与执行约束

本文件是开发的唯一产品与技术规格来源。开发 Agent 应按本文件实现，不应自行扩大范围。

优先级规则：

1. 标记为 **MUST** 的要求必须完成。
2. 标记为 **SHOULD** 的要求在不影响 MUST 的情况下完成。
3. 标记为 **MAY** 的要求仅作为扩展，不进入首版验收。
4. 当实现细节与开发便利性冲突时，优先保证：可运行、可演示、可追溯、可测试。
5. 首版禁止引入向量数据库、知识图谱、复杂多 Agent、自主代码执行、动态插件下载和实时流媒体处理。

平台仅用于对授权、公开或虚构数据进行离线辅助分析，不包含自动目标识别、行动决策、武器控制或自主指挥功能。

---

## 1. 产品概述

### 1.1 产品名称

- 中文名称：证链多模态情报分析平台
- 英文名称：EviTrace

### 1.2 一句话定义

EviTrace 是一个离线运行的多模态资料分析平台，可将文本、PDF、图片、音频和视频转换为可追溯的证据卡片，生成事件时间线、识别资料之间的时间/地点/数量冲突，并输出带证据编号的分析报告。

### 1.3 核心价值

平台不以聊天窗口为核心，而以“任务—资料—证据—事件—冲突—报告”为核心。与大模型直接回答相比，平台重点解决：

- 结论无法追溯到原始资料；
- 音视频分析结果与文本分析结果割裂；
- 大模型容易忽略或抹平资料冲突；
- 同一分析任务缺少固定流程和可重复执行记录；
- 所谓 Skill 只是提示词，缺少明确输入输出和启停管理。

### 1.4 MVP 成功标准

首版通过以下能力判定成功：

1. 用户可在离线环境登录并创建分析任务。
2. 用户可上传 TXT、PDF、DOCX、图片、音频和 MP4 视频。
3. 系统可生成包含来源定位信息的证据卡片。
4. 系统可从证据中提取人物、地点、时间、事件和数量。
5. 系统可生成按时间排序的事件时间线。
6. 系统可识别预先植入的时间、地点和数量冲突。
7. 系统可生成带 `[E-xxxx]` 证据引用的 Markdown 报告。
8. 用户点击证据引用后，可查看原文页码、音频时间段或视频关键帧。
9. 分析员只能查看自己的任务，管理员可查看所有任务。
10. 整个平台可通过 Docker Compose 在单机离线环境启动。

---

## 2. 范围定义

### 2.1 首版包含

- 两类角色：分析员、管理员；
- 任务创建、查看、删除；
- 多文件上传和解析状态展示；
- 文本/PDF/DOCX 解析；
- 图片 OCR；
- 音频本地转写；
- 视频音轨转写、定时抽帧和关键帧 OCR；
- 证据卡片生成；
- 人物、地点、时间、事件、数量提取；
- 时间线生成；
- 时间、地点、数量三类冲突检测；
- 固定工作流式分析 Agent；
- 8 个内置 Skill 及启停管理；
- 带证据引用的报告生成；
- 基础审计日志；
- 三组虚构演示数据及对照验证。

### 2.2 首版不包含

- 实时视频流和实时预警；
- 多部门、多密级、字段级权限；
- 动态安装第三方 Skill；
- Agent 自由规划、自由编写代码或访问互联网；
- 向量数据库、RAG、Neo4j 或复杂实体图谱；
- 人脸识别、身份识别、地理定位模型；
- 复杂来源可信度计算；
- 大规模并发和分布式任务队列；
- 模型训练或微调；
- 自动导出正式涉密文书；
- 自动行动建议或决策执行。

---

## 3. 用户与权限

### 3.1 角色

#### 分析员（analyst）

可以：

- 登录系统；
- 创建任务；
- 查看、编辑、删除自己的任务；
- 上传和删除自己任务中的文件；
- 启动分析；
- 查看证据、时间线、冲突和报告；
- 将冲突标记为“未确认/已确认/已忽略”；
- 下载 Markdown 报告。

不可以：

- 查看其他分析员的任务；
- 新建或停用用户；
- 启停 Skill；
- 查看完整审计日志；
- 修改系统模型配置。

#### 管理员（admin）

可以执行分析员的全部操作，并额外可以：

- 查看所有任务；
- 创建、停用和重置用户密码；
- 查看 Skill 列表并启停 Skill；
- 查看本地模型、OCR、ASR 和 FFmpeg 健康状态；
- 查看审计日志。

### 3.2 权限规则

- 所有业务接口必须验证 JWT。
- 分析员访问任务时必须满足 `task.owner_id == current_user.id`。
- 管理员跳过任务所有权限制。
- 文件、证据、分析结果和报告权限继承所属任务。
- 禁止通过修改 URL ID 访问他人资源。
- 删除任务时同时删除数据库关联记录和任务文件目录。

---

## 4. 核心业务流程

### 4.1 主流程

```text
登录
  → 新建任务
  → 填写任务名称与分析目标
  → 上传多模态资料
  → 点击“开始分析”
  → 系统生成并保存执行计划
  → 按文件类型调用解析 Skill
  → 生成证据卡片
  → 提取实体与事件
  → 生成时间线
  → 检测时间/地点/数量冲突
  → 生成带证据引用的报告
  → 用户审核冲突和报告
  → 标记任务完成并下载报告
```

### 4.2 任务状态

`Task.status` 必须使用以下枚举：

- `draft`：已创建，尚未上传资料；
- `ready`：至少存在一个可分析文件；
- `queued`：已提交分析；
- `parsing`：正在解析文件并生成证据；
- `extracting`：正在提取实体和事件；
- `detecting_conflicts`：正在检测冲突；
- `generating_report`：正在生成报告；
- `awaiting_review`：分析完成，等待人工审核；
- `completed`：用户确认完成；
- `failed`：运行失败。

允许状态转换：

```text
draft → ready
ready → queued
queued → parsing
parsing → extracting
extracting → detecting_conflicts
detecting_conflicts → generating_report
generating_report → awaiting_review
awaiting_review → completed
queued/parsing/extracting/detecting_conflicts/generating_report → failed
failed → queued
awaiting_review → queued（重新分析）
```

---

## 5. 功能需求

### 5.1 认证与用户

#### AUTH-001 登录（MUST）

- 输入：用户名、密码。
- 输出：JWT access token、用户基本信息。
- 错误：用户名或密码错误返回 401，不暴露具体原因。
- 首次启动通过环境变量创建默认管理员。

#### AUTH-002 当前用户（MUST）

- 登录后前端可获取 `id / username / role / is_active`。
- 被停用用户不能登录，也不能继续调用接口。

#### ADMIN-001 用户管理（MUST）

管理员可：

- 查看用户列表；
- 创建分析员或管理员；
- 停用/启用用户；
- 重置密码。

首版不实现注册、邮箱、找回密码和多因素认证。

### 5.2 任务管理

#### TASK-001 创建任务（MUST）

字段：

- `name`：必填，1—100 字符；
- `objective`：必填，1—1000 字符；
- `description`：选填，最多 2000 字符。

创建后状态为 `draft`。

#### TASK-002 任务列表（MUST）

列表展示：

- 名称；
- 创建人；
- 文件数量；
- 当前状态；
- 最近更新时间；
- 最近一次运行错误摘要。

分析员只见自己的任务，管理员可见全部。

#### TASK-003 任务详情（MUST）

详情包含：

- 基本信息；
- 文件列表；
- 最新运行状态；
- 证据统计；
- 实体列表；
- 时间线；
- 冲突列表；
- 报告。

#### TASK-004 删除任务（MUST）

- 运行中任务不可删除；
- 删除前前端二次确认；
- 删除数据库记录及 `data/tasks/{task_id}` 目录；
- 写入审计日志。

### 5.3 文件管理

#### FILE-001 支持格式（MUST）

- 文本：`.txt`、`.md`；
- 文档：`.pdf`、`.docx`；
- 图片：`.jpg`、`.jpeg`、`.png`；
- 音频：`.wav`、`.mp3`、`.m4a`；
- 视频：`.mp4`。

#### FILE-002 上传限制（MUST）

- 单文件默认最大 200 MB，由 `MAX_UPLOAD_MB` 配置；
- 禁止可执行文件和双扩展名绕过；
- 服务端根据扩展名和 MIME 双重验证；
- 文件名保存前必须清洗；
- 实际磁盘文件名使用 UUID，原始文件名单独保存。

#### FILE-003 文件状态（MUST）

- `uploaded`；
- `parsing`；
- `parsed`；
- `warning`；
- `failed`。

一个文件失败不应阻止其他文件继续分析。最终任务结果需显示失败文件和原因。

#### FILE-004 文件查看（MUST）

- 文本/PDF/DOCX：提供提取文本预览；
- 图片：显示原图；
- 音频：浏览器播放器并允许跳转时间；
- 视频：浏览器播放器并允许跳转时间；
- 禁止返回任意磁盘路径，文件必须通过受权限保护的接口访问。

### 5.4 多模态解析与证据卡片

#### EVID-001 文本证据（MUST）

- TXT/MD 按空行切分段落；
- DOCX 按段落切分；
- PDF 按页提取文本，再按最大 1000 字符切块；
- 每条证据必须保留页码、段落号或字符范围；
- 空白块不保存。

#### EVID-002 图片证据（MUST）

- 对图片执行 OCR；
- 每个 OCR 文本块生成证据；
- 保存边界框 `bbox=[x1,y1,x2,y2]`；
- OCR 无文本时生成一条 warning，不伪造描述。

#### EVID-003 音频证据（MUST）

- 使用本地 ASR 生成分段文本；
- 每段保存 `start_ms` 和 `end_ms`；
- 过滤空文本；
- 允许 ASR confidence 为空；
- 前端点击证据后跳转到对应播放时间。

#### EVID-004 视频证据（MUST）

视频解析包含：

1. 提取音轨并调用音频转写；
2. 每隔 `VIDEO_FRAME_INTERVAL_SEC` 秒抽取一帧，默认 10 秒；
3. 对关键帧执行 OCR；
4. 在 `visual_understand` 启用时复用同一批关键帧生成画面描述；
5. 将音轨证据、关键帧 OCR 证据和关键帧画面描述关联至原视频。

首版不做通用视频动作识别、目标跟踪和自动人物身份识别。

#### EVID-005 证据编号（MUST）

- 展示编号格式：`E-0001`、`E-0002`；
- 数据库内部使用 UUID；
- 展示编号在同一任务内唯一且递增；
- 报告只能引用当前任务内存在的证据编号。

#### EVID-006 证据定位器（MUST）

`locator_json` 按模态保存：

```json
// 文本/PDF/DOCX
{
  "kind": "text",
  "page": 3,
  "paragraph": 2,
  "char_start": 0,
  "char_end": 184
}
```

```json
// 图片
{
  "kind": "image",
  "bbox": [120, 80, 460, 190]
}
```

```json
// 图片画面描述
{
  "kind": "image"
}
```

```json
// 音频
{
  "kind": "audio",
  "start_ms": 80000,
  "end_ms": 94000
}
```

```json
// 视频音轨
{
  "kind": "video_audio",
  "start_ms": 80000,
  "end_ms": 94000
}
```

```json
// 视频关键帧
{
  "kind": "video_frame",
  "timestamp_ms": 140000,
  "frame_path": "derived/frames/frame_0000140.jpg",
  "bbox": [120, 80, 460, 190]
}
```

```json
// 视频关键帧画面描述
{
  "kind": "video_frame",
  "timestamp_ms": 140000,
  "frame_path": "derived/frames/frame_0000140.jpg"
}
```

### 5.5 分析 Agent 与执行计划

#### AGENT-001 固定编排（MUST）

首版 Agent 是确定性工作流执行器，不允许自由调用未知工具。固定步骤：

1. `document_parse` / `image_ocr` / `audio_transcribe` / `video_parse` / `visual_understand`；
2. `intelligence_extract`；
3. `conflict_detect`；
4. `report_generate`；
5. `citation_validate`。

#### AGENT-002 执行计划持久化（MUST）

每次运行前保存 `plan_json`，示例：

```json
{
  "run_id": "uuid",
  "steps": [
    {"order": 1, "skill": "document_parse", "file_ids": ["..."]},
    {"order": 2, "skill": "audio_transcribe", "file_ids": ["..."]},
    {"order": 3, "skill": "intelligence_extract"},
    {"order": 4, "skill": "conflict_detect"},
    {"order": 5, "skill": "report_generate"},
    {"order": 6, "skill": "citation_validate"}
  ]
}
```

计划可在前端显示，但首版不允许用户拖拽修改。

#### AGENT-003 失败处理（MUST）

- 单个文件解析失败：记录 warning，继续处理其他文件；
- 核心分析 Skill 被停用：禁止启动任务并明确提示；
- LLM 输出非 JSON：自动重试最多 2 次；
- 重试仍失败：运行状态设为 `failed`，保存原始错误摘要；
- 报告引用验证失败：报告仍保存，但任务保持 `awaiting_review`，显示高亮警告。

### 5.6 实体、事件与时间线

#### ANALYSIS-001 实体类型（MUST）

只提取以下类型：

- `person`：人物；
- `organization`：组织；
- `location`：地点；
- `event`：事件名称；
- `object`：设施、车辆、设备或其他对象；
- `time`：时间；
- `quantity`：数量。

实体结果存入 `analysis_results.entities_json`。

#### ANALYSIS-002 事件结构（MUST）

每个事件必须符合：

```json
{
  "event_id": "EVT-001",
  "event_key": "主体-动作-对象",
  "title": "简短事件标题",
  "subject": "主体或未知",
  "action": "动作",
  "object": "对象或未知",
  "time_text": "原始时间表述",
  "time_normalized": "2026-06-01T14:00:00",
  "location": "地点或未知",
  "quantity": {
    "value": 3,
    "unit": "辆"
  },
  "evidence_ids": ["E-0001", "E-0004"],
  "confidence": 0.82
}
```

规则：

- `event_key` 用于归并同一事件，由模型生成简短规范化文本；
- 无法确定的字段必须写 `null` 或“未知”，不得编造；
- `evidence_ids` 必须至少包含一个有效证据编号；
- `confidence` 范围为 0—1。

#### ANALYSIS-003 时间线（MUST）

- 有 `time_normalized` 的事件按时间升序；
- 只有模糊时间的事件放在“时间未确定”区域；
- 同一时间可以展示多个事件；
- 时间线条目必须显示证据编号。

### 5.7 冲突检测

#### CONFLICT-001 支持类型（MUST）

仅检测：

- `time`：同一事件的时间冲突；
- `location`：同一事件的地点冲突；
- `quantity`：同一事件、同一数量单位的数值冲突。

#### CONFLICT-002 检测逻辑（MUST）

1. 按 `event_key` 对事件分组；
2. 每组至少两条事件记录才执行比较；
3. 时间冲突：两个精确时间差大于 `TIME_CONFLICT_MINUTES`，默认 30 分钟；
4. 地点冲突：两个非空规范化地点字符串不同；
5. 数量冲突：单位相同且数值不同；
6. 每个冲突保留双方事件和证据编号；
7. 冲突由规则生成，不要求再次调用大模型。

冲突结构：

```json
{
  "conflict_id": "C-001",
  "type": "time",
  "event_key": "主体-动作-对象",
  "description": "同一事件存在 14:00 与 16:30 两种时间表述",
  "left": {
    "value": "14:00",
    "event_id": "EVT-001",
    "evidence_ids": ["E-0002"]
  },
  "right": {
    "value": "16:30",
    "event_id": "EVT-003",
    "evidence_ids": ["E-0008"]
  },
  "status": "unreviewed"
}
```

冲突状态：

- `unreviewed`；
- `confirmed`；
- `ignored`。

### 5.8 报告生成

#### REPORT-001 固定结构（MUST）

报告使用 Markdown，结构固定为：

```markdown
# 任务名称

## 一、任务概述
## 二、资料概况
## 三、事件时间线
## 四、主要冲突
## 五、综合分析结论
## 六、未确认事项
```

#### REPORT-002 引用规则（MUST）

- 时间线、冲突和综合结论中的事实性陈述必须带 `[E-xxxx]`；
- 可同时引用多个证据，例如 `[E-0002][E-0008]`；
- 模型只能使用提供的事件、冲突和证据摘要，不允许自行新增事实；
- “未确认事项”应包含资料缺失、冲突未解决和低置信度项。

#### REPORT-003 引用验证（MUST）

`citation_validate` 执行：

1. 提取报告中的 `E-\d{4}`；
2. 验证编号是否属于当前任务；
3. 统计无效引用；
4. 检查“综合分析结论”中每个非空段落是否至少有一个引用；
5. 输出 `citation_coverage` 和 `invalid_citations`。

验收标准：

- `invalid_citations` 必须为 0；
- `citation_coverage` 目标不低于 0.90；
- 低于 0.90 时 UI 显示警告，允许人工查看但不能标记为完成，除非管理员强制确认。

#### REPORT-004 下载（MUST）

- 支持下载 `.md`；
- 文件名：`任务名称_分析报告_YYYYMMDD_HHmm.md`；
- 首版不实现服务器端 PDF/DOCX 导出；
- 用户可使用浏览器打印功能另存为 PDF。

### 5.9 Skill 系统

#### SKILL-001 内置 Skill（MUST）

首版固定包含 8 个 Skill：

| Skill ID | 名称 | 主要输入 | 主要输出 |
|---|---|---|---|
| `document_parse` | 文档解析 | TXT/MD/PDF/DOCX 文件 | 文本证据 |
| `image_ocr` | 图片 OCR | JPG/PNG | OCR 证据 |
| `audio_transcribe` | 音频转写 | WAV/MP3/M4A | 带时间戳证据 |
| `video_parse` | 视频解析 | MP4 | 音轨证据、关键帧 OCR 证据 |
| `visual_understand` | 视觉理解 | JPG/PNG/MP4 | 图片/关键帧画面描述证据 |
| `intelligence_extract` | 要素事件提取 | 证据列表 | 实体、事件、时间线 |
| `conflict_detect` | 冲突检测 | 事件列表 | 冲突列表 |
| `report_generate` | 报告生成与引用验证 | 全部结构化结果 | Markdown 报告、引用检查结果 |

`citation_validate` 可作为 `report_generate` 内部子步骤实现，不必在管理员页面单独展示。

#### SKILL-002 Skill Manifest（MUST）

每个 Skill 在代码中声明：

```python
SkillManifest(
    id="document_parse",
    name="文档解析",
    version="1.0.0",
    description="解析 TXT、MD、PDF 和 DOCX，并生成文本证据",
    enabled_by_default=True,
    required=True,
    input_types=["txt", "md", "pdf", "docx"],
    output_type="evidence_list"
)
```

#### SKILL-003 Skill 接口（MUST）

```python
class Skill(Protocol):
    manifest: SkillManifest

    def run(self, context: SkillContext, payload: Any) -> SkillResult:
        ...
```

要求：

- Skill 只能读写当前任务目录；
- 所有返回必须使用 Pydantic 校验；
- 必须返回 `success / warnings / errors / data / metrics`；
- 禁止动态下载代码；
- 首版 Skill 注册表采用硬编码映射，管理员只能启停，不能上传新 Skill。

#### SKILL-004 启停规则（MUST）

- 管理员可启停非 required Skill；
- `intelligence_extract`、`conflict_detect`、`report_generate` 为 required，前端可显示但不可停用；
- 对应文件类型的解析 Skill 被停用时，该文件标记为 warning，其余流程继续。

---

## 6. 系统架构

### 6.1 技术栈

#### 前端

- Vue 3；
- TypeScript；
- Vite；
- Vue Router；
- Pinia；
- Axios；
- Element Plus；
- ECharts（时间线可用普通列表实现，ECharts 为可选）。

#### 后端

- Python 3.11；
- FastAPI；
- SQLModel 或 SQLAlchemy 2；
- SQLite；
- Pydantic；
- JWT；
- FastAPI BackgroundTasks；
- httpx 或 OpenAI Python 客户端调用本地 OpenAI-compatible 模型接口。

#### 多模态组件

- PDF：PyMuPDF；
- DOCX：python-docx；
- OCR：PaddleOCR；
- ASR：faster-whisper；
- 视频：FFmpeg；
- 图片处理：Pillow 或 OpenCV。

#### 部署

- Docker Compose；
- 前端容器；
- 后端容器；
- 模型服务默认视为同机外部服务，通过环境变量连接；
- 可选 Docker profile 启动 Ollama，但不作为首版必须项。

### 6.2 逻辑架构

```text
Vue 前端
  ├─ 登录与权限
  ├─ 任务列表
  ├─ 文件上传
  ├─ 分析工作台
  └─ 管理页面
       │ REST API / JWT
FastAPI 后端
  ├─ Auth API
  ├─ Task/File API
  ├─ Analysis API
  ├─ Admin API
  ├─ Orchestrator
  ├─ Skill Registry
  ├─ Local LLM Client
  └─ File Storage Service
       ├─ SQLite
       └─ data/tasks/{task_id}/
```

### 6.3 文件目录

```text
data/
  app.db
  tasks/
    {task_id}/
      original/
        {file_uuid}.{ext}
      derived/
        extracted/
        audio/
        frames/
        thumbnails/
      reports/
        latest.md
```

任何 API 不得直接接受用户提供的磁盘路径。

---

## 7. 数据模型

为减少开发量，实体、事件、时间线、冲突和报告集中存储为 JSON/Text，不拆分复杂关系表。

### 7.1 users

| 字段 | 类型 | 约束 |
|---|---|---|
| id | UUID/Text | PK |
| username | Text | unique, not null |
| password_hash | Text | not null |
| role | Text | analyst/admin |
| is_active | Bool | default true |
| created_at | DateTime | not null |
| updated_at | DateTime | not null |

### 7.2 tasks

| 字段 | 类型 | 约束 |
|---|---|---|
| id | UUID/Text | PK |
| name | Text | not null |
| objective | Text | not null |
| description | Text | nullable |
| owner_id | UUID/Text | FK users.id |
| status | Text | enum |
| last_error | Text | nullable |
| created_at | DateTime | not null |
| updated_at | DateTime | not null |

### 7.3 task_files

| 字段 | 类型 | 约束 |
|---|---|---|
| id | UUID/Text | PK |
| task_id | UUID/Text | FK tasks.id |
| original_name | Text | not null |
| stored_name | Text | not null |
| extension | Text | not null |
| mime_type | Text | nullable |
| size_bytes | Integer | not null |
| modality | Text | text/document/image/audio/video |
| status | Text | uploaded/parsing/parsed/warning/failed |
| error_message | Text | nullable |
| created_at | DateTime | not null |

### 7.4 task_runs

| 字段 | 类型 | 约束 |
|---|---|---|
| id | UUID/Text | PK |
| task_id | UUID/Text | FK tasks.id |
| status | Text | queued/running/succeeded/failed |
| plan_json | Text | JSON |
| progress | Integer | 0—100 |
| current_step | Text | nullable |
| warnings_json | Text | JSON array |
| error_message | Text | nullable |
| started_at | DateTime | nullable |
| finished_at | DateTime | nullable |

### 7.5 evidence

| 字段 | 类型 | 约束 |
|---|---|---|
| id | UUID/Text | PK |
| display_id | Text | task 内唯一，如 E-0001 |
| task_id | UUID/Text | FK tasks.id |
| file_id | UUID/Text | FK task_files.id |
| modality | Text | text/image/audio/video |
| evidence_type | Text | paragraph/ocr/asr/video_frame_ocr/image_caption/video_frame_caption |
| content | Text | not null |
| locator_json | Text | JSON |
| confidence | Float | nullable |
| skill_id | Text | not null |
| created_at | DateTime | not null |

唯一索引：`(task_id, display_id)`。

### 7.6 analysis_results

| 字段 | 类型 | 约束 |
|---|---|---|
| id | UUID/Text | PK |
| task_id | UUID/Text | unique, FK tasks.id |
| run_id | UUID/Text | FK task_runs.id |
| entities_json | Text | JSON array |
| events_json | Text | JSON array |
| timeline_json | Text | JSON array |
| conflicts_json | Text | JSON array |
| report_markdown | Text | nullable |
| citation_check_json | Text | JSON object |
| created_at | DateTime | not null |
| updated_at | DateTime | not null |

### 7.7 skill_configs

| 字段 | 类型 | 约束 |
|---|---|---|
| skill_id | Text | PK |
| name | Text | not null |
| version | Text | not null |
| enabled | Bool | not null |
| required | Bool | not null |
| last_status | Text | unknown/healthy/error |
| last_error | Text | nullable |
| updated_at | DateTime | not null |

### 7.8 audit_logs

| 字段 | 类型 | 约束 |
|---|---|---|
| id | UUID/Text | PK |
| user_id | UUID/Text | nullable |
| action | Text | not null |
| resource_type | Text | nullable |
| resource_id | Text | nullable |
| detail_json | Text | JSON |
| created_at | DateTime | not null |

必须记录：登录成功/失败、创建任务、删除任务、上传文件、启动分析、下载报告、创建/停用用户、启停 Skill。

---

## 8. API 规格

统一前缀：`/api/v1`。

统一成功响应建议：

```json
{
  "data": {},
  "message": "ok"
}
```

统一错误响应：

```json
{
  "detail": {
    "code": "TASK_NOT_FOUND",
    "message": "任务不存在或无权访问"
  }
}
```

### 8.1 Auth

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| POST | `/auth/login` | public | 登录 |
| GET | `/auth/me` | authenticated | 当前用户 |

登录请求：

```json
{"username":"analyst1","password":"password"}
```

登录响应：

```json
{
  "access_token": "jwt",
  "token_type": "bearer",
  "user": {"id":"...","username":"analyst1","role":"analyst"}
}
```

### 8.2 Tasks

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| GET | `/tasks` | authenticated | 任务列表 |
| POST | `/tasks` | authenticated | 创建任务 |
| GET | `/tasks/{task_id}` | owner/admin | 任务详情 |
| PATCH | `/tasks/{task_id}` | owner/admin | 修改基本信息或标记完成 |
| DELETE | `/tasks/{task_id}` | owner/admin | 删除任务 |

### 8.3 Files

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| GET | `/tasks/{task_id}/files` | owner/admin | 文件列表 |
| POST | `/tasks/{task_id}/files` | owner/admin | multipart 多文件上传 |
| DELETE | `/files/{file_id}` | owner/admin | 删除未运行文件 |
| GET | `/files/{file_id}/stream` | owner/admin | 原文件流/媒体播放 |
| GET | `/files/{file_id}/preview` | owner/admin | 提取文本或派生预览 |

### 8.4 Analysis

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| POST | `/tasks/{task_id}/runs` | owner/admin | 启动或重新分析 |
| GET | `/tasks/{task_id}/runs/latest` | owner/admin | 最新运行状态 |
| GET | `/tasks/{task_id}/results` | owner/admin | 全部结构化结果 |
| GET | `/tasks/{task_id}/evidence` | owner/admin | 证据分页列表 |
| GET | `/evidence/{evidence_id}` | owner/admin | 单条证据详情 |
| GET | `/evidence/{evidence_id}/source` | owner/admin | 返回定位信息和受保护文件 URL |
| PATCH | `/tasks/{task_id}/conflicts/{conflict_id}` | owner/admin | 修改冲突审核状态 |
| POST | `/tasks/{task_id}/report/regenerate` | owner/admin | 基于现有结构化结果重生成报告 |
| GET | `/tasks/{task_id}/report/download` | owner/admin | 下载 Markdown |

启动分析响应：

```json
{
  "run_id": "uuid",
  "status": "queued"
}
```

最新运行响应：

```json
{
  "run_id": "uuid",
  "status": "running",
  "progress": 55,
  "current_step": "intelligence_extract",
  "warnings": []
}
```

### 8.5 Admin

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| GET | `/admin/users` | admin | 用户列表 |
| POST | `/admin/users` | admin | 创建用户 |
| PATCH | `/admin/users/{id}` | admin | 启停/改角色/重置密码 |
| GET | `/admin/skills` | admin | Skill 列表 |
| PATCH | `/admin/skills/{skill_id}` | admin | 启停 Skill |
| GET | `/admin/health` | admin | 组件健康状态 |
| GET | `/admin/audit-logs` | admin | 审计日志 |

---

## 9. 本地模型接口与提示词约束

### 9.1 模型接口

只实现 OpenAI-compatible Chat Completions 接口。

环境变量：

```env
LOCAL_LLM_BASE_URL=http://host.docker.internal:11434/v1
LOCAL_LLM_API_KEY=local
LOCAL_LLM_MODEL=qwen-local
VLM_BASE_URL=
VLM_API_KEY=
VLM_MODEL=
LLM_TIMEOUT_SEC=180
LLM_MAX_RETRIES=2
```

后端必须封装 `LocalLLMClient`，业务代码不得直接调用 HTTP。
视觉理解必须封装 `VisionClient`，业务 Skill 不得直接调用 HTTP。文本 LLM 与视觉 VLM 是独立端点；真实视觉模式必须配置支持图片输入的 OpenAI-compatible VLM。

```python
class LocalLLMClient:
    def generate_json(self, system_prompt: str, user_prompt: str, schema: type[BaseModel]) -> BaseModel:
        ...

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        ...
```

### 9.2 要素事件提取输入

为了避免上下文过长：

- 单次最多传入约 12,000 中文字符；
- 证据过多时按 20—30 条一批提取，再进行一次合并；
- 每条证据格式为：`[E-0001][来源文件][定位] 内容`；
- 模型必须输出 JSON，不得输出 Markdown。

### 9.3 要素事件提取系统提示词要求

系统提示词必须明确：

- 只使用输入证据；
- 无法确定就输出 null；
- 每个事件必须引用证据编号；
- 不生成行动建议；
- 不合并存在明显冲突的事实；
- 严格符合 JSON schema。

### 9.4 报告生成输入

报告生成只传入：

- 任务目标；
- 文件摘要；
- 事件列表；
- 时间线；
- 冲突列表；
- 必要的证据短文本。

不得把所有原始二进制内容直接交给模型。

### 9.5 MOCK_AI（MUST）

为保证前后端可在无模型环境开发，必须支持：

```env
MOCK_AI=true
```

开启后：

- `intelligence_extract` 返回固定、确定性的示例结构；
- `report_generate` 返回固定模板报告；
- OCR/ASR 可使用测试 fixture 或跳过真实模型；
- 视觉理解读取 `*.caption.json` fixture，缺失时返回确定性画面描述；
- API、UI、权限和工作流仍可完整演示。

生产演示前将其设为 `false`。

---

## 10. UI/UX 规格

### 10.1 总体原则

- 首页不是聊天页；
- 主导航围绕“任务、分析、管理”；
- 每个结论旁边显示证据编号；
- 运行中的步骤和进度必须可见；
- 错误不可只显示“失败”，需显示可理解原因；
- 不使用复杂地图、三维场景和装饰性军事视觉。

### 10.2 路由

```text
/login
/tasks
/tasks/new
/tasks/:id
/admin/users
/admin/skills
/admin/health
/admin/audit
```

### 10.3 登录页

组件：

- 用户名；
- 密码；
- 登录按钮；
- 错误提示。

登录成功按角色进入 `/tasks`。

### 10.4 任务列表页

顶部：

- 页面标题；
- “新建任务”按钮；
- 状态筛选；
- 关键词搜索。

任务卡片/表格字段：

- 任务名；
- 分析目标摘要；
- 创建人（管理员可见）；
- 文件数；
- 状态 Tag；
- 更新时间；
- 查看、删除。

### 10.5 新建任务页

步骤：

1. 填写名称和分析目标；
2. 创建任务；
3. 上传文件；
4. 跳转到工作台。

文件上传需显示格式、大小、成功/失败状态。

### 10.6 分析工作台

推荐布局：

```text
┌──────────────────────────────────────────────────────────────┐
│ 任务标题  状态  进度  [开始分析/重新分析] [标记完成] [下载]  │
├───────────────┬──────────────────────────┬───────────────────┤
│ 文件与步骤栏  │ 主分析区域               │ 证据检查器        │
│               │ Tab: 概览/时间线/冲突/报告│                   │
│ 文件列表      │                          │ 原文件名          │
│ 解析状态      │                          │ 页码/时间/关键帧  │
│ 执行计划      │                          │ 原始证据内容      │
└───────────────┴──────────────────────────┴───────────────────┘
```

#### 左栏

- 文件列表及解析状态；
- 执行步骤：解析、提取、冲突、报告；
- 当前步骤高亮；
- warning 数量。

#### 主区域 Tab

**概览**：

- 文件数；
- 证据数；
- 实体数；
- 事件数；
- 冲突数；
- 引用覆盖率。

**时间线**：

- 时间；
- 事件标题；
- 地点；
- 证据编号按钮；
- 置信度。

**冲突**：

- 类型；
- 描述；
- 左右两组值；
- 双方证据；
- 审核状态下拉框。

**报告**：

- Markdown 渲染；
- 引用可点击；
- 无效引用红色；
- 引用覆盖率低于 90% 显示警告；
- “重新生成报告”和“下载 Markdown”。

#### 右栏证据检查器

点击证据后：

- 显示证据编号；
- 原文件名；
- 内容；
- 页码/段落/时间/帧信息；
- 图片或关键帧缩略图；
- 音视频播放器跳转到时间点。

### 10.7 管理页面

**用户管理**：用户表、新建、启停、重置密码。

**Skill 管理**：名称、版本、是否必需、启用状态、最近健康状态。

**健康检查**：

- 数据库；
- 本地模型接口；
- FFmpeg；
- OCR；
- ASR；
- 磁盘可写性。

---

## 11. 非功能需求

### NFR-001 离线运行（MUST）

- 核心运行过程不得依赖公网；
- 默认 `MOCK_AI=true` / `MOCK_MEDIA=true` 不得调用公网；真实 VLM/LLM 调用只能由部署人员显式配置端点和 key；
- 前端不得加载 CDN；
- 字体、图标和 JS 依赖均随应用打包；
- 模型和 OCR/ASR 权重由部署人员提前准备。

### NFR-002 可部署性（MUST）

- 提供 `docker-compose.yml`；
- 提供 `.env.example`；
- 提供初始化管理员脚本；
- 提供 `README.md` 启动、模型配置和演示步骤；
- `docker compose up --build` 后可访问前端。

### NFR-003 可恢复性（MUST）

- 运行失败后保留已生成证据；
- 用户可重新启动分析；
- 重新分析前删除旧分析结果，但保留原文件；
- 后端重启后运行中任务标记为 failed，并提示重新执行。

### NFR-004 性能（SHOULD）

- 任务列表接口在 100 个任务内响应小于 1 秒；
- 证据列表必须分页，默认 50 条；
- 前端轮询运行状态间隔 2 秒；
- 单机只允许一个分析任务运行，其余排队或返回 409。

### NFR-005 日志（MUST）

- 控制台日志包含时间、级别、模块、task_id、run_id；
- 不记录用户密码、JWT 和完整原始敏感文本；
- 错误日志保留异常类型和简短堆栈。

### NFR-006 可测试性（MUST）

- 解析器、冲突规则、引用验证器必须有单元测试；
- API 权限必须有集成测试；
- MOCK_AI 模式下可完成端到端测试。

---

## 12. 安全要求

- 密码必须哈希存储；
- JWT Secret 来自环境变量；
- CORS 只允许配置的前端地址；
- 上传文件名和路径必须防目录穿越；
- 拒绝 `.exe`、`.sh`、`.bat`、`.js` 等可执行或脚本文件；
- 后端不得执行上传文件中的宏或代码；
- DOCX 只读取文本；
- PDF 只解析文本/页面，不执行嵌入内容；
- 所有文件下载/播放接口必须经过任务权限校验；
- 管理员操作写入审计日志；
- 系统默认不得自动连接互联网或调用云模型；只有显式关闭 MOCK 并配置模型端点时才允许调用；
- 报告必须显示“AI 辅助生成，需人工复核”。

---

## 13. 错误码

建议至少实现：

| 错误码 | HTTP | 含义 |
|---|---:|---|
| `INVALID_CREDENTIALS` | 401 | 登录失败 |
| `INACTIVE_USER` | 403 | 用户已停用 |
| `FORBIDDEN` | 403 | 无权限 |
| `TASK_NOT_FOUND` | 404 | 任务不存在或无权访问 |
| `FILE_TYPE_NOT_SUPPORTED` | 400 | 文件格式不支持 |
| `FILE_TOO_LARGE` | 413 | 文件过大 |
| `TASK_NOT_READY` | 409 | 无可分析文件 |
| `TASK_ALREADY_RUNNING` | 409 | 已有任务运行 |
| `REQUIRED_SKILL_UNAVAILABLE` | 503 | 必需 Skill 不可用 |
| `LOCAL_MODEL_UNAVAILABLE` | 503 | 本地模型不可用 |
| `ANALYSIS_FAILED` | 500 | 分析失败 |
| `INVALID_MODEL_OUTPUT` | 500 | 模型输出无法校验 |

---

## 14. 验证与测试数据

### 14.1 演示数据

在 `demo_data/` 下准备 3 组虚构案例，每组至少包含：

- 2 份短文本或 PDF；
- 1 张含地点或数量文字的图片；
- 1 段约 20—40 秒音频；
- 1 段约 20—40 秒 MP4；
- 1 个时间冲突；
- 1 个地点或数量冲突。

不得使用真实涉密材料。

### 14.2 标注文件

每组案例提供 `expected.json`：

```json
{
  "expected_entities": [],
  "expected_events": [],
  "expected_conflicts": [
    {"type": "time", "left": "14:00", "right": "16:30"}
  ],
  "required_evidence_modalities": ["text", "image", "audio", "video"]
}
```

### 14.3 对照方式

- 基线组：将解析后的全部文本一次性发送给同一模型，直接生成报告；
- 平台组：证据卡片 → 事件提取 → 冲突检测 → 报告 → 引用验证。

记录：

- 报告中有效引用数；
- 引用覆盖率；
- 人工植入冲突发现数；
- 无效引用数；
- 是否可跳转到原始位置。

---

## 15. 验收标准

### 15.1 功能验收

- [ ] 管理员和分析员均可登录；
- [ ] 分析员无法访问另一分析员任务；
- [ ] 管理员可查看所有任务；
- [ ] 可上传每一种支持格式；
- [ ] 不支持格式被拒绝；
- [ ] PDF 证据显示页码；
- [ ] 图片证据显示 OCR 区域；
- [ ] 音频证据可跳转时间；
- [ ] 视频证据可显示关键帧并跳转时间；
- [ ] 运行状态和进度可见；
- [ ] 结果包含实体、时间线和冲突；
- [ ] 三类冲突至少各有一个自动化测试；
- [ ] 报告中的证据编号均有效；
- [ ] 点击报告引用可打开证据检查器；
- [ ] 可下载 Markdown；
- [ ] 管理员可启停非必需 Skill；
- [ ] Docker Compose 可启动系统。

### 15.2 质量验收

- [ ] `citation_coverage >= 0.90`；
- [ ] `invalid_citations == 0`；
- [ ] 3 组演示案例中的人工植入冲突至少发现 80%；
- [ ] 任何模型输出均经过 Pydantic 或 JSON Schema 校验；
- [ ] 单文件失败不会导致整个任务无结果；
- [ ] 所有关键操作有审计日志；
- [ ] MOCK_AI 模式端到端测试通过。

---

## 16. 建议仓库结构

```text
evitrace/
  README.md
  SPEC.md
  PLAN.md
  .env.example
  docker-compose.yml
  backend/
    Dockerfile
    requirements.txt
    app/
      main.py
      config.py
      database.py
      models.py
      schemas.py
      dependencies.py
      api/
        auth.py
        tasks.py
        files.py
        analysis.py
        admin.py
      services/
        auth_service.py
        storage_service.py
        audit_service.py
        llm_client.py
        orchestrator.py
        result_service.py
      skills/
        base.py
        registry.py
        document_parse.py
        image_ocr.py
        audio_transcribe.py
        video_parse.py
        intelligence_extract.py
        conflict_detect.py
        report_generate.py
      utils/
        file_types.py
        json_repair.py
        citations.py
        time_normalize.py
    tests/
      unit/
      integration/
      fixtures/
  frontend/
    Dockerfile
    package.json
    src/
      main.ts
      router/
      stores/
      api/
      views/
        LoginView.vue
        TaskListView.vue
        NewTaskView.vue
        TaskWorkbenchView.vue
        AdminUsersView.vue
        AdminSkillsView.vue
        AdminHealthView.vue
      components/
        FileList.vue
        RunProgress.vue
        EvidencePanel.vue
        TimelinePanel.vue
        ConflictPanel.vue
        ReportPanel.vue
  demo_data/
    case_01/
    case_02/
    case_03/
  scripts/
    seed_admin.py
    build_demo_data.py
    evaluate_demo.py
```

---

## 17. 实现决策摘要

开发 Agent 不需要再次选择以下事项：

- 使用固定工作流，不做自由规划多 Agent；
- 使用 SQLite，不引入 PostgreSQL；
- 使用本地文件系统，不引入 MinIO；
- 使用 JSON 字段保存实体、事件、时间线和冲突；
- 使用 OpenAI-compatible 本地模型接口；
- 使用 FastAPI BackgroundTasks，不引入 Redis/Celery；
- 使用规则检测三类冲突；
- 报告格式为 Markdown；
- 前端为 Vue 3；
- 首版只支持单机单分析任务；
- 必须提供 MOCK_AI 模式。
