# Screenshots — 答辩截图采集指南

本目录存放课程答辩用截图。这些是**实时界面截图**，最好用你自己的演示数据现场采集（30 秒即可，见下）。占位文件名被 README/实验报告引用，请按同名保存。

## 采集前置（30 秒起一套演示）

```bash
docker compose up -d --build      # 或本地：后端 uvicorn :8088 + 前端 npm run dev
```

打开 `http://localhost:8080`，用演示账号 `admin / admin123456` 登录。

> 建议浏览器窗口 1440×900 左右，缩放 100%，浅色主题；截图前等页面加载完成、顶部「运行模式」徽章出现。

## 需要的截图（按文件名保存到本目录）

| 文件名 | 界面 | 采集路径 |
|---|---|---|
| `login.png` | 登录页 | 打开 `http://localhost:8080`，未登录状态。 |
| `task-list.png` | 任务列表 | 登录后任务列表页（顶部应可见**运行模式徽章**：演示Fixture/混合/本地真实）。 |
| `workbench-timeline.png` | 工作台·时间线 | 新建任务 → 上传 `demo_data/case_01_time_conflict/` 下的 `brief.txt`/`report.pdf`/`image.png`/`audio.wav`/`video.mp4` → 点「开始分析」→ 进度跑到 `awaiting_review` → 切到「时间线」面板。 |
| `workbench-conflicts.png` | 工作台·冲突 | 同一任务切到「冲突」面板，展示检出的时间冲突（14:00 ↔ 16:30）及左右两侧各自的证据引用。 |
| `evidence-drawer.png` | 证据卡片/定位 | 点任一 `[E-xxxx]` 引用或证据卡，展开证据详情（含来源文件、定位：页/时间点/帧/bbox）。体现「结论→证据定位→原始资料」链路。 |
| `report-citations.png` | 报告·引用 | 切到「报告」面板，展示带 `[E-xxxx]` 引用的 Markdown 报告，顶部含「运行模式」元数据行。 |
| `evaluation-result.png` | 评估结果 | 终端运行 `python scripts/evaluate_demo.py` 后的输出，或打开生成的 `evaluation_result.md`（3/3、覆盖率 1.00、无效引用 0）。可选：`python scripts/evaluate_ab.py` 的 A/B 对照表。 |

## 建议补充（可选，增强完整度）

- `run-history.png`：工作台顶部「分析版本」下拉——同一任务多次运行后可切换查看历史 run（重跑保留历史；已实现，见 §十一）。
- `run-mode-badge.png`：顶栏运行模式徽章。演示=「演示Fixture」；配齐真实模型=「全真实链路」；部分真实=「混合模式」。鼠标悬停 tooltip 显示每个组件的「模型 · 本地/远程」（如 `LLM: deepseek-v4-flash · 远程`）——可佐证 §7.4 的云端/本机部署区分。
- `admin-skills.png`：管理页 Skill 启停 + 健康状态。
- `admin-audit.png`：管理页审计日志。

> 采集方式：本环境无可驱动的浏览器自动化（未连接 Chrome 扩展；computer-use 对浏览器为只读），因此截图为人工采集——按上面 30 秒流程跑一遍，逐个面板截图即可（约 2 分钟）。如需展示「全真实链路」徽章，先按 `docs/DEPLOYMENT.md` 配好云 LLM/VLM + 本机 OCR/ASR 再登录采集。

## 说明

- 三个案例任选其一即可（`case_01` 时间冲突 / `case_02` 地点冲突 / `case_03` 数量冲突）；想全面展示可各截一张冲突图。
- 截图均为演示 Fixture 模式即可清晰呈现产品形态；如需展示真实模型链路，按 `docs/DEPLOYMENT.md` 配好真实 LLM/VLM/OCR/ASR 后再采集，徽章会显示「本地真实/混合」。
