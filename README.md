# Video Account Distiller

`video-account-distiller` 是一个离线优先的 Agent Skill 与 Python 数据工具，用于导入、标准化、
查询、分层采样、体检和文本级拆解抖音、小红书、视频号、Bilibili、TikTok、YouTube 与
Instagram Reels 的账号导出数据、字幕和评论，并沉淀可复用的 Pattern 与对标实验。

正式版本 `1.0.0` 完成规划中的 Phase 0～Phase 7：在数据内核、账号体检、单视频盲分析、
账号蒸馏、发布复盘与本地多模态分析之上，增加带授权证明的导出导入、飞书多维表格与
Google Sheets 官方 API、批量任务、快照计划接口和团队配置。离线分析不会上传媒体。

当前主线同时提供 Phase 8 预发布能力：输入用户确认的抖音主页链接，默认通过 TikHub
文档化 API 读取最多 20 条近期公开作品，默认不采集评论，再复用已有的原始哈希、数据
校验、Parquet、DuckDB、Robust 指标、评论分析、账号体检和蒸馏链路。真实 API 调用必须
先预演并显式确认可能发生的费用。
可选的本地视频增强会从已留存、用户批准的 MediaCrawler 作品详情中解析公开视频源，
在本机完成下载、Whisper 中文转写、场景/关键帧/音频分析；可通过本机 Ollama 与
Qwen3-VL 增加画面、艺术字、品牌露出和 OCR，再重新蒸馏并保存可比较的账号画像。
MediaCrawler 保留为显式可选的本地、个人非商业学习研究 Provider；它会打开专用的可见
Chrome，登录和平台验证由用户手动完成。项目不调用代理池、隐身脚本、自动登录、验证码
处理或风控绕过。

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
- 使用本机 FFmpeg/FFprobe 分析 MP4、MOV、MKV 等媒体，生成镜头时间线与关键帧证据。
- 计算可追溯的音频响度、动态范围、静音/活动比例，并在无 FFmpeg 时明确降级。
- 通过回环地址上的 Ollama/Qwen3-VL 添加画面、构图、色彩、灯光、艺术字、动效痕迹、
  品牌露出和 OCR；默认保持未知且不上传媒体。
- 在评论分析副本中脱敏电话、邮箱、网址、账号和联系方式，不修改原始评论。
- 输出评论意图、痛点、异议、购买意图、内容机会和带偏差提醒的需求聚类。
- 将内容簇与账号内表现分层对照，生成同时包含支持样本和反例的可追溯 Pattern。
- 输出账号定位观察、优势/短板、可复制/不可复制因素、行动建议和 30 天实验草案。
- 为目标账号与对标账号生成迁移矩阵，并保持不同平台和账号基线独立。
- 按账号长期保存点赞、评论、分享、收藏、评论点赞和评论语义画像；后续蒸馏可直接做
  同平台排序，并明确排除平台不可见的播放量。
- 使用九维 Rubric 给脚本打分，展示每个分项、必改项、风险及低成熟度规则的有限影响。
- 以同账号历史分布生成 P25/P50/P75 预测区间，记录假设、置信度、版本和不可变输入哈希。
- 将预测与已导入的视频发布记录关联，规划 T+1h/T+24h/T+3d/T+7d 数据快照。
- 对实际快照计算预测误差，保留规则支持和反例，并生成待审批变更与下一轮实验。
- 验证授权导出清单、文件 SHA-256 和读写范围，再进入已有不可变导入链路。
- 通过可 Mock 的飞书多维表格和 Google Sheets 官方 API Adapter 双向同步表格数据。
- 对 429/5xx 有界退避，并将权限、限流和异常响应映射为稳定错误码。
- 运行可审计批量任务，输出快照到期计划，并维护不含凭证的团队角色配置。
- 输出 JSON/Markdown 数据质量报告、不可变运行清单和项目状态。
- 通过稳定错误码和 JSON Envelope 被 Agent 或自动化脚本调用。
- 从一个抖音主页链接有界采集近期作品，并一键生成账号报告和蒸馏结果。
- 显式启用后，从公开评论数最高的少量作品有界采集一级评论并进入脱敏需求分析。
- 默认 TikHub 调用先预演并显式确认费用；MediaCrawler 作为可选本地研究链路。
- 将完整 Provider 响应作为内容寻址的不可变原始证据。
- 从留存 Provider 证据中自动选择未分析视频，在不上传媒体的前提下完成本地中文转写、
  关键帧、镜头节奏、音频活跃度、单视频语义和账号重蒸馏。

## 安装

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。仓库默认开发版本为 Python 3.14，
并在 CI 中验证 Python 3.11 和 3.14。

```bash
git clone --recurse-submodules \
  https://github.com/elilitokirin1111-code/video-account-distiller.git
cd video-account-distiller
uv sync
uv run distiller --help
uv run distiller --version
uv run distiller doctor --json
```

默认 TikHub 主页采集只需在本机配置 `TIKHUB_API_KEY`。如需可选 MediaCrawler，再运行
`git submodule update --init --recursive`，并准备 Node.js 与 Chrome；本地视频增强还需要
FFmpeg/FFprobe 和 OpenAI Whisper CLI。
本地视觉还需要 Ollama 与一个视觉模型。`doctor` 会分别报告采集、本地媒体、转写、
本地视觉和账号视频增强能力。

Windows 可把 Ollama 程序和模型都放到 D 盘：

```powershell
[Environment]::SetEnvironmentVariable(
  "OLLAMA_MODELS", "D:\AI\Ollama\Models", "User"
)
.\OllamaSetup.exe /DIR="D:\AI\Ollama\App"
$env:OLLAMA_MODELS = "D:\AI\Ollama\Models"
& "D:\AI\Ollama\App\ollama.exe" pull qwen3-vl:8b
```

安装前应核验官方安装器签名。项目只允许连接
`http://127.0.0.1:11434`/`localhost:11434`，不会把关键帧发到远端视觉服务。

如果在 Windows 的中文路径中使用 Python 3.11，且 editable 安装未能加载，可使用：

```powershell
uv sync --no-editable
```

正式工作环境优先从 [GitHub Releases](https://github.com/elilitokirin1111-code/video-account-distiller/releases)
下载 wheel 和 `SHA256SUMS.txt`，校验后安装。完整步骤、环境自检和首次上线清单见
[`docs/production-release.md`](docs/production-release.md)。可选 MediaCrawler 主页采集依赖
带子模块的源码工作副本；第三方源码不会被根项目 wheel 重新打包。

## Quick Start

### 可视化自助应用（Windows）

完成 `uv sync` 和 MediaCrawler 子模块准备后，双击仓库根目录的
[`启动蒸馏应用.cmd`](启动蒸馏应用.cmd)。应用会自动启动本机 FastAPI 与 Streamlit，并在
服务就绪后打开浏览器。进入“蒸馏工作台”后可以自行：

1. 初始化或选择分析项目。
2. 粘贴抖音主页链接并先做不联网预检。
3. 默认采集 20 条作品，对 10 条作品各采样最多 20 条一级评论。
4. 对最多 20 条视频执行本地下载、关键帧/镜头/音频、Whisper 转写和可选 Ollama 视觉分析。
5. 查看持久化任务进度、账号报告和蒸馏结果，并下载 GPT 分析上下文。
6. 生成本地 OpenKB 知识包；远端同步必须再次确认模型处理。

MediaCrawler 首次运行可能打开可见 Chrome，登录与平台验证由用户在浏览器中完成。应用
默认不调用外部模型，也不会保存模型密钥。关闭启动窗口即可停止本机应用；已经开始的
任务状态会保存在本机 SQLite 中。

### 1. 初始化项目

```bash
uv run distiller init ./demo-project --json
```

### 从抖音主页链接直接解析

先预演；不会访问网络、启动浏览器或写入项目：

```bash
uv run distiller account analyze --project ./demo-project \
  --url "https://www.douyin.com/user/<sec-user-id>" \
  --sort latest --dry-run --json
```

在本机配置 TikHub 密钥，确认采集范围和费用后执行完整链路：

```powershell
$env:TIKHUB_API_KEY = "<在本机填写>"
```

```bash
uv run distiller account analyze --project ./demo-project \
  --url "https://www.douyin.com/user/<sec-user-id>" \
  --sort latest --confirm-provider-cost --json
```

默认最多采集 20 条近期作品，不采集评论。可用 `--count` 调整有限范围，用
`--comments-per-video` 显式启用评论；只有明确需要全主页时才使用 `--all`。
也可以用三个明确档位：

- `--profile standard`：默认 20 条、0 评论。
- `--profile comprehensive`：主页可用作品直到 Provider 耗尽/安全上限，并对 3 条作品各
  采样最多 20 条顶层评论。
- `--profile owned`：公开证据保持有界，后续另行导入已授权的私域指标。

`--max-provider-calls <n>` 是执行前硬上限。预演结果会同时返回调用预算、计费上限、Provider
能力和不能保证的数据范围。深度档也不代表完整评论、回复树、粉丝画像或私域经营数据。

MediaCrawler 是显式可选的本地研究链路；它不包含在 wheel 中，需要源码子模块、Node.js
和可见 Chrome：

```bash
uv run distiller account analyze --project ./demo-project \
  --url "https://www.douyin.com/user/<sec-user-id>" \
  --provider mediacrawler --count 20 --dry-run --json

uv run distiller account analyze --project ./demo-project \
  --url "https://www.douyin.com/user/<sec-user-id>" \
  --provider mediacrawler --count 20 --json
```

要在同一条 MediaCrawler 命令中继续分析最多 20 条公开视频，显式增加 `--media-limit`。视频、
帧和字幕留在本机；`base` 可换成已安装的其他本地 Whisper 模型：

```bash
uv run distiller account analyze --project ./demo-project \
  --url "https://www.douyin.com/user/<sec-user-id>" \
  --provider mediacrawler --count 20 \
  --sort latest --media-limit 20 --whisper-model base \
  --vision-provider ollama --vision-model qwen3-vl:8b --json
```

对已经采集过的账号，不需要重新打开浏览器：

```bash
uv run distiller account enrich-media --project ./demo-project \
  --account <acc_id> --limit 3 --whisper-model base --dry-run --json

uv run distiller account enrich-media --project ./demo-project \
  --account <acc_id> --limit 3 --whisper-model base \
  --vision-provider ollama --vision-model qwen3-vl:8b --json
```

预演只读取留存批次并报告候选域名、本地转写可用性和预计写入范围；正式执行仅允许留存
批次中的 HTTPS 抖音/CDN 地址。默认优先选择尚未做单视频分析的作品，因此可分批扩充覆盖。

MediaCrawler 首次运行会准备锁定环境并打开可见 Chrome。请在窗口内手动登录或完成平台
验证；专用登录状态保存在用户目录，不写入项目。`--all` 会持续翻页到 Provider 耗尽，
但仍受 1,000 页/20,000 条作品安全上限约束。不要把 TikHub 密钥或浏览器会话内容粘贴到
聊天、项目配置或 Git。

MediaCrawler 的锁定提交、第三方许可和商业化边界见
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。完整运行边界、错误码与首次真实验收
清单见
[`docs/phase8-account-url-analysis.md`](docs/phase8-account-url-analysis.md)。
本地视频增强的证据链、依赖、降级行为和隐私边界见
[`docs/account-media-enrichment.md`](docs/account-media-enrichment.md)。

重复采集或重复导入账号快照后，可查看观察期增长并生成供 GPT/外部工作流读取的受限上下文：

```bash
uv run distiller account growth --project ./demo-project \
  --account <acc_id> --json
uv run distiller account context --project ./demo-project \
  --account <acc_id> --json
```

上下文包含账号数据、公开互动、增长、报告、评论聚合、视频内容分析、证据路径和缺失项，
但不包含原始评论文本、Provider 原始页、签名视频地址、凭据或浏览器状态。启动
`distiller-api` 后，也可读取：

```text
GET /api/projects/{url-encoded-project}/accounts/{account-id}/growth
GET /api/projects/{url-encoded-project}/accounts/{account-id}/analysis-context
GET /api/tasks?limit=50
```

API 任务默认持久化到用户目录的 SQLite；服务重启时遗留任务会标记为
`E_TASK_INTERRUPTED`、`retryable: true`，不会被悄悄丢失或盲目续跑。

如需把多个账号、多个周期的分析成果编译成长期可查询知识，可连接独立 OpenKB 服务。
先离线预演导出和同步：

```bash
uv run distiller knowledge openkb export --project ./demo-project \
  --account <acc_id> --dry-run --json
uv run distiller knowledge openkb sync --project ./demo-project \
  --account <acc_id> --dry-run --json
```

确认 OpenKB 的模型、隐私边界和潜在费用后，再执行：

```bash
uv run distiller knowledge openkb sync --project ./demo-project \
  --account <acc_id> --confirm-model-processing --json
uv run distiller knowledge openkb query \
  "比较已有账号的内容模式、反例和数据缺口" \
  --project ./demo-project --confirm-model-processing --json
```

同步只读取 `knowledge-outbox/openkb/` 的脱敏派生文档；不会上传原始评论、Provider
响应、媒体、凭据或浏览器状态。OpenKB 不进入核心依赖，回答也不能替代 Distiller 的
证据索引。完整配置和 API 见
[`docs/openkb-integration.md`](docs/openkb-integration.md)。

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
uv run distiller account benchmark-profile --project ./demo-project \
  --account acc_target --json

uv run distiller compare --project ./demo-project \
  --target acc_target --benchmarks acc_benchmark_1,acc_benchmark_2 --json
```

`benchmark-profile` 会内容寻址地保存作品级点赞/评论/分享/收藏中位数与总量、互动结构、
每千粉互动（粉丝量可用时）、评论点赞覆盖、评论情绪/意图/问题/痛点/异议/内容机会、
内容方向和视听特征。`compare` 只在目标平台内按可用维度计算百分位和数据覆盖率；
不可见播放量不会被写成 0，也不参与排序。旧画像不会被新一次蒸馏覆盖。

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

### 8. 分析本地视频画面与声音

视频必须先存在于 `videos.parquet`；本地文件可通过 `--file` 指定，也可来自视频记录的
`media_path`：

```bash
uv run distiller analyze media --project ./demo-project \
  --video video-001 --file ./hotel.mp4 \
  --vision-provider ollama --vision-model qwen3-vl:8b \
  --strict-vision --json

uv run distiller validate --project ./demo-project --json
```

省略 `--vision-provider` 时只运行 FFmpeg/FFprobe 的本地确定性分析；也可使用
`--vision-output ./vision.json` 回放离线结构化结果。`--strict-media` 会在解码器不可用时
返回 `E_MEDIA_DECODE`，`--strict-vision` 会在视觉结果不满足 Schema 时停止。输出包含
`media-analysis.json`、`timeline.json`、`report.md`、
`evidence-index.json`、`warnings.json`、关键帧以及 `media_features.parquet`。

### 9. 使用授权协作 Adapter

先复制 Skill 中的示例 Connector 配置，并只填写环境变量名、授权证明和表格标识；不要把
令牌写入 YAML。预览远端写入不会发送请求：

```bash
uv run distiller sync push --project ./demo-project \
  --connector-config ./google-sheets.yaml --entity metrics --dry-run --json

uv run distiller snapshot plan --project ./demo-project --json
uv run distiller team init --project ./demo-project --owner owner-id --json
```

授权导出、飞书/Google 配置、拉取、批处理和错误码详见
[`docs/authorized-collaboration-adapters.md`](docs/authorized-collaboration-adapters.md)。

### 10. 使用 DuckDB 查询

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
├── raw/media/            # 本地媒体的 SHA-256 寻址副本
├── raw/account-collections/ # 主页 Provider 响应与标准行的内容寻址副本
├── staging/              # 映射并校验后的 JSONL
├── normalized/           # 标准化 Parquet
├── analyses/accounts/    # 内容寻址的分层样本清单
│   └── <account>/benchmark-profiles/ # 可复用的历史互动/评论/内容/视觉画像
├── analyses/videos/      # 盲分析、单视频报告、证据索引和警告
├── analyses/media/       # 镜头、关键帧、音频、OCR 与时间线
├── analyses/comments/    # 评论信号、需求聚类、证据索引和警告
├── reports/accounts/     # 账号体检与账号蒸馏报告
├── reports/comparisons/  # 对标迁移矩阵
├── candidates/           # 内容寻址的脚本候选记录
├── reports/scoring/      # 九维评分、证据和警告
├── predictions/          # 不可变 P25/P50/P75 预测
├── publications/         # 预测与实际视频发布关联
├── reports/retros/       # 预测误差、规则反例和下一轮实验
├── raw/collaboration/    # 官方 API 原始响应的内容寻址副本
├── collaboration/        # Sync、Batch 和快照计划产物
├── team.yaml             # 不含凭证的角色与 Connector 策略
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
稳健指标、代表性采样、账号体检、单视频文本/本地多模态拆解、评论需求分析、Pattern/反例、账号蒸馏、
对标迁移矩阵、脚本评分、不可变区间预测、发布登记、快照复盘、授权导出、飞书多维表格、
  Google Sheets、批量任务、快照计划、团队策略、FastAPI/Streamlit 工作台，以及通过默认
TikHub API 或可选锁定版本 MediaCrawler 进行的抖音公开主页解析与限额评论采样。

尚未实现：登录/验证码自动化、评论回复树、自动批准 Level 4 规则和持久化后台任务队列。
视觉/OCR 支持离线回放与回环 Ollama，不内置云模型客户端；平台数据仅允许用户导出、
明确授权的官方 API，或用户批准的有界
MediaCrawler/TikHub Provider。Phase 5 仍只生成待审批的规则升级建议；详见
[`docs/delivery-overview.md`](docs/delivery-overview.md)。

## 安全限制

- 只访问显式授权的官方表格 API 或用户确认的有界数据 Provider。
- MediaCrawler 只使用专用可见 Chrome 和用户手动登录；不自动处理凭证、验证码，不调用
  代理池、隐身脚本，不绕过风控、速率限制或服务条款。
- 保留 MediaCrawler 上游许可与第三方声明；商业使用前重新完成授权评估。
- 不把不同平台的原始播放量直接比较。
- 不将缺失值写成 0。
- 不提交原始用户数据、密钥、项目状态或本地缓存。
- 评论作者标识在标准化表中只保存哈希。
- 不包含云模型 Provider；Ollama 只允许本机回环地址。字幕和评论可能含敏感信息，
  分享报告前需人工检查。

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

- [产品方向与开发路线](docs/product-direction.md)
- [正式版安装与运行](docs/production-release.md)
- [1.0.0 生产验收记录](docs/production-acceptance-v1.0.0.md)
- [Phase 8 抖音主页链接一键解析](docs/phase8-account-url-analysis.md)
- [交付介绍](docs/delivery-overview.md)
- [架构](docs/architecture.md)
- [数据合同](docs/data-contracts.md)
- [分层采样与账号体检](docs/sampling-and-reporting.md)
- [字幕与盲分析](docs/text-video-analysis.md)
- [本地视频多模态分析](docs/local-media-analysis.md)
- [本地 Ollama 视觉与账号画像验收](docs/local-vision-and-benchmark-acceptance-2026-07-23.md)
- [OpenKB 可选知识层接入](docs/openkb-integration.md)
- [授权平台与协作 Adapter](docs/authorized-collaboration-adapters.md)
- [评论、Pattern 与账号蒸馏](docs/comment-and-account-distillation.md)
- [评分、预测、发布与复盘](docs/scoring-prediction-retro.md)
- [模型 Provider 指南](docs/model-provider-guide.md)
- [Adapter 指南](docs/adapter-guide.md)
- [隐私与合规](docs/privacy-and-compliance.md)
- [开发与测试](docs/development.md)
- [实施取舍](docs/implementation-decisions.md)
- [版本与后续更新说明](docs/release-notes.md)
- [原始规划](docs/planning/)
