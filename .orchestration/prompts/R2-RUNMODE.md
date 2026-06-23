# 任务：运行模式正名 + 部署维度（local/remote）

外部评审指出：`run_mode.py` 只要 LLM/媒体/视觉都非 mock 就把模式标为「本地真实」，但真实配置里文本是 DeepSeek 云端、视觉是 SiliconFlow 云端，仅 OCR/ASR 是本机——「本地真实」名不副实。需把**执行模式**（是否真实）与**部署位置**（本地/远程）拆成两个维度。**严禁泄露任何 base_url/key**（只输出派生出的 local/remote 枚举与 model 名）。不要 git commit；既有测试不回归。

## 1) `backend/app/utils/run_mode.py`
### 标签正名
- `_mode_label`：`real`→「**全真实链路**」（不要再叫"本地真实"）；`mock`→「演示Fixture」；`hybrid`→「混合模式」。

### 新增部署位置派生（不暴露 URL）
- 新增 `_deployment_from_url(base_url: str | None) -> str | None`：把 host 为 `localhost`/`127.0.0.1`/`::1`/`0.0.0.0`/`host.docker.internal` 视为 `"local"`，其它非空 host 视为 `"remote"`，base_url 为空/None 返回 None。用 `urllib.parse.urlparse` 取 hostname 判断；**只返回枚举，不返回 URL**。
- 各组件部署位置：
  - `llm.deployment`：real 时按 `_deployment_from_url(settings.local_llm_base_url)`；mock 时 None。
  - `vision.deployment`：real 时按 `settings.vlm_base_url`；mock 时 None。
  - `ocr.deployment` / `asr.deployment`：real 且配了 `*_base_url`→按 URL 派生；real 且未配 URL（in-process 库）→`"local"`；mock(fixture)→None。
- 顶层 `deployment_mode`：综合所有**真实**组件的部署位置——全为 local→`"local"`；全为 remote→`"remote"`；既有 local 又有 remote→`"mixed"`；无真实组件（全 mock）→`null`。
- 在返回 dict 中：保留现有 `mode`/`mode_label`/`mock_*`/`llm`/`vision`/`ocr`/`asr`/`skills`；给 llm/vision/ocr/asr 各加 `"deployment"` 字段；顶层加 `"execution_mode"`(=现有 mode 的别名或复用 mode) 与 `"deployment_mode"`。保持向后兼容（不删既有键）。
- **安全自证**：单测断言序列化结果不含 `sk-`、不含 `base_url`/`api_key` 键、不含任何 `http://`/`https://`；`_deployment_from_url("https://api.deepseek.com/v1")=="remote"`、`("http://127.0.0.1:8000")=="local"`、`("http://host.docker.internal:8001")=="local"`、`(None) is None`。

## 2) 前端徽章（`frontend/src/types/system.ts` + `frontend/src/components/AppLayout.vue`）
- 类型补充 `deployment`(可选) 与 `deployment_mode`、`execution_mode`。
- 徽章主文案用新 `mode_label`（全真实链路/混合模式/演示Fixture）；hover tooltip 增加每组件「模型 + 本地/远程」信息（如 `LLM: deepseek-v4-flash · 远程`）。`local`显示"本地"、`remote`显示"远程"。
- type-check/build 通过；不硬编码任何密钥/URL。

## 3) 报告元数据（`backend/app/skills/report_generate.py` `_with_run_metadata`）
- 元数据行体现部署位置，例如：
  `> 运行模式：全真实链路（LLM：远程·deepseek-v4-flash｜视觉：远程·Qwen…｜OCR：本地｜ASR：本地）｜分析组件：…`
  （mock 组件仍显示「演示」）。不得出现 URL/key。仍不得影响引用校验（无 `E-\d{4,}` 形态）。

## 验证（实际执行，最终消息逐条报告）
1. `cd backend && ./.venv/bin/pytest -q` 全绿（含 deployment 派生 + 脱敏自证 + 标签正名相关测试更新/新增）。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `./.venv/bin/python scripts/evaluate_demo.py` 仍 3/3，coverage/invalid 不变。
4. `cd frontend && npm run type-check && npm run build` 通过。
报告：run_mode 新结构示例、local/remote 派生规则、脱敏自证、徽章与报告元数据改动。不要 git commit。
