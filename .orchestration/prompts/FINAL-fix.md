# 任务：EviTrace 终审修复（交付前最后一批）

全项目终审（Codex + 多维 Workflow + 主循环直审 + 实测）结论为 SHIP-WITH-FIXES：核心闭环、权限、多模态证据、冲突检测、MOCK 端到端、Docker 健康、130 测试、3/3 演示均通过，无禁止项。以下为交付前要修的真实项。请精确修复，**每改完都要保证既有验证不回归**（这是硬门槛）。

## 必修

### 1. 解析错误信息未脱敏（路径泄露回归，安全一致性）
位置：`backend/app/services/parse_service.py`（约 191-195 写 `file.error_message`；约 205-215 写 `task.last_error = str(exc)[:1000]`；以及 `result.errors` 合并处）。
现状：与已脱敏的 Skill 健康（registry 走 `public_health_detail`/`redact_health_detail`）和 orchestrator（`_safe_error`）不一致，单文件解析异常或端点顶层异常会把内嵌绝对路径（data_root、模型目录）的原始异常文本写入 `file.error_message`/`task.last_error`，并经 `serialize_file`/`analysis._evidence_payload`/任务详情回传给 owner。真实模式（MOCK_AI=false）下 PyMuPDF/ffmpeg/OCR/ASR 异常常含服务器绝对路径。
修复：复用既有脱敏函数（`backend/app/services/health_details.py` 的 `redact_health_detail` 或 registry 用的 `public_health_detail`），对 `file.error_message`、`task.last_error`、以及可能来自底层异常的 `result.errors` 文本统一脱敏后再落库；保留 task_id/file_id 等非敏感标识。补一条测试：模拟解析异常含绝对路径，断言落库与返回的错误信息已脱敏（不含 data_root 绝对路径）。

### 2. 报告引用强校验：时间线/冲突事实也必须带证据编号（SPEC REPORT-002 / PLAN §11）
现状：`backend/app/utils/citations.py` 的覆盖率只校验「五、综合分析结论」段落（符合 REPORT-003），但 REPORT-002 与 PLAN §11 要求时间线、主要冲突中的事实性陈述同样必须带 `[E-xxxx]`、不得出现无证据编号的确定性事实。真实模型路径可能产出「时间线/冲突无引用」却仍 invalid==0、coverage==1.0、通过完成门禁的报告。
修复（保证 MOCK 演示不回归）：
- 让「三、事件时间线」与「四、主要冲突」两节由**结构化结果确定性生成**（每个事件/冲突行都拼接其 `evidence_ids` 为 `[E-xxxx]`），在 MOCK 与真实模式都如此（真实模式下模型只负责叙述性段落：一、二、五、六）。这样这两节天然带引用、不依赖模型自觉。
- 扩展 `citations` 校验：除结论段覆盖率外，新增对「三、事件时间线」「四、主要冲突」两节的检查——这两节中的事实行若存在但缺少有效 `[E-xxxx]` 则计入问题（可纳入一个新的结构化校验结果字段，如 `uncited_sections` 或并入现有 citation_check），并让完成门禁在存在此类未引用事实时阻断（与 invalid_citations 同级处理）。
- **硬门槛**：改完后 `scripts/evaluate_demo.py` 三组必须仍 `recall≥0.8 / coverage≥0.9 / invalid==0` 且新增的「时间线/冲突未引用」为 0；如有回归，调整模板/fixture 直到通过。
- 不要破坏 fallback 模板（模型失败时仍生成六段、带声明、可进入 awaiting_review）。补/更新测试。

### 3. orchestrator 解析阶段丢失逐文件进度
位置：`backend/app/services/orchestrator.py`（约 270，调用 `parse_service.parse_all_files(task_id)` 未传 run_id）。
现状：`parse_all_files(task_id, run_id=None)` 内 `_mark_run_progress` 因 run_id 为 None 短路，解析期间 run 进度停在粗粒度（10/45），多文件/视频解析时前端观感停滞。
修复：传入 `run_id=run.id`，让逐文件进度回写。注意避免 orchestrator 主 session 与 parse_service 子 session 对同一 run 行的进度互相覆盖（建议解析窗口内进度完全交由 parse_service，orchestrator 不在该窗口重复写 run.progress；进度仍须单调不减）。补/更新进度单调性测试覆盖解析阶段。

### 4. 证据编号正则 4 位硬上限（前瞻性加固）
位置：`backend/app/utils/citations.py`（`E-\d{4}`）、`frontend/src/components/ReportPanel.vue`（`/\[(E-\d{4})\]/`）。
修复：放宽为 `E-\d{4,}`（生成端保持 `:04d` 零填充不变），消除 >9999 条证据时 `E-10000` 被误匹配为 `E-1000` 的隐患。两处保持一致。

## 不在本批次（仅说明，勿改）
- 容器非 root/cap_drop：因 host bind-mount 与 nginx:80 权限耦合，改动易破坏已验证健康的 compose，故**保留现状**（已具备 read_only+tmpfs+no 模型权重）。不要改。
- 截图：占位，由人工在演示时补，**不要伪造**。

## 验证（实际执行，最终消息逐条报告真实输出）
1. `cd backend && ./.venv/bin/pytest -q` 全绿（报告总数，应≥130 且新增测试）。
2. `./backend/.venv/bin/python scripts/evaluate_demo.py` 退出 0，三组 `recall=1.00 / coverage=1.00 / invalid=0`，且新增的时间线/冲突未引用检查为 0；贴出表格。
3. `cd frontend && npm run type-check && npm run build` 通过。
4. AST 3.11 安全（若动了带注解的文件）：确认无未定义注解名（可复用之前的检查思路）。
5. 报告任何为通过硬门槛而对模板/fixture 做的调整。
不要运行 git commit。不引入新依赖。
