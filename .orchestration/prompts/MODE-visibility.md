# 任务：运行模式可见化（API + 前端徽章 + 报告元数据）

外部评审指出：系统无法从界面或报告看出当前是「演示 Fixture / 本地真实 / 混合」哪种模式运行，答辩时易被质疑「是否偷偷用 mock」。需要把运行模式与所用模型显式暴露出来。**严禁泄露任何 API key 或带凭证的 URL**；不要 git commit；既有测试不回归。

## 背景（已确认事实）
- `app/config.py` 的 `settings` 有三个有效模式属性：`effective_mock_llm`、`effective_mock_media`、`effective_mock_vision`（布尔）。模型名：`local_llm_model`、`vlm_model`（real 视觉时）；OCR/ASR 来源由 `ocr_base_url`/`asr_base_url`（配则 HTTP）否则 `ocr_model_dir`/faster-whisper 库决定；mock 时为 fixture。
- Skill 版本在各 Skill 的 `manifest.version`，可经 `app/skills/registry.py` 的注册表读取（用现有 API，不要新建并行注册逻辑）。
- 敏感值脱敏工具：`app/utils/health_details.py` 的 `redact_health_detail`（已对各 key 脱敏）。

## 1) 运行模式工具 `app/utils/run_mode.py`（新增）
实现 `run_mode_metadata() -> dict`，返回**不含任何 key/凭证**的结构：
```
{
  "mode": "real" | "mock" | "hybrid",          # 全真实=real，全 mock=real 的反面=mock，混合=hybrid
  "mode_label": "本地真实" | "演示Fixture" | "混合模式",
  "mock_llm": bool, "mock_media": bool, "mock_vision": bool,
  "llm": {"real": bool, "model": <local_llm_model 仅当 real，否则 null>},
  "vision": {"real": bool, "model": <vlm_model 仅当 real，否则 null>},
  "ocr": {"real": bool, "source": "http"|"lib"|"fixture"},   # real 且配 OCR_BASE_URL=http；real 未配=lib；mock=fixture
  "asr": {"real": bool, "source": "http"|"lib"|"fixture"},
  "skills": [{"id": ..., "name": ..., "version": ...}, ...]   # 取自 registry manifest
}
```
- `mode`：三者(llm/media/vision)全 mock → `mock`；全 real → `real`；否则 `hybrid`。media 的 real 指 `effective_mock_media=False`。
- **绝不**输出 `*_api_key`、`*_base_url`（URL 也不要，只给 source 枚举与 model 名）。model 名是安全的（如 `deepseek-v4-flash`/`Qwen/...`），可输出。
- 单元测试覆盖：全 mock→mock、全配齐→real、仅 LLM 真实→hybrid，且断言返回 dict 序列化后不含任何 `sk-`、不含 `base_url`/`api_key` 键、不含 http URL。

## 2) API 端点 `GET /system/mode`
- 新增 `app/api/system.py`，`GET /system/mode`，依赖 `get_current_user`（登录可见即可，不限管理员），返回 `{"data": run_mode_metadata(), "message": "ok"}`。
- 在应用路由汇总处（找现有 `include_router` 的位置）注册，保持与其它路由一致的前缀风格（其它是 `/tasks`、`/auth` 等，无额外 `/api` 前缀则同样不加）。
- 测试：登录后 200、结构正确、未登录 401/403（与现有受保护端点一致）。

## 3) 报告元数据
报告需写入运行模式与模型名（评审要求「模型名称、Skill 版本和运行模式写入报告元数据」）。
- 在 `app/skills/report_generate.py`：新增后处理函数 `_with_run_metadata(markdown)`，在报告**通知行 `REPORT_NOTICE` 之后、正文之前**插入一行 blockquote：
  `> 运行模式：<mode_label>｜LLM：<model 或 演示>｜视觉：<model 或 演示/未启用>｜OCR：<http/本地库/演示>｜ASR：<http/本地库/演示>｜分析组件：intelligence_extract@x.y.z, conflict_detect@x.y.z, report_generate@x.y.z`
  （组件版本取这三个 required skill 的 manifest.version）。
- 在 `run()` 里对**所有分支**（mock 报告、real 报告、降级报告）统一应用 `_with_run_metadata`，保证恒存在。注意调用顺序：先确定 markdown（含 notice），再插入元数据，再 `_with_structured_fact_sections`，最后引用校验。
- 校验影响自检：该 blockquote 放在 `二、资料概况` 之前的头部，不属于 `三/四` 事实行、不属于 `五` 结论段，**不得**影响 `validate_report_citations` 的覆盖率/无效引用统计；model 名不含 `E-\d{4,}` 形态。请确认 evaluate_demo 的覆盖率/invalid 不变。

## 4) 前端徽章
- 找到登录后主框架/顶部栏组件（如 `frontend/src/App.vue` 或布局组件 / 顶部导航）。新增一个运行模式徽章（Element Plus `el-tag`）：
  - `real`→`type="success"` 文案「本地真实」；`mock`→`type="info"`「演示Fixture」；`hybrid`→`type="warning"`「混合模式」。
  - 鼠标悬停 `title`/tooltip 显示 LLM/视觉/OCR/ASR 各自 model 或来源。
- 用现有 API 客户端模式（找 `frontend/src/api`/services 既有写法）新增 `getSystemMode()`，登录后获取一次（可放现有 store 或 App 挂载时）。不要硬编码任何密钥/URL。
- `npm run type-check && npm run build` 通过。

## 验证（实际执行，最终消息逐条报告）
1. `cd backend && ./.venv/bin/pytest -q` 全绿（含新增 run_mode/endpoint/report-metadata 测试）。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `./.venv/bin/python scripts/evaluate_demo.py` 仍 3/3，coverage/invalid 不变。
4. `cd frontend && npm run type-check && npm run build` 通过。
报告：改动文件、端点契约、脱敏自证（输出不含 key/URL）、报告元数据示例行、前端徽章位置。不要 git commit。
