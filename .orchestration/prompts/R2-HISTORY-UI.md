# 任务：前端历史运行下拉框（工作台可查看/切换历史分析版本）

外部评审指出：后端已支持按 `run_id` 查历史（`GET /tasks/{id}/runs`、`/results?run_id=`、`/evidence/index?run_id=`、`/report/download?run_id=`），但前端工作台只读最新运行，普通用户看不到历史。需在工作台加一个「分析版本/历史运行」下拉框。仅前端改动。不要 git commit；`npm run type-check && npm run build` 必须通过。

## 后端现状（已就绪，无需改）
- `GET /tasks/{id}/runs` → `{data:[{run_id,status,progress,started_at,finished_at,has_result}], message}`，按 started_at desc。
- `/tasks/{id}/results?run_id=`、`/tasks/{id}/evidence/index?run_id=`、`/tasks/{id}/evidence?run_id=`、`/tasks/{id}/report/download?run_id=`、`/tasks/{id}/report/regenerate?run_id=`、`PATCH /tasks/{id}/conflicts/{cid}?run_id=` 均接受可选 `run_id`，缺省=最新。

## 前端改动（`frontend/src/views/TaskWorkbenchView.vue` + 必要类型）
1. 载入任务时调用 `GET /tasks/{id}/runs` 取运行列表；新增响应式 `runs` 与 `selectedRunId`（默认 = 列表中**最新有结果**的 run_id，没有则最新 run；空列表则 null）。
2. 在工作台顶部（任务标题/状态附近）加一个 Element Plus `el-select`「分析版本」：每个选项展示 `started_at`（本地时间，格式化）+ 状态 + `has_result ? '' : '（无结果）'` + 短 run_id（前 8 位）。当前展示项高亮。
   - 注：运行模式（演示/真实/混合）目前**未按 run 持久化**，下拉只展示时间/状态/是否有结果，不要臆造每次运行的模式标签。
3. 切换选中 run 后：results / evidence-index / 证据详情 / 报告下载 等请求统一带 `run_id=selectedRunId`（选中最新时可不带或带最新 id，二者等价）。把现有 `getResults`/`getEvidenceIndex`/证据点击/报告下载/重生成/改冲突状态的请求改为附带当前 `run_id`。
4. 新一次分析完成（触发 `POST /runs` 后轮询到终态）时：刷新运行列表，并把 `selectedRunId` 切到这次新 run（保持"看最新"的默认体验）。
5. 轮询「最新运行状态」仍用 `/runs/latest`（用于进度展示）；历史只读展示用 selectedRunId。选择历史（已完成）运行时不应显示"进行中"轮询态。
6. 不破坏现有交互（时间线/冲突/证据/报告四面板照常，只是数据源带 run_id）；不硬编码任何密钥/URL。

## 验证（实际执行，最终消息报告）
1. `cd frontend && npm run type-check` 通过。
2. `cd frontend && npm run build` 通过。
3. （如方便）`cd backend && ./.venv/bin/pytest -q` 仍全绿（不应受影响）。
报告：下拉框位置与展示字段、run_id 透传到哪些请求、切换/新运行后的刷新逻辑、type-check/build 结果。不要 git commit。
