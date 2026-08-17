# Phase 8：抖音主页链接一键解析

Phase 8 把“用户提供抖音主页链接”接入已有的不可变导入、Parquet、DuckDB、稳健指标、
评论需求分析、账号体检和账号蒸馏链路。标准入口默认使用 TikHub 文档化 API；
MediaCrawler 保留为显式可选的本地、个人非商业学习研究 Provider。

主页元数据采集默认不下载视频。需要分析作品内容时，显式使用
`--media-limit <1-100>`，或在已有账号上运行 `distiller account enrich-media`。该路径只从
当前账号最新留存的 MediaCrawler 详情证据中解析公开视频源，在本机完成 Whisper 中文
转写、关键帧/镜头/音频分析，可选回环 Ollama/Qwen3-VL 视觉与 OCR、单视频语义分析、
账号重蒸馏和可比较画像保存；不会再次打开浏览器。

## 一条命令会完成什么

`distiller account analyze` 会依次执行：

1. 校验用户提供的 HTTPS 抖音主页 URL。
2. 用选定 Provider 读取公开账号资料、有限主页作品和显式启用的有界一级评论。
3. 完整保存 Provider 原始响应，计算 SHA-256，并生成标准账号、视频、指标和评论输入。
4. 复用原有映射、Pydantic 校验、去重和不可变导入服务。
5. 输出标准化 Parquet，并刷新只读 DuckDB 查询层。
6. 计算互动率、稳健分数和 S/A/B/C/D 表现分层。
7. 生成评论需求分析、账号健康报告、证据索引和账号蒸馏报告。
8. 保存点赞、评论、分享、收藏、评论语义、内容和视听特征的 `abp_*` 账号画像。

默认采集最多 50 条近期作品，不采集评论。`--count <1-20000>` 调整有限作品范围；
`--comments-per-video <1-20>` 显式启用评论。只有明确需要全主页时才使用 `--all`，该模式
另有 1,000 页、20,000 条作品的异常保护与重复游标检测，触发时会明确报告范围警告。
默认不下载作品视频，不读取私有后台指标，也不把当前粉丝数冒充作品发布时粉丝数。

## 安装与运行准备

标准 TikHub 路径可以从 wheel 或普通源码安装运行：

```bash
git clone https://github.com/elilitokirin1111-code/video-account-distiller.git
cd video-account-distiller
uv sync
uv run distiller doctor --json
```

只有使用可选 MediaCrawler 时才需要拉取子模块：

```bash
git submodule update --init --recursive
uv sync
uv run distiller doctor --json
```

MediaCrawler 需要 `uv`、Node.js、Chrome 和子模块源码。首次真实运行时，`uv` 会根据
MediaCrawler 锁文件准备隔离环境，随后打开一个可见 Chrome 窗口。登录或平台验证必须由
用户手动完成；登录状态保存在
`~/.video-account-distiller/browser-profiles/mediacrawler-douyin/`，不写入分析项目或 Git。

Windows 上也可使用本机 Edge。运行前设置
`MEDIACRAWLER_BROWSER_CHANNEL=msedge`，Edge 登录状态会独立保存在
`~/.video-account-distiller/browser-profiles/mediacrawler-douyin-edge/`。
如首次登录需要更多时间，可将 `MEDIACRAWLER_LOGIN_TIMEOUT_SECONDS` 设置为
`30`～`900` 之间的整数；登录页跳转在等待窗口内按临时状态处理。
全主页采集的进程时限默认提升为 3,600 秒；可用
`MEDIACRAWLER_PROCESS_TIMEOUT_SECONDS=60..3600` 显式收紧，但不要用缩短超时掩盖平台
验证、限流或翻页异常。

MediaCrawler 的第三方许可、锁定提交和商业化边界见
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)。

## 可选本地视频增强

对已经采集过的账号，先预演再执行：

```bash
uv run distiller account enrich-media --project <dir> --account <acc_id> \
  --limit 3 --whisper-model base --dry-run --json
uv run distiller account enrich-media --project <dir> --account <acc_id> \
  --limit 3 --whisper-model base --vision-provider ollama \
  --vision-model qwen3-vl:8b --json
```

也可以在主页命令上追加 `--media-limit 3 --whisper-model base --vision-provider ollama
--vision-model qwen3-vl:8b`。详细依赖、证据路径、稳定
错误码和隐私边界见 [`account-media-enrichment.md`](account-media-enrichment.md)。

## 默认 TikHub API 工作流

在本机配置密钥。密钥只从环境变量读取：

```powershell
$env:TIKHUB_API_KEY = "<在本机填写>"
$env:TIKHUB_API_BASE_URL = "https://api.tikhub.dev"
```

先预演；预演不启动浏览器、不访问网络、不写项目：

```bash
uv run distiller account analyze \
  --project ./demo-project \
  --url "https://www.douyin.com/user/<sec-user-id>" \
  --sort latest \
  --dry-run \
  --json
```

确认范围和预计调用数后，显式确认可能发生的费用：

```bash
uv run distiller account analyze \
  --project ./demo-project \
  --url "https://www.douyin.com/user/<sec-user-id>" \
  --sort latest \
  --confirm-provider-cost \
  --json
```

TikHub 只允许配置的固定官方 Provider 主机。项目不会在失败后静默切换到另一付费端点。
命令成功后返回内部 `account_id`、原始证据路径、各实体导入质量、标准化结果、指标结果、
评论分析、账号报告、蒸馏报告和可复用账号画像。

## 可选 MediaCrawler 本地研究工作流

先预演，再执行有限采集：

```bash
uv run distiller account analyze \
  --project ./demo-project \
  --url "https://www.douyin.com/user/<sec-user-id>" \
  --provider mediacrawler \
  --count 20 \
  --dry-run \
  --json

uv run distiller account analyze \
  --project ./demo-project \
  --url "https://www.douyin.com/user/<sec-user-id>" \
  --provider mediacrawler \
  --count 20 \
  --json
```

首次运行请保持 Chrome 窗口可见并手动完成登录。如用户明确批准全主页范围，可把
`--count 20` 替换为 `--all`。热门排序在有限模式下只覆盖本次读取的有界作品池。

## 安全与数据边界

- 只处理用户确认的公开抖音主页。
- 不自动输入账号密码，不自动处理 CAPTCHA/滑块，不调用代理池、隐身脚本或风控绕过。
- 平台要求验证时暂停等待用户手动处理；失败或超时返回稳定错误。
- 默认作品范围为 20 条，默认评论数为 0；全主页和评论采集都必须显式启用。
- 全主页异常保护限制为 1,000 页/20,000 条作品，评论始终保持有界，并保留范围警告。
- 完整原始页面保存在 `raw/account-collections/<provider>/<sha256>/`；公开不等于可任意传播。
- 标准评论只保留作者哈希，评论分析副本继续执行直接标识符脱敏。
- 完播率、平均观看时长、流量来源、受众画像和投流真值等公开主页没有的数据保持未知。
- 公开播放量不可用时保持未知，不写成 0，也不参与跨账号互动排序。

## 稳定错误码

| 错误码 | 含义 |
|---|---|
| `E_PROFILE_URL_INVALID` | 不是允许的 HTTPS 抖音主页链接 |
| `E_MEDIACRAWLER_UNAVAILABLE` | 子模块、uv、Node、Chrome 或隔离运行环境未就绪 |
| `E_BROWSER_LOGIN_REQUIRED` | 可见浏览器内未在时限内完成手动登录或验证 |
| `E_COLLECTION_TIMEOUT` | 有界采集进程超时 |
| `E_PROVIDER_COST_CONFIRMATION_REQUIRED` | TikHub 调用未显式确认可能产生费用 |
| `E_ADAPTER_AUTH` | TikHub 密钥、余额或权限问题 |
| `E_RATE_LIMIT` | 有界重试后仍被限流 |
| `E_ADAPTER_RESPONSE` | Provider 响应不可解析或缺少必要数据 |

账号、作品和指标属于主链路，失败时整次命令失败。评论属于增强链路；评论采集失败时保留
已成功的账号、作品和指标，并添加 `comment_collection_degraded:<错误码>` 警告。

## 正式环境验收

自动测试必须继续使用离线 Fixture。首次真实环境验收建议：

1. 运行 `distiller doctor --json`，确认标准 TikHub 或选定的 MediaCrawler 能力已就绪。
2. 对默认 20 条、无评论范围运行 `--dry-run`，确认 Provider、费用与预计请求量。
3. 在用户确认的公开测试账号上执行一次有限采集；MediaCrawler 登录必须手动完成。
4. 检查账号、作品、指标和评论接受数以及范围警告。
5. 运行 `distiller validate --project <dir> --json`。
6. 人工抽查至少 3 条作品的标题、发布时间与公开互动数。
7. 确认日志、JSON、运行清单和 Git 中没有凭证、Cookie 内容或授权头。

首次真实环境验收已于 2026-07-23 通过，见
[`phase8-live-acceptance-2026-07-23.md`](phase8-live-acceptance-2026-07-23.md)。
Provider 响应变化只在采集适配层修复，不修改标准分析模型和下游证据合同。
