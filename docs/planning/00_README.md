# Video Account Distiller 规划包

项目建议名称：`video-account-distiller`

中文名称：视频账号拆解与蒸馏 Skill

## 1. 这个项目解决什么问题

把短视频账号分析从“人工看几条视频后凭经验总结”，升级为可重复、可验证、可积累的分析工作流：

1. 导入一个或多个账号及其视频数据。
2. 统一不同平台的数据口径。
3. 自动选择有代表性的样本，而不是只看爆款。
4. 对账号、单条视频、评论区和用户需求进行结构化拆解。
5. 把规律分成“事实、相关性、假设、验证规则”，避免把偶然爆款误判成方法论。
6. 形成账号蒸馏档案、爆款模式库、内容评分表和可执行创作 Playbook。
7. 对新选题或脚本进行发布前评分和预测。
8. 发布后回收数据，通过复盘更新规则和权重。

## 2. 交给 Codex 的内容

本压缩包包含：

- `01_PRODUCT_SPEC.md`：产品需求、用户场景和范围边界。
- `02_ANALYSIS_FRAMEWORK.md`：账号蒸馏、视频拆解、数据分析的方法论。
- `03_TECHNICAL_DESIGN.md`：Skill 架构、模块设计、脚本接口和工程约束。
- `04_DATA_SCHEMA.md`：核心数据表、字段和计算口径。
- `05_SKILL_BLUEPRINT.md`：根 Skill、子 Skill、参考文件与命令触发设计。
- `06_TEST_AND_ACCEPTANCE.md`：测试计划、验收标准和质量门槛。
- `07_MILESTONE_PLAN.md`：分阶段实施计划和优先级。
- `08_CODEX_MASTER_PROMPT.md`：可直接提交给 Codex 的主任务提示词。
- `AGENTS.md.template`：建议放入仓库根目录的 Codex 工程规则模板。

## 3. 首版建议范围

首版不要直接实现所有平台在线抓取。先把“分析内核”做正确：

- 支持 CSV、JSON、字幕文件和本地视频元数据导入。
- 提供平台 Adapter 接口。
- 内置 Douyin、Xiaohongshu、Bilibili、TikTok、YouTube、Instagram Reels、视频号的数据字段映射模板。
- 在线采集作为可插拔 Adapter，必须遵守平台规则、授权范围和速率限制。
- 所有核心分析都可在离线 Fixture 数据上测试。

## 4. 建议技术栈

- Python 3.11+
- Typer：CLI
- Pydantic：输入输出模型
- DuckDB：分析与本地查询
- Parquet：标准化数据存储
- Pandas 或 Polars：表格处理
- SQLite：规则、任务和运行状态
- Jinja2：Markdown/HTML 报告模板
- pytest：测试
- Ruff + mypy：静态检查
- 可选：Whisper 兼容接口、FFmpeg、OpenCV、场景切分模型、Embedding 服务

## 5. Codex 开始执行前

把整个规划包放入新仓库的 `docs/planning/`，把 `AGENTS.md.template` 复制为仓库根目录的 `AGENTS.md`，然后将 `08_CODEX_MASTER_PROMPT.md` 作为 Codex 的首个任务输入。
