# Codex 主任务提示词

你需要在当前空仓库中创建一个生产级 Agent Skill 项目：`video-account-distiller`。

## 一、目标

该项目用于对抖音、小红书、视频号、Bilibili、TikTok、YouTube 和 Instagram Reels 等平台的视频账号进行：

- 数据导入和标准化。
- 账号表现分析。
- 单视频结构化拆解。
- 评论区需求分析。
- 内容模式发现。
- 对标账号蒸馏。
- 内容评分。
- 发布前预测。
- 发布后复盘。
- 规则与知识库迭代。

不要把它做成一个只有 Prompt 的 Skill。需要同时提供：

1. 符合 Agent Skills 开放格式的 `SKILL.md`。
2. 可测试的 Python 分析包。
3. CLI。
4. 数据 Schema。
5. 报告模板。
6. 离线 Fixture。
7. 单元、合同、集成和 Golden 测试。
8. 完整文档。

## 二、先阅读

开始编码前，按顺序阅读：

- `docs/planning/00_README.md`
- `docs/planning/01_PRODUCT_SPEC.md`
- `docs/planning/02_ANALYSIS_FRAMEWORK.md`
- `docs/planning/03_TECHNICAL_DESIGN.md`
- `docs/planning/04_DATA_SCHEMA.md`
- `docs/planning/05_SKILL_BLUEPRINT.md`
- `docs/planning/06_TEST_AND_ACCEPTANCE.md`
- `docs/planning/07_MILESTONE_PLAN.md`
- 根目录 `AGENTS.md`

这些文件是项目的产品和技术真源。出现冲突时，以更具体的文档为准，并在实现记录中说明取舍。

## 三、本次只实现 Phase 0 和 Phase 1

本次范围：

### Phase 0

- 创建标准仓库结构。
- 配置 Python 3.11+。
- 使用 `uv` 管理依赖。
- 使用 Typer、Pydantic、DuckDB、PyArrow、Jinja2、pytest、Ruff、mypy。
- 创建 `video-account-distiller` Skill 骨架。
- 创建 CLI。
- 创建 CI。
- 创建文档。
- 创建安装和验证说明。

### Phase 1

- 项目初始化。
- CSV 和 JSON 导入。
- 账号、视频、指标快照和评论的数据模型。
- 原始输入只读保存与 SHA-256 哈希。
- 字段映射。
- 数据校验。
- 去重。
- 标准化 Parquet。
- DuckDB 查询层。
- 基础派生指标。
- Robust Z-score 和表现分层。
- 数据质量标志。
- `distiller status`。
- JSON 和 Markdown 数据质量报告。
- 完整测试。

不要实现真实平台抓取。只实现 Adapter 接口、CSV/JSON Adapter 和平台映射模板。

## 四、工程规则

- 先建立计划，再修改文件。
- 小步提交。
- 所有公共函数有类型标注。
- Pydantic 模型禁止静默丢弃未知关键字段。
- 未知值使用 `None`，不得用 0 代替。
- 原始数据不可修改。
- 脚本机器输出写 stdout，日志写 stderr。
- CLI 失败返回非 0 code 和稳定错误码。
- 所有写操作尽量幂等。
- API Key 和凭证不得进入日志或 Git。
- 测试不得依赖真实网络。
- 关键公式必须有单元测试。
- 所有报告都包含 run ID、输入哈希、Schema 版本和警告。
- 不要将不同平台的原始播放量直接比较。
- 不要实现绕过登录、验证码、风控或平台限制的代码。

## 五、Skill 规则

创建：

```text
skills/video-account-distiller/
├── SKILL.md
├── references/
├── scripts/
└── assets/
```

要求：

- `name` 必须为 `video-account-distiller`。
- description 中包含中英文触发场景。
- 主 `SKILL.md` 少于 500 行。
- 详细方法放到 `references/`。
- 脚本通过 Python 包或 CLI 调用，不复制业务逻辑。
- 所有引用路径有效。
- 提供验证命令。
- 可安装到 `.codex/skills/` 或 `~/.codex/skills/`。

## 六、CLI 最低要求

```bash
distiller init <project-dir>
distiller import accounts --project <dir> --file <path> --platform <platform>
distiller import videos --project <dir> --file <path> --platform <platform>
distiller import metrics --project <dir> --file <path> --platform <platform>
distiller import comments --project <dir> --file <path> --platform <platform>
distiller validate --project <dir>
distiller normalize --project <dir>
distiller metrics --project <dir> --account <account-id>
distiller status --project <dir>
```

每个命令必须支持：

- `--help`
- `--json`
- 明确错误码
- 合理日志

## 七、数据模型

严格参考 `04_DATA_SCHEMA.md`。本阶段至少实现：

- Account
- AccountSnapshot
- Video
- MetricSnapshot
- DerivedMetrics
- Comment
- RunManifest
- DataQualityIssue
- FieldMapping

所有输出包含 `schema_version`。

## 八、指标

至少实现并测试：

- like rate by views
- comment rate by views
- share rate by views
- save rate by views
- engagement rate by views
- engagement rate by followers
- completion efficiency
- log1p metric
- median
- MAD
- Robust Z-score
- performance band

分母为 0 或缺失时返回 `None`。

## 九、Fixture

创建至少三个数据集：

1. 正常单账号数据。
2. 缺失字段和异常值数据。
3. 跨平台数据。

包含：

- 高表现、中位和低表现。
- 投流标记。
- 当前粉丝数与发布时间粉丝量区别。
- 重复记录。
- 时间格式差异。
- 缺失分享和收藏。
- 负数或非法指标，用于校验测试。

## 十、测试

必须通过：

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

目标：

- 核心模块覆盖率不低于 80%。
- 测试不访问网络。
- 临时项目目录由 pytest fixture 创建。
- 测试原始数据不可变。
- 测试重复导入幂等。
- 测试 null 与 0 的区别。
- 测试平台不可比警告。
- 测试错误码。
- 测试 CLI JSON 输出。

## 十一、交付文档

创建：

- `README.md`
- `docs/architecture.md`
- `docs/data-contracts.md`
- `docs/adapter-guide.md`
- `docs/privacy-and-compliance.md`
- `docs/development.md`

README 包含：

- 项目定位。
- 安装。
- Quick Start。
- 示例输入。
- 示例命令。
- 项目目录。
- 当前支持范围。
- 限制。
- 测试命令。
- Skill 安装说明。

## 十二、完成时输出

完成后：

1. 运行全部检查。
2. 展示测试结果。
3. 展示仓库树。
4. 展示关键 CLI 示例。
5. 总结实现内容。
6. 明确未实现的后续 Phase。
7. 检查 Git 状态。
8. 提交所有更改，保持工作区干净。

发现规划中有无法实现或相互冲突的要求时，不要静默忽略。选择最安全、最容易测试的方案，并在 `docs/implementation-decisions.md` 记录原因。
