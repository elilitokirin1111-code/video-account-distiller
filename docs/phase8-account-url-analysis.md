# Phase 8：抖音主页链接一键解析

Phase 8 首版把“用户提供抖音主页链接”接入已有的不可变导入、Parquet、指标、报告和账号
蒸馏链路。它使用文档化、需要密钥的 TikHub API Provider，不启动浏览器、不读取 Cookie、
不自动登录，也不处理验证码或绕过平台风控。

## 当前能力

- 接受 `https://*.douyin.com/...` 主页或短链接，拒绝 HTTP、其他域名、内嵌凭证和自定义端口。
- 解析 `sec_user_id`，读取公开账号资料，并按最新或热门顺序分页读取 1～100 条公开作品。
- 映射公开播放、点赞、评论、分享和收藏数据；未知字段保持 `null`。
- 将完整 Provider 响应保存在
  `raw/account-collections/tikhub/<sha256>/provider-batch.json`。
- 将账号、视频和指标转换为标准 JSON，再进入原有字段映射、Pydantic 校验、去重、Parquet、
  Robust 指标、账号体检和蒸馏服务。
- `--dry-run` 不需要密钥、不访问网络、不写项目，返回最多调用次数和预计写入范围。
- 非预演调用必须显式传入 `--confirm-provider-cost`，避免误触付费接口。

首版不读取评论正文、不下载视频文件、不做登录态采集，也不声称获得完播率、观看时长、
流量来源或粉丝画像等非公开后台指标。因此，纯主页蒸馏会包含
`comment_analysis_missing` 和 `semantic_video_analysis_coverage_low` 等范围警告；补充字幕、
本地视频和授权评论后可继续提升语义层结论。

## 准备密钥

在 [TikHub](https://docs.tikhub.io/) 创建并充值可用的 API 密钥，把密钥只放在运行环境，
不要写入项目、配置文件、聊天内容或 Git：

```powershell
$env:TIKHUB_API_KEY = "<在本机填写>"
$env:TIKHUB_API_BASE_URL = "https://api.tikhub.dev"
```

中国大陆环境默认使用 `https://api.tikhub.dev`；海外可使用
`https://api.tikhub.io`。代码只允许这两个固定 Provider 主机。

## 运行

先预演：

```bash
uv run distiller account analyze \
  --project ./demo-project \
  --url "https://www.douyin.com/user/<sec-user-id>" \
  --count 10 \
  --sort latest \
  --dry-run \
  --json
```

确认预计调用次数和 Provider 计费后执行：

```bash
uv run distiller account analyze \
  --project ./demo-project \
  --url "https://www.douyin.com/user/<sec-user-id>" \
  --count 10 \
  --sort latest \
  --confirm-provider-cost \
  --json
```

成功 JSON 会返回内部 `account_id`、采集指纹、不可变原始响应路径、三类导入质量报告、
标准化与指标结果、账号健康报告和蒸馏报告。

## 接口与错误

Provider 使用以下文档化接口：

- [从主页链接提取 sec_user_id](https://docs.tikhub.io/186826167e0)
- [读取抖音用户资料](https://docs.tikhub.io/186826222e0)
- [读取抖音用户主页作品](https://docs.tikhub.io/186826223e0)

新增稳定错误码：

| 错误码 | 含义 |
|---|---|
| `E_PROFILE_URL_INVALID` | 不是允许的 HTTPS 抖音主页链接 |
| `E_PROVIDER_COST_CONFIRMATION_REQUIRED` | 未显式确认 Provider 可能产生费用 |
| `E_ADAPTER_AUTH` | 密钥缺失、无效、余额或权限问题 |
| `E_RATE_LIMIT` | 有界重试后仍被限流 |
| `E_ADAPTER_RESPONSE` | Provider 响应不可解析或缺少必要数据 |

## 正式环境验收

提交代码前的自动测试全部离线运行。首次真实环境验收应使用用户确认的公开测试账号：

1. 运行 `distiller doctor --json`，确认 `capabilities.tikhub_douyin` 为 `true`。
2. 对 10 条作品运行预演，记录预计调用次数。
3. 显式确认费用后执行一次真实解析。
4. 检查账号、视频和指标接受数，查看 Provider 范围警告。
5. 运行 `distiller validate --project <dir> --json`。
6. 人工抽查至少 3 条作品的标题、发布时间与公开互动数。
7. 确认日志、JSON、运行清单和 Git 中均没有密钥或授权头。

真实验收通过后再升级正式发布版本；Provider 字段变化只在
`collection/providers.py` 内适配，不修改标准分析模型。
