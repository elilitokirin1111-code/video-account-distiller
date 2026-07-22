# 技术设计文档

## 1. 架构原则

- Skill 负责编排与领域规则。
- Python 包负责确定性处理。
- 模型负责非确定性的语义与多模态标注。
- 原始数据只读保存。
- 标准化数据可重建。
- 报告中的每个结论可追溯。
- 所有模型输出必须通过 Pydantic Schema 校验。
- 脚本输出 JSON 到 stdout，日志写 stderr。
- 复杂参考资料放在 `references/`，主 `SKILL.md` 保持简洁。
- 网络采集与分析内核解耦。

## 2. 建议仓库结构

```text
video-account-distiller/
├── AGENTS.md
├── README.md
├── LICENSE
├── pyproject.toml
├── uv.lock
├── .gitignore
├── .env.example
├── skills/
│   └── video-account-distiller/
│       ├── SKILL.md
│       ├── references/
│       │   ├── workflow.md
│       │   ├── account-analysis.md
│       │   ├── video-analysis.md
│       │   ├── metrics.md
│       │   ├── sampling.md
│       │   ├── hook-taxonomy.md
│       │   ├── narrative-taxonomy.md
│       │   ├── comment-analysis.md
│       │   ├── pattern-evidence.md
│       │   ├── scoring-prediction.md
│       │   ├── report-contracts.md
│       │   ├── platform-douyin.md
│       │   ├── platform-xiaohongshu.md
│       │   ├── platform-wechat-channels.md
│       │   ├── platform-bilibili.md
│       │   ├── platform-tiktok.md
│       │   ├── platform-youtube.md
│       │   └── platform-instagram.md
│       ├── scripts/
│       │   ├── init-project.py
│       │   ├── import-data.py
│       │   ├── validate-data.py
│       │   ├── normalize-data.py
│       │   ├── calculate-metrics.py
│       │   ├── select-samples.py
│       │   ├── build-analysis-bundle.py
│       │   ├── parse-model-output.py
│       │   ├── discover-patterns.py
│       │   ├── score-content.py
│       │   ├── register-prediction.py
│       │   ├── register-publication.py
│       │   ├── run-retro.py
│       │   ├── generate-report.py
│       │   └── status.py
│       └── assets/
│           ├── templates/
│           ├── schemas/
│           └── prompts/
├── src/
│   └── video_account_distiller/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── errors.py
│       ├── models/
│       ├── adapters/
│       ├── ingestion/
│       ├── normalization/
│       ├── metrics/
│       ├── sampling/
│       ├── features/
│       ├── patterns/
│       ├── scoring/
│       ├── prediction/
│       ├── retro/
│       ├── reports/
│       ├── knowledge/
│       └── utils/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── golden/
│   └── fixtures/
├── docs/
│   ├── architecture.md
│   ├── data-contracts.md
│   ├── adapter-guide.md
│   ├── model-provider-guide.md
│   └── privacy-and-compliance.md
└── examples/
    ├── demo-douyin/
    ├── demo-youtube/
    └── demo-cross-platform/
```

## 3. 用户项目目录

Skill 初始化后，在用户的内容项目目录生成：

```text
content-research-project/
├── distiller.yaml
├── .distiller-state.json
├── .distiller-secrets.example
├── raw/
│   ├── accounts/
│   ├── videos/
│   ├── comments/
│   ├── transcripts/
│   ├── media/
│   └── imports/
├── normalized/
│   ├── accounts.parquet
│   ├── videos.parquet
│   ├── metric_snapshots.parquet
│   ├── comments.parquet
│   ├── transcripts.parquet
│   └── media_features.parquet
├── analyses/
│   ├── accounts/
│   ├── videos/
│   ├── comments/
│   └── comparisons/
├── knowledge-base/
│   ├── accounts/
│   ├── patterns/
│   ├── rules/
│   ├── experiments/
│   ├── reviews/
│   └── index.json
├── predictions/
├── publications/
├── reports/
├── runs/
│   └── <run-id>/
│       ├── manifest.json
│       ├── input-index.json
│       ├── output-index.json
│       ├── warnings.json
│       └── run.log
└── STATUS.md
```

## 4. 配置文件

`distiller.yaml` 建议：

```yaml
project:
  name: demo-project
  language: zh-CN
  timezone: Asia/Shanghai

analysis:
  default_sample_size: 40
  min_pattern_support: 3
  min_validated_rule_support: 10
  use_robust_zscore: true
  log_transform_metrics: true
  confidence_thresholds:
    low: 0.35
    medium: 0.60
    high: 0.80

platforms:
  enabled:
    - douyin
    - xiaohongshu
    - bilibili
    - tiktok
    - youtube
    - instagram
  cross_platform_raw_metric_comparison: false

models:
  text_provider: null
  vision_provider: null
  transcription_provider: null
  embedding_provider: null
  require_schema_validation: true

privacy:
  redact_usernames_in_reports: true
  store_raw_comments: true
  hash_comment_author_ids: true
  allow_cloud_model_upload: false

reports:
  formats:
    - markdown
    - json
  include_evidence_index: true
```

## 5. 核心组件

### 5.1 Adapter 层

统一接口：

```python
class PlatformAdapter(Protocol):
    platform: Platform

    def validate_source(self, source: SourceConfig) -> ValidationResult: ...
    def collect_accounts(self, source: SourceConfig) -> list[RawAccount]: ...
    def collect_videos(self, source: SourceConfig) -> list[RawVideo]: ...
    def collect_comments(self, source: SourceConfig) -> list[RawComment]: ...
    def collect_metric_snapshots(self, source: SourceConfig) -> list[RawMetricSnapshot]: ...
    def map_fields(self, raw_record: dict) -> NormalizedRecord: ...
```

首版 Adapter：

- `CsvAdapter`
- `JsonAdapter`
- `ManualAdapter`
- `TranscriptAdapter`
- `LocalMediaAdapter`

平台在线 Adapter 只提供接口和示例，不默认实现高风险抓取。

### 5.2 Ingestion 层

职责：

- 文件发现。
- 编码识别。
- 字段映射。
- 数据类型转换。
- 时间和时区处理。
- 原始文件哈希。
- 重复数据识别。
- 运行清单。

### 5.3 Normalization 层

职责：

- 平台字段映射。
- 单位统一。
- 缺失值处理。
- URL 和 ID 规范化。
- 账号快照与发布时间粉丝量区分。
- 指标来源和置信度记录。

### 5.4 Metrics 层

职责：

- 派生指标。
- 分位数。
- Robust Z-score。
- 内容支柱表现。
- 生命周期增长。
- 账号稳定性。
- 异常值提示。

### 5.5 Sampling 层

输出 `sample_manifest.json`：

```json
{
  "account_id": "acc_x",
  "strategy": "stratified",
  "population_size": 120,
  "selected_size": 40,
  "strata": {
    "performance": {"S": 5, "A": 8, "B": 15, "C": 7, "D": 5},
    "recency": {"recent": 12},
    "pillar_coverage": {"pillar_1": 15, "pillar_2": 13, "pillar_3": 12}
  },
  "selected_video_ids": []
}
```

### 5.6 Feature extraction 层

分为：

- 确定性特征：时长、发布时间、字幕字数、镜头数量等。
- 模型标注特征：Hook、内容支柱、叙事、情绪、CTA 等。
- 人工修订特征：允许覆盖模型结果，但保留修订记录。

### 5.7 Pattern 层

职责：

- 对标签做频次和表现对比。
- 发现特征组合。
- 生成候选 Pattern。
- 自动附带支持样本和反例。
- 计算证据强度。
- 提醒混杂因素。
- 将 Pattern 升级为 Rule，必须满足明确条件。

### 5.8 Scoring 层

输入：

- 账号上下文。
- 新选题或脚本。
- 当前 Rubric。
- 规则库。

输出：

- 分项评分。
- 证据。
- 改进建议。
- 风险。
- 预测输入特征。

### 5.9 Prediction 层

预测必须不可变记录：

```text
prediction_id
content_id
created_at
account_id
target_metrics
predicted_quantiles
confidence
assumptions
rubric_version
rule_versions
input_hash
```

发布后不能修改原预测，只能创建校准记录。

### 5.10 Retro 层

职责：

- 读取实际快照。
- 选择评价时间点。
- 计算误差。
- 解释异常。
- 更新 Pattern 支持和反例。
- 生成权重调整建议。
- 不自动大幅修改 Rubric，默认要求人工确认。

### 5.11 Report 层

每次报告同时输出：

- `report.md`
- `report.json`
- `evidence-index.json`
- `warnings.json`

## 6. 模型调用设计

### 6.1 Provider 抽象

```python
class TextModelProvider(Protocol):
    def generate_structured(
        self,
        prompt: str,
        response_model: type[BaseModel],
        *,
        temperature: float = 0.0,
    ) -> BaseModel: ...
```

多模态、转写和 Embedding 使用类似接口。

### 6.2 模型任务拆分

不要一个 Prompt 完成整个账号分析。建议分步：

1. 单条视频事实抽取。
2. 单条视频语义标注。
3. 评论意图抽取。
4. 账号内容聚类命名。
5. 模式候选解释。
6. 账号级报告生成。
7. 规则审查。
8. 反例审查。

### 6.3 防止事后合理化

模型 Prompt 必须：

- 先读取内容，不读取表现数据，生成内容特征。
- 再将内容特征与表现数据结合。
- 强制输出反例。
- 强制标记未知。
- 禁止使用“因为播放高所以 Hook 好”之类循环解释。
- 对低样本明确降置信度。

## 7. CLI 设计

建议入口：

```bash
distiller init
distiller import accounts --file accounts.csv --platform douyin
distiller import videos --file videos.csv --platform douyin
distiller import comments --file comments.csv --platform douyin
distiller validate
distiller normalize
distiller metrics --account <id>
distiller sample --account <id> --size 40
distiller analyze video --video <id>
distiller analyze account --account <id>
distiller compare --target <id> --benchmarks <id1,id2>
distiller distill --account <id>
distiller score --account <id> --script script.md
distiller predict --account <id> --script script.md
distiller publish --prediction <id> --url <url>
distiller retro --publication <id> --snapshot t3d
distiller report --account <id> --format markdown
distiller status
```

所有命令支持：

- `--json`
- `--run-id`
- `--dry-run`
- `--config`
- `--verbose`

## 8. 错误处理

定义稳定错误码：

- `E_INPUT_MISSING`
- `E_SCHEMA_INVALID`
- `E_FIELD_MAPPING_REQUIRED`
- `E_DUPLICATE_RECORD`
- `E_PLATFORM_UNSUPPORTED`
- `E_ADAPTER_AUTH`
- `E_RATE_LIMIT`
- `E_MEDIA_DECODE`
- `E_MODEL_UNAVAILABLE`
- `E_MODEL_SCHEMA_INVALID`
- `E_INSUFFICIENT_SAMPLE`
- `E_REPORT_GENERATION`

错误结果也使用 JSON Schema。

## 9. 可观测性

每次运行记录：

- run ID。
- 输入哈希。
- 配置哈希。
- 代码版本。
- Skill 版本。
- 模型提供商和模型名。
- Prompt 版本。
- 开始与结束时间。
- 处理条数。
- 警告。
- 错误。
- 输出文件。

## 10. 数据安全

- `.distiller-secrets` 永不提交。
- API Key 只从环境变量或安全配置读取。
- 评论作者 ID 默认哈希。
- 报告默认不展示完整用户标识。
- 上传云模型前检查配置授权。
- 原始媒体文件不自动上传。
- 支持 `--local-only`。
- 日志不打印凭证。
- 删除任务必须显式确认。
- 不提供绕过平台限制的实现。

## 11. 性能目标

P0：

- 10 万条视频指标可在本地完成标准化和基础指标计算。
- 1 万条评论可批处理。
- 深度模型分析按样本执行，不默认全量烧模型。
- 所有中间结果缓存。
- 输入未变化时允许跳过重复分析。

## 12. 版本和迁移

- Skill 版本和数据 Schema 版本分离。
- 每个 Parquet/JSON 输出包含 `schema_version`。
- 提供迁移脚本。
- 规则库记录生成版本。
- Prompt 模板有独立版本。
