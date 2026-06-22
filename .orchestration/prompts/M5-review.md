# 代码审核任务：EviTrace M5（测试、演示数据、评估、Docker、README）

你是独立审核员（只读，禁止修改）。审核 M5 是否符合 `SPEC.md`/`PLAN.md` 且**诚实、可复现、可部署**。

## 依据
- `SPEC.md` §14（演示数据/expected.json/对照）、§15（验收，尤其 §15.2）、§6.4 部署、§12 安全、NFR-001/002/003、§16。
- `PLAN.md` 第 7 章 M5-01~07、第 13 章交付清单。
- 代码/产物：`scripts/{build_demo_data,evaluate_demo,seed_admin}.py`、`demo_data/**`、`evaluation_result.md`、`docker-compose.yml`、`backend/{Dockerfile,docker-entrypoint.sh,.dockerignore}`、`frontend/{Dockerfile,nginx.conf,.dockerignore}`、`.dockerignore`、`README.md`、`backend/tests/**`。

## 必查项
1. **评估脚本诚实性（重点）**：`evaluate_demo.py` 是否真的跑**真实管线**（解析/证据/冲突规则/引用验证/报告），而非直接读 expected.json 充当结果？冲突召回、引用覆盖率、invalid 统计是否**真实计算**而非硬编码 1.0？是否存在“对着答案打分”的作弊（如把 expected 直接当 found）？是否用独立临时 DB/DATA_ROOT 不污染开发库？
2. **演示数据完整性**：三组 case 是否各含 brief.txt/report.(pdf|docx)/image.png/audio.wav/video.mp4/expected.json/README.md + sidecar(ocr/asr/video)/extraction.json；媒体是否能通过后端 magic 校验；冲突是否**跨模态**（植入冲突两侧分别来自不同模态证据）；expected.json 结构是否符合 §14.2；植入冲突类型与目录名一致（time/location/quantity）。
3. **MOCK 边界诚实性**：MOCK 是否只替代“模型提取 + OCR/ASR/视频解码”，其余为真实逻辑；report/citation 是否真实由引擎产生；是否在 README 明示 MOCK 的范围与真实模式切换。
4. **测试覆盖（M5-01/02）**：最低模块（文件/路径安全、证据编号、时间/地点/数量冲突、引用验证、权限依赖、MOCK 输出校验）是否都有单测；集成测试是否覆盖完整流程（两分析员 + B 不可访问 + 管理员可访问 + 冲突改状态 + 下载）；断言是否非脆弱。
5. **Docker 安全/正确性**：compose 是否数据卷持久化、healthcheck、restart、read_only/tmpfs 不破坏运行；后端镜像不含模型权重、只装运行期依赖；entrypoint 的 SECRET_KEY 自动生成是否安全（持久化、权限、不回显、弱值才生成）；是否泄露 secret/完整路径；`.dockerignore` 是否排除 venv/node_modules/data/.git/.env；nginx.conf 是否安全（SPA 回退、/api 反代、无 CDN、无目录遍历/敏感头泄露）；ENV 默认值与 SECRET_KEY 守卫是否自洽（生产拒绝弱密钥 vs 零配置可启动是否矛盾）。
6. **可恢复性 NFR-003**：重启后数据/报告保留；运行中断恢复（启动把 running 置 failed）是否在容器场景成立。
7. **README 准确性**：13 项是否齐全；命令是否与仓库一致（venv 路径、脚本名、端口 8080/8000、compose 命令）；是否有过时/错误指令；是否声明安全边界与已知限制；是否无 CDN/联网要求矛盾（NFR-001）。
8. 是否有 `.env`/secret/真实密钥被提交；是否引入被禁止依赖。

## 输出
每个发现：严重级别（BLOCKER/MAJOR/MINOR/NIT）、文件:行、问题、修复建议。最后一行总评 PASS/PASS-WITH-FIXES/FAIL + 交付前必修项。只报告真实问题，尤其警惕评估“作弊”与部署“假成功”。
