# 复审（只读，禁止修改）：历史保留 FAIL 修复确认

上一轮审核 FAIL，已修 1 BLOCKER + 3 MAJOR。请**确认修复正确且未引入回归**，重点复现上轮问题场景验证已闭合。

## 必查项
1. **BLOCKER 表重建**（`backend/app/database.py` `_rebuild_analysis_results_without_legacy_unique` / `_analysis_results_has_unique_task_id_index`）：
   - 旧库（`analysis_results.task_id` 表内 UNIQUE）启动后，UNIQUE 是否真被移除、可插入同 task 第二条结果？数据是否完整保留（列交集复制无丢列）？
   - 新表是否带应有的非唯一索引（task_id index、run_id index）？
   - 幂等：新库/已迁移库重复启动不重建、不报错？迁移顺序（evidence 回填在重建前读旧表）是否仍正确？日志脱敏？非 SQLite 跳过？
2. **MAJOR 派生文件 run 隔离**（`video_parse.py` / `parse_service.py`）：帧/音频是否落到 `derived/runs/{run_id}/...`；重跑是否只清理当前 run 当前 file 的产物、不动历史 run；`_validate_frame_paths` 路径穿越校验是否仍有效（放宽根后不得允许逃逸任务 derived 目录）。
3. **MAJOR 按 id 访问 run 无关**（`result_service.get_evidence_with_access`）：`run_id=None` 时按主键返回该证据（校验 task 访问权）；显式错 run 仍 404；历史 source 的 `frame_url`→frame 链路是否可取历史帧。LIST 端点是否仍按 run 过滤。
4. **MAJOR 完成校验**（`task_service`）：是否改用 `resolve_result` 取最新结果的 citation_check。
5. **回归**：跨运行证据隔离（抽取/冲突/报告仅当前 run）、display_id 跨运行不冲突、删除任务级联物理删除——是否仍成立？demo 3/3、coverage/invalid 不变？
6. 是否有**新引入**问题（重建表丢索引/外键、frame 旧 locator 兼容、空 run 边界）。

## 输出
逐条确认「已闭合/未闭合」，每条给文件:行依据。新发现按 BLOCKER/MAJOR/MINOR/NIT 标注。末行总评 PASS / PASS-WITH-FIXES / FAIL。只报真实问题。
