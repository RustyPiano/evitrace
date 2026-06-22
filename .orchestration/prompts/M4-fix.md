# 任务：修复 EviTrace M4 三方审核（Opus×2 + Codex）发现的问题

M4 已实现并提交（124 测试通过；安全审核基本 PASS）。以下问题由三方审核交叉确认，两个 MAJOR 已由架构师复现。请**精确修复**并跑测试/构建验证。不实现 M5（演示数据/Docker 生产化/README 终稿）。

## MAJOR

### 1. 证据引用联动分页缺陷：超过 50 条的 `[E-xxxx]` 点击失效（已复现）
现状：`backend/app/services/result_service.py:18` `MAX_PAGE_SIZE=50` 且 list 接口把 page_size 钳到 50；而 `frontend/src/views/TaskWorkbenchView.vue:273` 只请求第 1 页 `page_size:500`。任务证据 >50 条时，第 51 条起的 `display_id` 无法映射到 evidence UUID，时间线/冲突/报告里点击 `[E-00xx]` 提示“未找到证据”。
修复（择一，要正确支持 >50 条且有验证）：
- 推荐：前端按分页**循环拉取全部证据**构建 display_id→evidence 映射（每页 50，直到取完 total）；或
- 后端新增轻量映射接口（如 `GET /api/v1/tasks/{id}/evidence/index` 返回 `[{display_id,id,modality,evidence_type}]`，owner/admin 权限，不分页或高上限），前端用它做引用联动。
无论哪种，确保点击任意存在的 `[E-xxxx]`（含第 51+ 条）都能打开正确证据。补一个验证（>50 条证据时引用可解析）。

### 2. Skill 健康探测错误泄露完整路径（健康类页面脱敏要求）
现状：`backend/app/skills/registry.py:170` `config.last_error = str(exc)` 原样持久化并在 `AdminSkillsView` 展示；OCR/ASR 模型目录不存在时 exc 含完整本地路径（泄露 DATA_ROOT/模型目录）。
修复：健康探测错误**入库与返回前统一脱敏**（复用 M4 已有的 `_short_detail`/脱敏逻辑：替换 data_root/模型目录/secret/api_key/base_url，截断长度）。前端只显示通用原因（如“模型目录未就绪 / 依赖未安装 / FFmpeg 不可用”）。skill last_status/last_error 走同一脱敏。

## MINOR

### 3. 报告面板空状态与覆盖率警告/重生成按钮不一致
位置：`frontend/src/components/ReportPanel.vue`（约 16/25/77）。报告未生成时 `citationCheck` 为空却按覆盖率 0 显示“<90%”警告，且“重新生成”可点最终 404。
修复：覆盖率警告与“重新生成报告”按钮都以 `analysisComplete && citationCheck` 为前提；无结果时只显示空状态原因。

### 4. 用户管理自锁/最后管理员限制缺少原因提示
位置：`frontend/src/views/AdminUsersView.vue`。当前只禁用控件不解释。
修复：给禁用的角色选择/启停控件加 tooltip/行内说明：“不能修改当前登录账号”“至少保留一个启用管理员”。

### 5. 工作台轮询应改为递归 setTimeout
位置：`frontend/src/views/TaskWorkbenchView.vue`（约 380-386，`setInterval(...,2000)`）。
修复：改为递归 `setTimeout`（上一轮 refresh 完成后再排下一轮），避免请求叠加；轮询回调加异常保护，token 失效/持续 401 时停止轮询而非每 2s 反复弹错。保持 2s 间隔。

### 6. 删除死代码
`frontend/src/views/TaskDetailView.vue` 与 `frontend/src/views/AdminPlaceholderView.vue` 已无路由/import 引用（被 TaskWorkbenchView 与具体 admin 页取代）。删除二者，确认 router 无悬挂引用、`type-check`/`build` 仍通过。

### 7. 上传大小上限前端硬编码
位置：`frontend/src/components/FileUploadPanel.vue`（硬编码 200MB）。
修复：让前端从后端获取 `MAX_UPLOAD_MB`（可在某个已有接口或新增轻量 `GET /api/v1/config`/复用 health 返回公开配置；不要暴露敏感项），避免与后端不一致的误导文案。

### 8. 标记完成补审计（§12 管理员操作留痕）
位置：`backend/app/services/task_service.py`。任务置 `completed` 后补 `record_audit(action="task_completed", detail={"force": force})`（脱敏）。

### 9. RequestValidationError 响应收敛（M0 遗留）
位置：`backend/app/main.py`（约 81-85）。422 处理器当前回传 `str(exc)`。改为返回精简结构（如 `exc.errors()` 的字段路径与类型，去掉输入值）或固定 message，详细仅服务端日志。保持 `{detail:{code,message}}` 结构。

### 10. （SHOULD）视频关键帧证据支持视频跳转
位置：`frontend/src/components/EvidencePanel.vue`。`video_frame` 证据当前仅显示静态帧缩略图；按 §10.6，应同时提供视频播放器并可跳到 `timestamp_ms`。补充：video_frame 证据除缩略图外，加载原视频并 seek 到 timestamp_ms（与 video_audio 跳转一致）。若实现成本高可保留缩略图为主、增加“在视频中定位”入口。

## 验证（实际执行，最终消息报告）
1. 后端 `cd backend && ./.venv/bin/pytest -q` 全绿（含新增引用分页/脱敏相关测试）。
2. 前端 `npm run type-check && npm run build` 通过；确认删除死代码后无悬挂引用、无 CDN。
3. 端到端（MOCK）：构造 >50 条证据的任务，确认第 51+ 条 `[E-xxxx]` 点击可打开证据；Skill 健康错误不含完整路径；报告空状态不误显警告。
4. 报告所有修复与验证结果及任何边界决定（如选择前端分页还是新增映射接口）。
不要运行 git commit。
