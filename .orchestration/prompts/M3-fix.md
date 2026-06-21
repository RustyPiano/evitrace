# 任务：修复 EviTrace M3 三方审核（Opus×2 + Codex）发现的问题

M3 已实现并提交，94 测试通过（但覆盖有缺口，且有跨版本/真实模式硬伤）。以下问题由三个独立审核员交叉确认，部分已由架构师复现。请**精确修复**并实际跑 `pytest`，为关键修复补测试。不顺手改无关代码，不实现 M4 完整工作台。

## BLOCKER

### 1. Docker(Python 3.11) 启动崩溃：注解引用未导入的 `SkillManifest`（本机 3.14 因 PEP 649 惰性注解掩盖）
位置：`backend/app/skills/registry.py:54` `def get_manifest(...) -> SkillManifest:`，既无 `from __future__ import annotations` 也未导入 `SkillManifest`。Python 3.11 在模块导入时即求值函数注解 → `NameError` → `app.main` 无法启动（Docker 用 3.11）。已用 AST 复现确认。
修复：
- 修 registry.py（导入 `SkillManifest` 并在文件顶部加 `from __future__ import annotations`）。
- **全仓扫描同类隐患**：对 `backend/app/**/*.py` 检查是否存在「函数/类注解引用了未导入也未定义的名字」且该文件没有 `from __future__ import annotations`。对所有命中文件统一加 `from __future__ import annotations`（标准、安全）并修正缺失导入。给出一个 AST 静态校验脚本/步骤证明修复后**无任何**此类隐患（即模拟 3.11 的 eager 注解求值不再有未定义名）。

### 2. 时间冲突误判：`datetime` 是 `date` 的子类导致「纯日期 vs 同日带时刻」被判冲突
位置：`backend/app/skills/conflict_detect.py`（约 66-69，用 `isinstance(value, date)` 判断）。
现状：一侧 datetime 时 `isinstance(dt, date)` 为 True → 不调用 `.date()` → `date(2026,6,1) != datetime(2026,6,1,16,30)` 为 True → 同一天误报时间冲突。违反 SPEC §5.7「只有日期时日期不同即冲突」。
修复：按 `kind` 区分而非 isinstance：datetime 取 `.date()` 后比较日期；只有当至少一侧是纯 date 时走「日期不同即冲突」。补测试。

### 3. 冲突边界测试缺失（PLAN 第 9 章/§5.7 验收门槛）
补齐纯函数单测：恰好 30 分钟→不冲突（“大于”）；跨午夜 23:50 vs 次日 00:30(=40min)→冲突、23:50 vs 00:20(=30min)→不冲突；仅日期相同→不冲突、仅日期不同→冲突；纯日期 vs 同日 datetime→不冲突（即第 2 条回归）；同地点不同表述（`地点 A` vs `地点A`）→不冲突；时区 aware vs naive（见第 4 条）。

## MAJOR

### 4. 冲突时间相减：tz-aware 与 naive 混比抛 `TypeError`
位置：`conflict_detect.py`（时间相减处）。
修复：定义统一策略——把可解析时间统一规整（建议都转 naive 本地或都转 UTC），混合时安全处理；无法安全比较时跳过并记 warning，不抛异常使任务失败。补时区边界测试。

### 5. `time_normalized` 未校验即入时间线 → 非法字符串被当确定时间并按字符串排序
位置：`backend/app/skills/intelligence_extract.py`（sanitize 阶段约 168）。
修复：sanitize 时对 `time_normalized` 调 `parse_time_value`，**不可解析则置 `time_normalized=None` 并记 warning**，保留 `time_text`；时间线只对可解析时间排序，其余进「时间未确定」。

### 6. time_normalize 解析格式过窄，真实链路时间冲突大量漏检（影响 §15.2 ≥80%）
位置：`backend/app/utils/time_normalize.py`。
现状：仅 `date/datetime.fromisoformat`，`"14:00"`、`"2026/06/01 14:00"`、`"6月1日14:00"` 等均返回 None。
修复：扩展常见格式容错——`YYYY/MM/DD[ HH:MM[:SS]]`、`YYYY-MM-DD HH:MM`、`HH:MM`（仅时间：标记为 time-only，不参与跨日比较或按当日比较，需明确语义并与冲突规则一致）、常见中文日期（`YYYY年M月D日`、`M月D日[ HH:MM]`）。解析失败仍返回 None 不抛。补单测覆盖这些格式与失败用例。注意与第 2/4 条的 kind/tz 策略保持一致。

### 7. 真实模式报告未强制六段结构与「AI 辅助生成需人工复核」声明
位置：`backend/app/skills/report_generate.py`（约 153，只检查是否含「## 五、综合分析结论」）。
修复：统一在报告 prepend「**AI 辅助生成，需人工复核。**」声明；校验 6 个固定标题（§5.8 一~六）齐全，缺任一则走 fallback 模板；fallback 同样含声明与六段。

### 8. 真实提取 sanitize 的 warning 被丢弃（无效 evidence 引用过滤但不告警，违反 M3-02）
位置：`intelligence_extract.py`（约 305，`_sanitize_extraction` 的 warnings 未聚合）。
修复：聚合各批次 sanitize warnings 并并入 SkillResult.warnings（含「丢弃了引用无效证据的事件」等）。

### 9. `llm_client` 真实模式 `response.json()` 解析失败未映射为 `INVALID_MODEL_OUTPUT`
位置：`backend/app/services/llm_client.py`（约 168）。
修复：捕获 `ValueError`/结构异常，按重试逻辑处理，最终包装为 `AppError("INVALID_MODEL_OUTPUT", 500)`；非 200 状态码也要有明确映射。

### 10. 完成门禁缺失：`awaiting_review → completed` 未校验引用质量（SPEC §5.8 REPORT-003）
位置：`backend/app/services/task_service.py`（约 155，标记 completed 处）。
现状：只校验当前状态是 awaiting_review，未读 citation_check。
修复：标记 completed 前读取 `AnalysisResult.citation_check_json`：
- `invalid_citations` 非空 → 一律拒绝完成（明确错误）。
- `citation_coverage < 0.9` → 仅当**管理员**且显式 `force=true` 时允许；否则拒绝并提示。
为 PATCH 完成增加可选 `force` 字段（仅 admin 生效）。补测试（普通用户低覆盖率被拒；admin force 通过；有无效引用一律拒）。

## MINOR

### 11. 启动恢复未归一 current_step/progress（“已失败仍显示 55% extracting”）
位置：`orchestrator.recover_interrupted_runs`。修复：置 failed 时同时把 `current_step` 归一（如 None/"failed"），`progress` 可保留或归零，保证与 status 一致。

### 12. 后台任务异常吞没/中间态卡死兜底（NFR-003，连带单运行滞留）
位置：`orchestrator.execute_run`。修复：用 `finally` 守卫——离开时若 run 仍 queued/running，用**新 session**强制置 failed（task 同步 failed + last_error）；后台任务整体再包一层 try/except 记录日志。确保异常路径下旧 run 必达终态，避免 `ensure_no_active_run` 永久 409 阻塞全局。（执行期互斥可在 execute_run 入口二次校验无其它 running run；不要求重写为长锁。）

### 13. 引用「综合分析结论」标题匹配脆弱
位置：`backend/app/utils/citations.py`。修复：标题用正则 `^##\s*五、\s*综合分析结论` 容错（`report_generate` 的结构校验同步用同一正则口径）。

### 14. 同一事实跨批不合并 evidence_ids
位置：`intelligence_extract._merge_extractions`。修复：相同 `(event_key, fact_key)` 的事件合并其 `evidence_ids`（去重）为一条，而非按 evidence 集合保留多条，避免时间线重复与自比较噪声。

### 15. 报告下载文件名时间戳与清洗
位置：`backend/app/api/analysis.py`。修复：文件名时间戳用 `result.updated_at`（报告时刻）而非 `datetime.now()`；对 `task.name` 做基础清洗后再拼入文件名。

### 16. 杂项
- `LLM_MAX_RETRIES` 客户端内 `min(value, 2)` 或配置上限，落实「最多 2 次」。
- 前端 `TaskDetailView.vue` 轮询间隔 `1500`→`2000`（NFR-004）。

## 验证（实际执行，最终消息报告每条）
1. `cd backend && ./.venv/bin/pip install -r requirements.txt -r requirements-dev.txt && ./.venv/bin/pytest -q` 全绿，报告新增/总测试数。
2. 给出 AST 静态校验输出，证明全仓无「3.11 eager 注解引用未定义名」隐患（第 1 条）。
3. 端到端（MOCK）：完整 run→awaiting_review；报告 invalid_citations==0 且 coverage≥0.9；冲突含时间/地点/数量；纯日期 vs 同日 datetime 不再误报；time_normalize 新格式用例通过。
4. 完成门禁：低覆盖率普通用户被拒、admin force 通过、有无效引用一律拒。
5. 前端 `npm run type-check && build` 通过。
不要运行 git commit。报告所有修复与验证结果及任何边界决定。
