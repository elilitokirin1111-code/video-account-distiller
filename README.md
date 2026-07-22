# Video Account Distiller

`video-account-distiller` 是一个离线优先的 Agent Skill 与 Python 数据工具，用于导入、标准化、
查询、分层采样、体检和文本级拆解抖音、小红书、视频号、Bilibili、TikTok、YouTube 与
Instagram Reels 的账号导出数据、字幕和评论，并沉淀可复用的 Pattern 与对标实验。

当前版本 `0.5.0` 完成规划中的 Phase 0～Phase 5：在数据内核、账号体检、单视频盲分析和
账号蒸馏之上，增加可解释脚本评分、不可变预测、发布登记、预测误差复盘以及待审批的规则/
Rubric 变更建议。它不会登录或抓取真实平台。

## 能做什么

- 初始化结构统一、可恢复的本地研究项目。
- 导入 CSV、JSON、JSONL，并支持平台别名和自定义字段映射。
- 原样保存输入文件，生成 SHA-256，校验原始数据完整性。
- 使用严格 Pydantic 模型校验 Account、Video、MetricSnapshot、Comment 等数据。
- 对文件内及多次导入的数据进行稳定去重。
- 输出标准化 Parquet，并提供只读 DuckDB 查询层。
- 计算互动率、完播效率、Median、MAD、Robust Z-score、账号相对表现和 S/A/B/C/D 分层。
- 按表现、近期、内容类型、时长、投流和异常值选择可解释的代表性样本。
- 输出账号基础统计、高中低表现对照和内容寻址的样本清单。
- 同时生成账号体检 JSON、Markdown、证据索引和警告文件。
- 导入 SRT、VTT、TXT、JSON/JSONL 字幕并输出标准化 `transcripts.parquet`。
- 在隐藏表现数据的前提下抽取事实和语义标签，再后置合并账号内表现背景。
- 模型结果严格校验、自动重试；不可用时输出可见的低置信度降级结果。
- 输出单视频 JSON/Markdown、独立盲分析、字幕/指标证据索引和警告。
- 在评论分析副本中脱敏电话、邮箱、网址、账号和联系方式，不修改原始评论。
- 输出评论意图、痛点、异议、购买意图、内容机会和带偏差提醒的需求聚类。
- 将内容簇与账号内表现分层对照，生成同时包含支持样本和反例的可追溯 Pattern。
- 输出账号定位观察、优势/短板、可复制/不可复制因素、行动建议和 30 天实验草案。
- 为目标账号与对标账号生成迁移矩阵，并保持不同平台和账号基线独立。
- 使用九维 Rubric 给脚本打分，展示每个分项、必改项、风险及低成熟度规则的有限影响。
- 以同账号历史分布生成 P25/P50/P75 预测区间，记录假设、置信度、版本和不可变输入哈希。
- 将预测与已导入的视频发布记录关联，规划 T+1h/T+24h/T+3d/T+7d 数据快照。
- 对实际快照计算预测误差，保留规则支持和反例，并生成待审批变更与下一轮实验。
- 输出 JSON/Markdown 数据质量报告、不可变运行清单和项目状态。
- 通过稳定错误码和 JSON Envelope 被 Agent 或自动化脚本调用。

## 安装

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。仓库默认开发版本为 Python 3.14，
并在 CI 中验证 Python 3.11 和 3.14。

```bash
git clone https://github.com/elilitokirin1111-code/video-account-distiller.git
cd video-account-distiller
uv sync
uv run distiller --help
```

如果在 Windows 的中文路径中使用 Python 3.11，且 editable 安装未能加载，可使用：

```powershell
uv sync --no-editable
```

## Quick Start

### 1. 初始化项目

```bash
uv run distiller init ./demo-project --json
```

### 2. 导入离线导出数据

```bash
uv run distiller import accounts --project ./demo-project \
  --file ./tests/fixtures/normal/accounts.csv --platform douyin --json

uv run distiller import videos --project ./demo-project \
  --file ./tests/fixtures/normal/videos.csv --platform douyin --json

uv run distiller import metrics --project ./demo-project \
  --file ./tests/fixtures/normal/metrics.csv --platform douyin --json

uv run distiller import comments --project ./demo-project \
  --file ./tests/fixtures/normal/comments.json --platform douyin --json
```

PowerShell 中可将行尾 `\` 改为反引号，或将每条命令写在一行。

### 3. 校验并标准化

```bash
uv run distiller validate --project ./demo-project --json
uv run distiller normalize --project ./demo-project --json
uv run distiller status --project ./demo-project --json
```

`status` 会列出标准化后的账号 ID，并在 `videos.recent` 中给出最近 20 条视频的内部
`video_id` 与平台编号；`truncated` 表示是否还有未展示的视频。使用账号 ID 计算账号内表现：

```bash
uv run distiller metrics --project ./demo-project \
  --account acc_0776e1a4f82e23c02045 --json
```

### 4. 分层采样并生成账号体检

```bash
uv run distiller sample --project ./demo-project \
  --account acc_0776e1a4f82e23c02045 --size 40 --json

uv run distiller report --project ./demo-project \
  --account acc_0776e1a4f82e23c02045 --sample-size 40 --json
```

报告目录同时包含 `report.json`、`report.md`、`evidence-index.json` 和 `warnings.json`。
每个统计项和报告发现都能通过 `evi_*` 追溯到标准化记录、原始哈希和来源运行。

### 5. 导入字幕并拆解单条视频

```bash
uv run distiller import transcripts --project ./demo-project \
  --video video-001 \
  --file ./subtitle.srt --language zh-CN --json

uv run distiller normalize --project ./demo-project --json

uv run distiller analyze video --project ./demo-project \
  --video video-001 \
  --model-output ./structured-output.json --json

uv run distiller validate --project ./demo-project --json
```

`--model-output` 是离线结构化模型结果文件；省略时会使用保守的本地降级分析。需要完整
模型结果时可追加 `--strict-model`。当前版本不会向任何模型服务上传字幕。
`--video` 可填写内部 `vid_*`，也可填写项目内唯一的平台视频编号。最后一次 `validate`
会同时检查分析文件 Schema、盲分析是否混入表现字段、模型输出哈希和证据引用。

### 6. 分析评论并蒸馏账号

```bash
uv run distiller analyze comments --project ./demo-project \
  --account acc_0776e1a4f82e23c02045 --json

uv run distiller distill --project ./demo-project \
  --account acc_0776e1a4f82e23c02045 --json

uv run distiller validate --project ./demo-project --json
```

评论分析只使用脱敏副本，报告不会包含作者原始标识。Phase 4 Pattern 只会标记为观察或
统计关联，不会自动升级为“验证规则”。每个 Pattern 都保存支持视频、反例、混杂因素和证据。

完成目标账号和对标账号的蒸馏后，可以生成迁移矩阵：

```bash
uv run distiller compare --project ./demo-project \
  --target acc_target --benchmarks acc_benchmark_1,acc_benchmark_2 --json
```

### 7. 评分、预测、登记发布和复盘

先准备 UTF-8 脚本文件，并确保目标账号已经完成 `distill`：

```bash
uv run distiller score --project ./demo-project \
  --account acc_target --script ./hotel-script.md --target-pillar room --json

uv run distiller predict --project ./demo-project \
  --account acc_target --script ./hotel-script.md --target-pillar room \
  --target-age-hours 72 --json
```

`score` 只做发布前检查，不写预测；`predict` 保存同账号历史分布下的不可变区间。视频发布并
通过现有 Adapter 导入、标准化后，登记预测关联。标准化视频的发布时间必须晚于预测创建
时间，显式传入的发布时间也不能与标准化记录冲突：

```bash
uv run distiller publish --project ./demo-project \
  --prediction pred_xxx --video vid_xxx --json

# 导入后续指标快照，再 normalize 和 metrics
uv run distiller retro --project ./demo-project \
  --publication pub_xxx --snapshot t3d --json
```

复盘不会覆盖原预测，也不会自动批准 Rule 或 Rubric 变更；所有建议均保持 `pending`。
如果实际快照时间明显偏离目标，或属于投流/Robust 异常值，系统仍保留结果供观察，但会将
匹配规则标记为“证据不足”，并禁止据此生成 Rule/Rubric 变更建议。

### 8. 使用 DuckDB 查询

```python
from pathlib import Path

from video_account_distiller.storage.duckdb_store import DuckDBStore

with DuckDBStore(Path("demo-project/normalized")) as store:
    rows = store.query(
        "SELECT video_id, performance_band, performance_score "
        "FROM derived_metrics ORDER BY performance_score DESC"
    )
```

查询层只允许 `SELECT` 和 `WITH`，避免修改标准化数据。

## 示例输入

视频 CSV 使用规范字段时无需额外映射：

```csv
platform_video_id,account_id,title,published_at,duration_seconds
video-001,account-001,酒店早餐介绍,2026-07-20T09:00:00+08:00,30
```

非标准字段使用 `--mapping mapping.yaml`。完整格式见
[`docs/adapter-guide.md`](docs/adapter-guide.md)。

## 项目目录

```text
demo-project/
├── distiller.yaml
├── .distiller-state.json
├── raw/imports/          # 原始文件，只读保留
├── staging/              # 映射并校验后的 JSONL
├── normalized/           # 标准化 Parquet
├── analyses/accounts/    # 内容寻址的分层样本清单
├── analyses/videos/      # 盲分析、单视频报告、证据索引和警告
├── analyses/comments/    # 评论信号、需求聚类、证据索引和警告
├── reports/accounts/     # 账号体检与账号蒸馏报告
├── reports/comparisons/  # 对标迁移矩阵
├── candidates/           # 内容寻址的脚本候选记录
├── reports/scoring/      # 九维评分、证据和警告
├── predictions/          # 不可变 P25/P50/P75 预测
├── publications/         # 预测与实际视频发布关联
├── reports/retros/       # 预测误差、规则反例和下一轮实验
├── runs/<run-id>/        # manifest 与质量报告
├── knowledge-base/       # 账号画像、Pattern、Rule、Rubric、实验和复盘
└── STATUS.md
```

## Agent Skill

标准 Skill 位于 `skills/video-account-distiller/`。可以复制或链接到：

- 仓库级：`.codex/skills/video-account-distiller/`
- 用户级：`~/.codex/skills/video-account-distiller/`

安装示例：

```bash
uv run python skills/video-account-distiller/scripts/install-skill.py \
  install --mode copy --destination ~/.codex/skills
```

安装脚本不会静默覆盖已有 Skill。验证方式见
[`docs/development.md`](docs/development.md)。

## 当前支持范围

支持离线项目、CSV/JSON/JSONL、SRT/VTT/TXT 字幕、七个平台字段映射、Parquet、DuckDB、
稳健指标、代表性采样、账号体检、单视频文本拆解、评论需求分析、Pattern/反例、账号蒸馏、
对标迁移矩阵、脚本评分、不可变区间预测、发布登记和快照复盘。

尚未实现：真实平台抓取、自动批准 Level 4 规则、画面/声音多模态以及团队协作 Adapter。
Phase 5 只生成待审批的规则升级建议；详见
[`docs/delivery-overview.md`](docs/delivery-overview.md)。

## 安全限制

- 不访问真实平台，不绕过登录、验证码、风控、速率限制或服务条款。
- 不把不同平台的原始播放量直接比较。
- 不将缺失值写成 0。
- 不提交原始用户数据、密钥、项目状态或本地缓存。
- 评论作者标识在标准化表中只保存哈希。
- 当前不包含网络模型 Provider；字幕和评论可能含敏感信息，分享报告前需人工检查。

## 测试与质量门

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
uv build
```

测试强制禁用网络，并覆盖单元、合同、集成和 Golden 场景。生成 10 万条离线 Fixture：

```bash
uv run python tools/generate_large_fixture.py --output ./tmp/large-fixture --rows 100000
```

## 文档索引

- [交付介绍](docs/delivery-overview.md)
- [架构](docs/architecture.md)
- [数据合同](docs/data-contracts.md)
- [分层采样与账号体检](docs/sampling-and-reporting.md)
- [字幕与盲分析](docs/text-video-analysis.md)
- [评论、Pattern 与账号蒸馏](docs/comment-and-account-distillation.md)
- [评分、预测、发布与复盘](docs/scoring-prediction-retro.md)
- [模型 Provider 指南](docs/model-provider-guide.md)
- [Adapter 指南](docs/adapter-guide.md)
- [隐私与合规](docs/privacy-and-compliance.md)
- [开发与测试](docs/development.md)
- [实施取舍](docs/implementation-decisions.md)
- [版本与后续更新说明](docs/release-notes.md)
- [原始规划](docs/planning/)
