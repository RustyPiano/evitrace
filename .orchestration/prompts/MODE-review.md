# 代码审核（只读，禁止修改）：运行模式可见化

独立审核新增的「运行模式可见化」特性。这是增量、低风险特性：暴露当前运行是 演示Fixture/本地真实/混合 哪种模式 + 所用模型 + Skill 版本。

## 范围
`backend/app/utils/run_mode.py`、`backend/app/api/system.py`、`backend/app/main.py`、`backend/app/skills/report_generate.py`、`frontend/src/api/system.ts`、`frontend/src/types/system.ts`、`frontend/src/components/AppLayout.vue`、新增测试。

## 必查项（只报真实问题）
1. **泄露（最高优先）**：`run_mode_metadata()` 及 `/system/mode` 响应、报告元数据行，**绝不能**包含任何 API key、`*_api_key`、带凭证或主机的 URL（`http(s)://...`）。model 名（如 deepseek-v4-flash / Qwen/...）可输出。逐一确认 llm/vision/ocr/asr 分支不会间接带出 base_url 或 key。
2. **鉴权**：`/system/mode` 是否要求登录（get_current_user），未登录是否 401；是否误加了管理员限制（应普通登录用户可见）。
3. **路由**：是否按现有约定注册（前缀与其它路由一致）、无重复/冲突路径。
4. **报告元数据**：blockquote 是否插在 REPORT_NOTICE 之后、正文之前；是否对 mock/real/fallback **所有分支**生效；其内容是否可能被 `validate_report_citations` 误判（含 `E-\d{4,}` 形态？影响覆盖率/invalid？）；mode/source 标签映射是否覆盖全部枚举（http/lib/fixture、real/mock/hybrid），有无 KeyError 风险。
5. **健壮性**：`_skills_metadata` 读注册表是否稳定；`metadata["llm"]["model"]` 为 None 时报告行是否回退「演示/未启用」；vision real 但 model 为 None 的边界。
6. **前端**：徽章类型映射（real=success/mock=info/hybrid=warning）、登录后获取时机、type-check 是否真正通过、是否硬编码任何密钥/URL。
7. **回归**：evaluate_demo 3/3、coverage/invalid 不变；既有报告相关测试是否仍语义正确。

## 输出
每个发现：严重级（BLOCKER/MAJOR/MINOR/NIT）、文件:行、问题、修复建议。末行总评 PASS / PASS-WITH-FIXES / FAIL + 合并前必修项。
