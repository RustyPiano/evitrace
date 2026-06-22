# 任务：修复历史保留审核（codex）发现的 1 BLOCKER + 3 MAJOR

审核 FAIL。下述问题只影响「旧库迁移」与「历史运行的帧/源访问」（新库 + 单运行不受影响，故现有测试全绿）。逐项修复 + 补针对性测试，既有测试不回归、demo 仍 3/3。不要 git commit。

## BLOCKER：SQLite 无法 DROP 旧 `unique=True` 生成的表内 UNIQUE 约束（`backend/app/database.py`）
旧模型 `AnalysisResult.task_id = unique=True` 会生成 `sqlite_autoindex_analysis_results_*`，**该 autoindex 背后是表级 UNIQUE 约束，`DROP INDEX` 必然失败**（被 except 吞掉），约束仍在 → 旧库重跑同一任务插入第二条 `analysis_results` 触发 UNIQUE 失败。
**修复（表重建迁移）**：在 `_migrate_sqlite_schema` 中，检测 `analysis_results` 是否存在「唯一且仅含 task_id」的约束/autoindex（`PRAGMA index_list`，origin 为 `u`/`pk` 或 `unique=1` 且 `PRAGMA index_info` 列为 `["task_id"]`）。若存在，执行标准 SQLite 表重建：
1. `ALTER TABLE analysis_results RENAME TO analysis_results_legacy;`
2. 用**当前 SQLAlchemy 模型**重建新表：`AnalysisResult.__table__.create(bind=connection)`（当前模型已无 unique，schema 正确，并带应有的非唯一索引）。
3. 按**新旧列交集**复制数据：`INSERT INTO analysis_results (<cols>) SELECT <cols> FROM analysis_results_legacy;`（用 `PRAGMA table_info` 取两表列名求交集，避免列不匹配）。
4. `DROP TABLE analysis_results_legacy;`
- 全程 try/except、日志只记异常类型名（脱敏）；非 SQLite 跳过；幂等（已无 UNIQUE 时不重建）。注意外键：无其它表 FK 指向 analysis_results，安全。
- 顺序：`create_all` 之后执行（旧库 create_all 不会改已存在表）。`evidence.run_id` 的 ADD COLUMN/回填逻辑保留。
- **测试**：构造旧 schema（`CREATE TABLE analysis_results(... task_id TEXT NOT NULL UNIQUE ...)` 贴近旧模型列）+ 插一条；调用 `initialize_database()`；断言可插入**第二条**同 task_id 的结果、且旧数据保留、`evidence.run_id` 列存在并回填。

## MAJOR 1：重跑删除派生帧/音频，历史运行帧/源失效（`backend/app/services/parse_service.py` + 帧写入处 + `result_service`）
当前帧/音频在共享目录 `derived/frames`、`derived/audio`，`_cleanup_file_derived_artifacts(task_id, file_id)` 重跑时删掉同 file_id 的全部派生文件，毁掉历史运行证据引用的帧。
**修复（按 run 隔离派生文件）**：
- 帧/音频落盘路径**按 run_id 命名空间**：如 `derived/runs/{run_id}/frames/...`、`derived/runs/{run_id}/audio/...`（找到视频抽帧/音频写入处——`video_parse`/`extract_video_frames`/media——传入并使用 run_id 子目录）。证据 locator 里存的 `frame_path` 随之为 run 隔离路径。
- `_cleanup_file_derived_artifacts` 改为**只清理当前 run** 的该 file 派生目录（接受 run_id 参数，仅删 `derived/runs/{run_id}/...` 下该 file 的产物），绝不动其它 run。
- `_validate_frame_paths` 的安全根（`frames_root`）放宽到 `derived`（或 `derived/runs`）基目录并保持 `is_relative_to` 路径穿越校验。
- `frame_file_response` 仍按 locator 的 frame_path 读取（run 隔离后历史帧仍在）。
- 兼容旧库回填的证据（frame_path 为旧 `derived/frames/...`）：读取时若新路径不存在可回退旧路径或直接以 locator 存的路径为准（以 locator 存的为准最简单——历史证据存的就是它当时的路径）。**重点是不要再删除历史 run 的帧**。

## MAJOR 2：历史证据按 id 访问被强制最新 run 而 404（`backend/app/services/result_service.py:218 get_evidence_with_access`）
按**证据 id（主键）**访问 detail/source/frame 时，当前在 `run_id=None` 下解析为「最新 run」并要求 `evidence.run_id == 最新`，历史证据必 404；`evidence_source` 的 `frame_url` 也不带 run。
**修复（按 id 访问改为 run 无关）**：`get_evidence_with_access` 仅做：①按 id 取证据；②校验调用者对 `evidence.task_id` 有访问权；③**仅当显式传入 run_id 且与 `evidence.run_id` 不一致时**才 404；`run_id=None` 时直接返回该证据（它本身就是某个具体 run 的证据，主键查询无需再限定 run）。这样 source 的 `frame_url`（不带 run）也能正确取到历史帧。LIST 端点仍按 run 过滤（不改）。

## MAJOR 3：完成校验用 `.first()` 取结果而非最新（`backend/app/services/task_service.py` 约 115）
任务「标记完成」的引用门禁仍 `db.query(AnalysisResult).filter(task_id==).first()`，多结果下可能取到旧 run 的 citation_check。
**修复**：改用 `result_service.resolve_result(db, task.id)`（最新结果 + 一致排序）。补测试：两次运行后完成校验基于**最新** run 的 citation_check。

## 验证（实际执行，最终消息逐条报告）
1. `cd backend && ./.venv/bin/pytest -q` 全绿（含旧 schema 迁移重建、历史帧重跑后仍可取、按 id 访问历史证据、完成校验用最新 run）。
2. `./.venv/bin/python scripts/check_annotation_names.py` 通过。
3. `backend/.venv/bin/python scripts/evaluate_demo.py` 仍 3/3，coverage/invalid 不变。
4. `cd frontend && npm run type-check && npm run build` 通过（若动前端）。
报告：表重建迁移实现与测试、派生文件 run 隔离方案、按 id 访问语义修正、完成校验改用 resolve_result，各自验证结果。不要 git commit。
