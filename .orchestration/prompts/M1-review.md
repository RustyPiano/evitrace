# 代码审核任务：EviTrace M1（登录、权限、任务、文件）

你是独立代码审核员（只读，禁止修改）。审核 M1 实现是否符合 `SPEC.md`/`PLAN.md`，重点是**安全与正确性**。

## 依据
- `SPEC.md` §3（权限规则）、§5.1–5.3、§7（数据模型列名/约束）、§8（API/错误结构）、§12（安全）、§13（错误码）、NFR-005（日志不泄露）。
- `PLAN.md` 第 3 章 M1-01~05、第 9 章测试矩阵。
- 代码主要在 `backend/app/{models,constants,dependencies,schemas,main}.py`、`backend/app/api/*`、`backend/app/services/*`、`backend/app/skills/registry.py`、`backend/app/utils/file_types.py`、`backend/tests/*` 与 `frontend/src/*`。

## 必查项（逐条核对，给真实发现）
1. **认证安全**：密码是否哈希存储且校验正确；JWT 是否用 SECRET_KEY 签名、是否校验过期/签名；`get_current_user` 是否正确拒绝无效/过期 token 与停用用户；登录失败是否统一 401 `INVALID_CREDENTIALS`（不泄露是用户名还是密码错）。
2. **越权 / IDOR**：所有任务/文件/证据相关接口是否都做了 owner/admin 校验；非 owner 访问他人任务是否一致返回 404（不要时而 403 时而 404）；能否通过改 URL 中的 task_id/file_id 访问他人资源；`DELETE /files/{file_id}` 与 `/files/{file_id}/stream` 是否经过任务归属校验。
3. **文件上传安全**：白名单与 MIME 双校验是否可被双扩展名/大小写绕过；`.exe/.sh/.bat/.js` 是否被拒；`MAX_UPLOAD_MB` 超限是否 413 且不会把超大文件整体读入内存导致 OOM；原始文件名清洗与 UUID 落盘；**路径穿越**：`../../x`、绝对路径、符号链接是否被 `resolve()`+前缀校验挡住；stream 是否可能返回任务目录外文件。
4. **数据模型（SPEC §7）**：8 张表列名/类型/约束是否逐字对齐；`users.username` unique、`evidence (task_id, display_id)` 唯一、`analysis_results.task_id` unique 是否建立；时间是否 UTC、是否误用已弃用 `utcnow`；JSON 是否以 Text 存储；状态枚举取值是否等于 SPEC 字面值。
5. **级联删除**：删除任务是否清理 DB 关联记录与磁盘 `data/tasks/{id}` 目录；运行中任务是否禁止删除。
6. **错误码/响应**：是否使用 SPEC §13 的错误码与 §8 统一 `{detail:{code,message}}` 结构；5xx 是否不泄露内部细节。
7. **审计日志**：登录成功/失败、创建任务、删除任务、上传文件是否写 audit；是否避免记录密码/JWT/敏感全文。
8. **前端权限**：路由守卫与 401 处理是否正确；是否存在“仅前端拦截、后端不校验”的依赖（后端必须独立校验）。
9. **并发/CWD/资源**：文件流是否正确关闭句柄；是否复用 M0 的 PROJECT_ROOT 路径而非 CWD 相对路径。
10. 是否引入被禁止依赖；是否越界实现了 M2+ 内容。

## 输出
对每个发现：严重级别（BLOCKER/MAJOR/MINOR/NIT）、文件:行、问题、修复建议。最后一行总评：PASS / PASS-WITH-FIXES / FAIL，并说明进入 M2 前必须修的项。只报告真实问题。
