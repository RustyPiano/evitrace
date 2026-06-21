# 任务：修复 EviTrace M1 三方审核（Opus×2 + Codex）发现的问题

M1 已实现并提交。以下问题由三个独立审核员发现并交叉确认。请**精确修复**，不顺手改无关代码。修复后必须实际运行 `pytest` 与前端构建验证。

## BLOCKER

### 1. 默认 `SECRET_KEY=change-me` 实际生效，可伪造 admin JWT；默认管理员口令
现状：仓库无 `.env`，运行时 `secret_key="change-me"`（公开值），任何人可伪造 `role=admin` 的 JWT，认证形同虚设；`docker-compose.yml` 还直接加载 `.env.example`。违反 SPEC §12。
修复：
- 在 `config.py` 增加启动校验：当 `env == "production"` 时，若 `secret_key` 属于弱/默认值集合（`{"change-me",""}`）或长度过短，**拒绝启动**并给出清晰错误；同样当 `first_admin_password` 仍为默认 `admin123456` 时在生产拒绝。`env == "development"` 时仅打印醒目 WARNING，允许运行（保证本地演示）。
- 生成本机运行用的 `.env`（**确保被 .gitignore 忽略**，不要提交）：从 `.env.example` 复制，并把 `SECRET_KEY` 替换为随机强密钥（如 `secrets.token_urlsafe(48)`），`ENV=development`。这样本地实例不再用 change-me。
- 新增 `scripts/seed_admin.py`（SPEC §16 要求该脚本存在）：可幂等创建/重置首个管理员（读取 settings，调用现有 auth/seed 逻辑）。
- README 增补：生产部署必须 `cp .env.example .env` 并填入随机 `SECRET_KEY` 与强管理员口令；说明 dev 默认值仅供本地演示。
- `.gitignore` 确认包含 `.env`。

### 2. 缺少管理员用户管理 API —— M1 验收流程「管理员创建分析员」无法走通（ADMIN-001 是 MUST）
现状：后端只有 `/admin/health`。SPEC §5.1 ADMIN-001 与 §8.5、PLAN M1-05 验收流程都需要管理员能创建分析员。
修复（**只做后端 API + 测试；前端完整管理页仍留到 M4-05**）：
实现以下接口（均 `require_admin`，写审计，路径与 SPEC §8.5 一致）：
- `GET /api/v1/admin/users`：用户列表（id/username/role/is_active/created_at）。
- `POST /api/v1/admin/users`：创建用户（username 唯一、role∈{analyst,admin}、设置初始密码并哈希）。
- `PATCH /api/v1/admin/users/{id}`：启停（is_active）、改角色、重置密码。
安全约束（防自锁）：管理员不能停用/降级当前登录账号；系统必须至少保留一个启用的管理员（最后一个 active admin 不可停用/降级）。违反返回明确 4xx。
审计：`user_created`/`user_updated`（含启停/重置，detail 不含明文新密码）。
测试：管理员创建分析员成功→该分析员可登录；非管理员访问 `/admin/users` 403；不能停用最后一个 admin；不能停用自己。

## MAJOR

### 3. MIME 双校验可被绕过（Content-Type 缺失/`application/octet-stream` 时退化为纯扩展名）
位置：`backend/app/utils/file_types.py`（约 79 行）。
修复：不要用基于扩展名的 `guess_type` 替代真实上传 MIME。对受支持类型做**服务端文件头/magic 校验**：至少校验 PDF(`%PDF-`)、PNG(`\x89PNG`)、JPEG(`\xff\xd8\xff`)、WAV(`RIFF....WAVE`)、MP4(`ftyp` box)、DOCX(zip `PK\x03\x04` 且包含 `[Content_Types].xml`/`word/`)。txt/md 允许文本。当类型无法确认时**拒绝**（400 FILE_TYPE_NOT_SUPPORTED），而不是放行。注意需要读取文件头字节但仍保持上传的流式/大小限制不被破坏（可先读前若干 KB 校验，再继续流式落盘）。补充对应测试：把可执行内容改名为 `.pdf` 并用 octet-stream 上传应被拒。

### 4. `PATCH /tasks/{id}` 标记完成缺状态机校验（允许非法转换）
位置：`task_service.update_task`。SPEC §4.2 仅允许 `awaiting_review → completed`。
修复：置 `completed` 前校验 `task.status == awaiting_review`，否则返回 409（建议错误码 `INVALID_STATUS_TRANSITION` 或复用合适码）。补测试。

### 5. `DELETE /files/{file_id}` 仅禁运行中，允许删除已分析任务的文件 → 悬挂 evidence
SPEC §8.3 语义是「删除未运行文件」。
修复：仅当任务处于未分析状态（建议 `draft`/`ready`）时允许删除文件；处于 `awaiting_review/completed` 等已产出结果的状态时拒绝（明确错误），引导用户走重新分析。删除文件时同时清理该文件关联的 evidence（防御性级联）。补集成测试（含拒绝场景）。

### 6. 删除任务时删除了历史审计日志（应 append-only）
位置：`task_service.delete_task`（约 175 行）删除了该任务的 `audit_logs`。
修复：**不要**在删除任务时删除任何 `audit_logs`（审计只追加）。保留 `task_created/file_uploaded/task_deleted` 等历史。继续删除 DB 业务关联（Evidence/TaskRun/AnalysisResult/TaskFile）与磁盘目录。

### 7. 级联删除测试缺口（PLAN M1-01/M1-03 勾选项目前假性通过）
修复：新增集成测试：构造含 evidence + task_run + analysis_result 的任务，删除后断言三表对应记录清零、磁盘目录消失；构造 `parsing` 状态任务删除返回 409 `TASK_ALREADY_RUNNING`。

## MINOR（一并修）

### 8. 畸形 `Range` 头触发 500
位置：`storage_service`（约 200 行）。`int()` 解析失败应返回结构化 416/400，而非 500。捕获并处理。

### 9. 依赖未固定版本
`backend/requirements.txt` 与 `requirements-dev.txt` 给所有依赖加上明确版本约束（bcrypt、PyJWT、fastapi、uvicorn、pydantic、pydantic-settings、SQLAlchemy、python-multipart、pytest、httpx 等），保证离线可复现（NFR-001/002）。选当前本机已验证可用的版本。

### 10. bcrypt 72 字节静默截断
`auth_service`：哈希/校验前对超过 72 字节的口令显式处理（截断到 72 字节并保持哈希/校验一致，或对超长输入返回明确错误）。保证语义明确、行为一致，并加一条测试。

### 11. 登录用户枚举时序旁路
`auth_service.authenticate`：用户不存在时也对一个固定假哈希执行一次 `verify_password`，拉平响应时序。

### 12. 缺「已登录后被停用」测试
新增测试：用户登录拿到 token 后被停用，再用旧 token 调受保护接口返回 403 `INACTIVE_USER`。

### 13. 死代码 / 响应不一致
`schemas.SuccessResponse` 定义未被使用。要么删除，要么在合适处使用以统一 `{data,message}`（登录响应保持 SPEC §8.1 的裸结构不变）。择一处理，避免死代码。

## 验证（必须实际执行，最终消息报告每条结果）
1. `cd backend && ./.venv/bin/pip install -r requirements.txt -r requirements-dev.txt && ./.venv/bin/pytest -q` 全绿，并说明新增测试数量。
2. 手动验证：弱 SECRET_KEY 在 `ENV=production` 启动被拒、在 development 仅告警；本机 `.env` 已生成且 gitignore 生效（`git status` 不含 `.env`）。
3. 手动验证：admin 创建 analyst → analyst 登录成功；不能停用最后一个 admin / 自己。
4. 手动或测试验证：octet-stream 改名 `.pdf` 的可执行内容被拒；正常 pdf/png/jpg/wav/mp4/docx 仍可上传。
5. `npm run type-check && npm run build` 通过（若动了前端）。
不要运行 git commit。报告所有修复与验证结果，以及任何与 PLAN 里程碑边界相关的决定（如把 admin users API 提前到 M1）。
