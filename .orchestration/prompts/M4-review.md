# 代码审核任务：EviTrace M4（完整前端工作台与管理页）

你是独立代码审核员（只读，禁止修改）。审核 M4 是否符合 `SPEC.md`/`PLAN.md`。

## 依据
- `SPEC.md` §10（UI/UX，尤其 §10.2 路由、§10.6 工作台、§10.7 管理页）、§5.7/§5.8、§8.5 Admin API、§12 安全、§13、NFR-001/004。
- `PLAN.md` 第 6 章 M4-01~07、第 11 章禁止事项。
- 代码：`frontend/src/views/*`、`frontend/src/components/*`、`frontend/src/router/index.ts`、`frontend/src/api/*`、`frontend/src/stores/*`、`backend/app/api/admin.py`、`backend/tests/integration/test_admin_health_audit.py`。

## 必查项
1. **工作台**（§10.6）：三栏布局；顶部开始/重跑/标记完成/下载；左栏文件+步骤+plan_json；中栏 概览/时间线/冲突/报告 Tab；右栏 EvidencePanel；2s 轮询；完成自动停轮询；刷新后状态保持（从后端拉取）；失败显示 last_error + 重试；运行中禁用冲突编辑/删文件/重复开始。
2. **时间线**：时间升序、模糊时间独立区、证据按钮联动 EvidencePanel、空状态。
3. **冲突面板**：类型筛选、左右值、双方证据、状态下拉 PATCH、改后持久化、计数同步、无冲突空文案、运行中禁用。
4. **报告面板（安全重点）**：Markdown 是否禁用原始 HTML/严格 sanitize（确认 `v-html` 内容经转义，无法注入 `<script>`/`onerror`）；`[E-xxxx]` 可点击且无效引用标红；覆盖率<0.9 警告；重生成/下载；完成门禁 UI（覆盖率低时管理员 force）。
5. **管理页**：users（建/启停/重置/角色，自锁与最后管理员限制提示）、skills（required 禁停、非必需启停、健康探测）、health（DB/磁盘/LLM/FFmpeg/OCR/ASR，**不泄露 Secret/完整路径**）、audit（分页）。
6. **权限**：`/admin/*` 路由守卫；分析员无菜单且被拦；**后端独立二次校验**（不能仅前端）；axios 401 处理。
7. **后端 admin 接口**：`GET /admin/health` 是否脱敏（不返回完整磁盘路径/密钥/base_url 明文）、权限 admin-only、组件探测非致命；`GET /admin/audit-logs` 权限+分页；审计是否覆盖 启动分析/下载报告/启停 Skill/创建停用用户。
8. **死代码/一致性**：`TaskDetailView.vue`、`AdminPlaceholderView.vue` 是否已成为死代码（路由是否还引用）；是否有重复/未用组件。
9. 离线 NFR-001（无 CDN）；状态色一致；按钮防重复提交；加载/空/错误三态；是否引入被禁止依赖（markdown CDN/聊天页/地图3D）。
10. 是否越界实现 M5（不应包含演示数据/Docker 生产化/README 终稿）。

## 输出
每个发现：严重级别（BLOCKER/MAJOR/MINOR/NIT）、文件:行、问题、修复建议。最后一行总评 PASS/PASS-WITH-FIXES/FAIL + 进入 M5 前必修项。只报告真实问题。
