# Video Account Distiller

`video-account-distiller` 是一个离线优先的 Agent Skill 与 Python 数据工具，用于导入、标准化、
查询和评估抖音、小红书、视频号、Bilibili、TikTok、YouTube 与 Instagram Reels 的账号导出数据。

当前版本完成规划中的 Phase 0 和 Phase 1：先把可追溯的数据内核做正确，再在后续阶段增加采样、
视频语义拆解、账号蒸馏、预测与复盘。它不会登录或抓取任何真实平台。

## 能做什么

- 初始化结构统一、可恢复的本地研究项目。
- 导入 CSV、JSON、JSONL，并支持平台别名和自定义字段映射。
- 原样保存输入文件，生成 SHA-256，校验原始数据完整性。
- 使用严格 Pydantic 模型校验 Account、Video、MetricSnapshot、Comment 等数据。
- 对文件内及多次导入的数据进行稳定去重。
- 输出标准化 Parquet，并提供只读 DuckDB 查询层。
- 计算互动率、完播效率、Median、MAD、Robust Z-score、账号相对表现和 S/A/B/C/D 分层。
- 输出 JSON/Markdown 数据质量报告、不可变运行清单和项目状态。
- 通过稳定错误码和 JSON Envelope 被 Agent 或自动化脚本调用。

## 安装

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。仓库默认开发版本为 Python 3.14，
并在 CI 中验证 Python 3.11。

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

`status` 会列出标准化后的账号 ID。使用该 ID 计算账号内表现：

```bash
uv run distiller metrics --project ./demo-project \
  --account acc_0776e1a4f82e23c02045 --json
```

### 4. 使用 DuckDB 查询

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
├── reports/
├── runs/<run-id>/        # manifest 与质量报告
├── knowledge-base/       # 后续 Phase 使用
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

支持离线项目、CSV/JSON/JSONL、七个平台的字段映射模板、Parquet、DuckDB、基础派生指标和
账号内稳健分层。

尚未实现：真实平台抓取、代表性采样、字幕与视频语义分析、评论意图、模式发现、账号报告、
内容评分、预测、发布复盘、多模态以及团队协作 Adapter。详见
[`docs/delivery-overview.md`](docs/delivery-overview.md)。

## 安全限制

- 不访问真实平台，不绕过登录、验证码、风控、速率限制或服务条款。
- 不把不同平台的原始播放量直接比较。
- 不将缺失值写成 0。
- 不提交原始用户数据、密钥、项目状态或本地缓存。
- 评论作者标识在标准化表中只保存哈希。

## 测试与质量门

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

测试强制禁用网络，并覆盖单元、合同、集成和 Golden 场景。生成 10 万条离线 Fixture：

```bash
uv run python tools/generate_large_fixture.py --output ./tmp/large-fixture --rows 100000
```

## 文档索引

- [交付介绍](docs/delivery-overview.md)
- [架构](docs/architecture.md)
- [数据合同](docs/data-contracts.md)
- [Adapter 指南](docs/adapter-guide.md)
- [隐私与合规](docs/privacy-and-compliance.md)
- [开发与测试](docs/development.md)
- [实施取舍](docs/implementation-decisions.md)
- [版本与后续更新说明](docs/release-notes.md)
- [原始规划](docs/planning/)
