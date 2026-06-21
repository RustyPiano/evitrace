# 代码审核任务：EviTrace M3（Agent 工作流、提取、冲突、报告）

你是独立代码审核员（只读，禁止修改）。审核 M3 是否符合 `SPEC.md`/`PLAN.md`，重点是**分析逻辑正确性、状态机、引用验证、MOCK 确定性与安全**。

## 依据
- `SPEC.md` §4.2、§5.5–5.8、§8.4、§9、§13、NFR-003/004/005。
- `PLAN.md` 第 5 章 M3-01~07、第 8 章伪代码、第 9 章测试矩阵、第 10 章降级。
- 代码：`backend/app/services/{llm_client,orchestrator}.py`、`backend/app/skills/{intelligence_extract,conflict_detect,report_generate}.py`、`backend/app/utils/{json_repair,citations,time_normalize}.py`、`backend/app/schemas_analysis.py`、`backend/app/api/analysis.py`、`backend/app/main.py`、`backend/tests/*`、`frontend/src/views/TaskDetailView.vue`。

## 必查项
1. **冲突规则（核心）**：时间(>30min/仅日期不同/不可解析不比较)、地点(规范化后不同)、数量(同单位不同值；异单位仅 warning) 是否完全符合 SPEC §5.7；6 条必备用例是否都有测试且正确；边界（恰好 30 分钟、跨午夜、时区）是否合理；不同 event_key 不比较。
2. **time_normalize**：解析逻辑是否健壮（多格式、失败返回 null 不抛）；时间差计算正确。
3. **引用验证（citations）**：`E-\d{4}` 提取；只认当前任务证据；coverage 计算（综合结论每个非空段落是否含引用）是否符合 PLAN 8.3；invalid_citations 统计正确。
4. **extraction schema/逻辑**：confidence∈[0,1]、evidence_ids≥1、event_id 服务端重编号、无效 evidence 引用过滤/丢弃+warning、未知字段不崩；批处理与合并；时间线排序与模糊时间分组。
5. **MOCK 确定性与不伪造**：MOCK 提取/报告是否确定；是否只引用真实存在的 display_id；报告 invalid_citations==0 且 coverage≥0.9；证据为空是否明确失败而非伪造。
6. **report fallback（MUST）**：模型失败时纯模板最小报告是否可用、任务仍能进入 awaiting_review 带 warning；报告是否含「AI 辅助生成需人工复核」声明；固定六段结构。
7. **orchestrator 状态机**：parse→extract→conflict→report 顺序；进度单调不减；run_guard 单运行（运行中 409）；异常→run/task failed 且错误摘要不泄露内部细节；成功→awaiting_review；保存 AnalysisResult 完整。
8. **重跑**：保留文件、删旧 evidence、清旧 analysis_result、新建 run、不覆盖历史 run。
9. **启动恢复（NFR-003）**：启动把 running run 置 failed、task failed、明确 last_error。
10. **LLM client**：业务 skill 是否经 client 而非直接 httpx；真实模式超时/重试(≤2)/json 提取修复/schema 校验/最终 INVALID_MODEL_OUTPUT/不可达 503；MOCK 不联网；不发二进制；日志不泄露敏感全文。
11. **Analysis API**：路径/权限/错误码与 §8.4/§13 一致；无文件 409、运行中 409、非 owner 不可见；冲突 PATCH 持久化；报告 download 文件名与内容；regenerate 不重跑解析。
12. **前端**：Markdown 渲染是否禁用原始 HTML/严格 sanitize（防 XSS）；轮询是否 2s；是否无 CDN。
13. 是否引入被禁止依赖；是否越界实现 M4 完整工作台/管理页。

## 输出
每个发现：严重级别（BLOCKER/MAJOR/MINOR/NIT）、文件:行、问题、修复建议。最后一行总评 PASS/PASS-WITH-FIXES/FAIL + 进入 M4 前必修项。只报告真实问题。
