# GPT 真实评估操作手册

本功能为账号级 GPT 分析提供固定回归集、独立重复运行、引用完整性、结论稳定性和
成本基线。评估默认只做本地预检；只有同时通过项目权限、预算、预检哈希和三项运行
确认后，才会发起远程模型调用。

当前自动化验收使用本地 Fake Provider，没有在开发或测试期间产生真实 API 费用。
正式付费验收仍需要操作者明确授权并在本机设置 `OPENAI_API_KEY`。

## 核心保证

- 同一个 `suite_id + campaign_id + case_id + run_index` 可安全重试；已完成运行读取缓存，
  不会再次调用模型。
- 更换 `campaign_id` 会生成一组新的独立运行，可能再次产生费用。
- `preview_hash` 绑定套件、campaign、模型参数、当前账号上下文哈希、提示词/Schema
  哈希和费用上限。上下文或配置变化后，旧哈希不能执行。
- 每个 case 必须运行 2～5 次；每个 suite 最多 20 个 case。
- 保守费用总额超过 `max_total_cost_usd` 时，以
  `E_GPT_EVALUATION_BUDGET_EXCEEDED` 在调用前停止。
- API Key 只从进程环境读取，不进入请求、SQLite、项目工件或 Git。

## 1. 建立固定账号回归集

复制 [`examples/gpt-evaluation-suite.example.json`](../examples/gpt-evaluation-suite.example.json)，
把占位账号 ID 替换为项目内已经完成本地数据准备和分析的账号。固定回归集应覆盖不同
数据量、内容类型和数据缺口，之后不要在同一 suite 版本中随意更换账号。
真实账号清单可能包含敏感的本地标识，建议保存在仓库外的访问受控目录；Git 中只保留
占位示例。

`max_total_cost_usd` 是本次 suite 的硬预算；`stability_threshold` 是不同独立输出之间
finding 指纹的最低 Jaccard 相似度，默认 `0.6`。

## 2. 只读预检

```powershell
distiller gpt-eval preview C:\data\hotel-project `
  --suite C:\data\hotel-gpt-suite.json `
  --campaign acceptance-2026-08-01 `
  --json
```

预检不读取 API Key、不联网、不写项目。必须审阅：

- `cases[].request.data_scope`：将发送的数据范围；
- `request_fingerprints`：上下文、提示词和 Schema 指纹；
- `planned_independent_runs`：计划调用次数；
- `budget.conservative_maximum_usd` 与 `budget.within_limit`；
- `pricing_snapshot` 和返回的 `preview_hash`。

## 3. 显式执行

先在项目设置中启用 `privacy.allow_cloud_model_upload: true`，再只在当前进程环境设置 Key：

```powershell
$env:OPENAI_API_KEY = "<仅在本机填写>"

distiller gpt-eval run C:\data\hotel-project `
  --suite C:\data\hotel-gpt-suite.json `
  --campaign acceptance-2026-08-01 `
  --confirmed-preview-hash <上一步的 preview_hash> `
  --confirm-cloud-upload `
  --confirm-cost `
  --confirm-independent-paid-runs `
  --json
```

不要用新 campaign ID 来“重试”失败任务。进程中断后应先使用原 campaign ID 重跑；已经
落盘的 run 会命中缓存，只补齐尚未完成的 run。只有确实需要新一轮独立样本时，才创建
新的 campaign ID 并重新预检、复核和确认。

一个 campaign 的 suite、预算或阈值一旦产生结果便不可覆盖。修改 suite 后必须使用新
campaign ID，系统会拒绝把不同预检结果写进已有 campaign 目录。

## 4. 结果与判定

Suite 结果写入：

```text
evaluations/gpt/<suite-id>/<campaign-id>/
  suite.json
  preview.json
  result.json
  report.md
```

每个独立账号结果仍写入：

```text
analyses/gpt/<account-id>/<analysis-id>/
  analysis.json
  audit.json
  evaluation.json
  report.md
```

`result.json` 汇总：

- 引用完整运行数与通过率；
- evidence allowlist 完整性；
- case 内所有运行两两 finding Jaccard 相似度、最小值和均值；
- 新调用数与缓存命中数；
- 每次运行估算费用、总估算费用、未知费用运行数和批准预算；
- `pass`、`review_required` 或 `fail`。

引用不完整、引用越界、稳定性低于阈值或已知估算费用超过预算会判定为 `fail`。响应缺少
可计算费用的 token 用量，或检测到需人工复核的数字结论时，会判定为
`review_required`。API 账单或发票仍是费用的最终权威来源；自动指标不能替代业务正确性
和语义质量人工复核。

## REST API

```text
POST /api/projects/{url-encoded-project}/gpt-evaluations/preview
POST /api/projects/{url-encoded-project}/gpt-evaluations/run
```

请求体使用与 CLI 相同的 suite。执行请求还必须包含 `campaign_id`、
`confirmed_preview_hash`、`confirm_cloud_upload`、`confirm_cost` 和
`confirm_independent_paid_runs`。执行进入非持久、不可自动重试的模型任务队列；通过
`GET /api/tasks/{task-id}` 查询结果。
