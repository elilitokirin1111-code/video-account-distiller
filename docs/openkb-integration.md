# OpenKB 可选知识层接入

## 定位

OpenKB 是独立的派生知识编译和查询层，不是采集器、视频解析器、数据库或证据仓。

Distiller 继续负责：

- TikHub、MediaCrawler 和授权导出的数据采集。
- 原始响应与媒体的不可变保存。
- Parquet/DuckDB 标准化和确定性统计。
- 视频转录、关键帧、评论聚合、账号报告和证据索引。

OpenKB 只接收经过脱敏、限量和证据回链处理的 Markdown 文档，用于跨报告查询和长期知识
积累。OpenKB 返回的回答是派生分析，不得自动升级为 Rule、Rubric 或事实。

## 架构

```text
Provider / authorized export
            │
            ▼
Distiller raw evidence → normalized Parquet → reports / analyses / knowledge-base
                                                │
                                                ▼
                                  KnowledgeExportService
                                                │
                                                ▼
                              knowledge-outbox/openkb/accounts/*.md
                                                │
                                                ▼
                       OpenKBIntegrationService → separate openkb-web
                                                │
                                                ▼
                                  query / chat / downstream GPT
                                                │
                         verify source_paths and evidence IDs
```

OpenKB 不会被加入 `video-account-distiller` 的 Python 依赖。两个项目使用独立虚拟环境和
进程，避免 OpenKB 的 Alpha 依赖锁影响 Distiller 的分析内核。

当前适配器已对照 OpenKB 上游提交 `ff54396e575ee6feb0113b631a34caa082b441cc`
的 REST 契约核验，使用 `/api/v1/init`、`/add`、`/remove`、`/status` 和 `/query`，
所有可能返回 SSE 的调用均显式设置 `stream=false`。上游升级后应先运行本项目契约测试，
再做一次限量真实实例验收。

## 输出目录

```text
knowledge-outbox/openkb/
├── accounts/
│   └── account-<stable-hash>.md
├── manifest.json
└── sync-state.json
```

账号文档包含：

- 项目和账号快照。
- 数据可用性、观察期增长。
- 账号体检、蒸馏、评论聚合、对标画像、媒体增强和限量视频分析。
- 缺失项和下游分析合同。
- 指向 `reports/`、`analyses/`、`knowledge-base/` 的证据回链。

默认不会包含：

- 原始评论文本。
- `raw/` 或 `normalized/` 文件。
- Provider 原始页。
- Cookie、Token、浏览器状态或授权头。
- 签名视频 URL 或媒体文件。
- 默认配置要求隐藏的账号名称、简介和主页 URL。

## 安装和启动 OpenKB

在独立虚拟环境中安装并启动：

```bash
pip install "openkb[web]"
openkb-web --host 127.0.0.1 --port 7566
```

如需启用 OpenKB Bearer Token：

```powershell
$env:OPENKB_API_TOKEN="<openkb-server-token>"
$env:DISTILLER_OPENKB_API_TOKEN="<same-token>"
openkb-web --host 127.0.0.1 --port 7566
```

Distiller 只保存环境变量名称，不保存 Token 值。

## 配置

```text
DISTILLER_OPENKB_BASE_URL=http://127.0.0.1:7566
DISTILLER_OPENKB_KB=distiller-project
DISTILLER_OPENKB_API_TOKEN=<optional>
```

默认仅连接 `http://127.0.0.1:7566`。非回环地址必须使用 HTTPS 并配置 Token。API 请求体
不能覆盖 Base URL，防止把服务变成任意地址请求代理。纯同步预演和本地状态检查不会发出
请求，因此可在尚未注入远端 Token 时检查目标与导出范围；任何真实远端请求仍会拒绝缺失
Token 的配置。

## CLI 工作流

先预演导出和同步：

```bash
uv run distiller knowledge openkb export \
  --project ./demo-project --account <acc_id> --dry-run --json

uv run distiller knowledge openkb sync \
  --project ./demo-project --account <acc_id> --dry-run --json
```

确认导出范围、OpenKB 模型配置、隐私边界和潜在费用后正式同步：

```bash
uv run distiller knowledge openkb sync \
  --project ./demo-project --account <acc_id> \
  --confirm-model-processing --json
```

查询状态和知识：

```bash
uv run distiller knowledge openkb status \
  --project ./demo-project --account <acc_id> --remote --json

uv run distiller knowledge openkb query \
  "这个账号重复出现的高表现模式、反例和数据缺口是什么？" \
  --project ./demo-project --confirm-model-processing --json
```

真实同步和查询必须显式传入 `--confirm-model-processing`，因为 OpenKB 可能调用其配置的
云端或付费模型。未确认时返回 `E_PROVIDER_COST_CONFIRMATION_REQUIRED`。

同步后检查本地导出和状态完整性：

```bash
uv run distiller validate --project ./demo-project --json
```

校验会拒绝越出 `knowledge-outbox/openkb/accounts/` 的文档、大小不一致、指向
`raw/`/`normalized/` 的证据反链，以及引用未知导出的同步状态。

## API

```text
POST /api/projects/{encoded-project}/knowledge/openkb/accounts/{account-id}/export
POST /api/projects/{encoded-project}/knowledge/openkb/accounts/{account-id}/sync
GET  /api/projects/{encoded-project}/knowledge/openkb/accounts/{account-id}/status
POST /api/projects/{encoded-project}/knowledge/openkb/query
```

同步和查询使用持久化任务：

```json
{
  "confirm_model_processing": true,
  "create_kb": true,
  "force": false,
  "max_video_analyses": 10
}
```

客户端随后轮询：

```text
GET /api/tasks/{task-id}
```

## 幂等与更新

- 内容哈希基于去掉瞬时生成时间的规范化上下文。
- 相同账号、相同分析内容重复导出不会重写文件。
- 相同目标、相同内容重复同步会在本地直接跳过，不触发模型调用。
- 内容变化时，先从同一 OpenKB 目标移除旧文档，再上传新文档。
- 更换 OpenKB 目标时不会尝试删除旧目标的数据。
- `--force` 会重新编译，即使内容未变化，因此仍需费用确认。

## 故障与回滚

- OpenKB 不可用不会影响 Distiller 原始证据、标准化数据或报告。
- 同步失败不会更新 `sync-state.json`。
- OpenKB 文档删除不删除 Distiller 导出或证据。
- 可删除 `knowledge-outbox/openkb/` 后重新生成，但不要在未检查时覆盖损坏的 manifest。
- `E_ADAPTER_AUTH`：检查环境变量，不要把 Token 写入项目或日志。
- `E_ADAPTER_RESPONSE`：检查 OpenKB 服务、端口和 API 版本。
- `E_RATE_LIMIT`：等待后重试，不要在未复核费用时提高重试次数。
- `E_RAW_INTEGRITY`：人工检查本地 manifest/sync state，禁止静默修复。

## 验收标准

1. 离线导出中没有原始评论、凭据、原始 Provider 页或媒体 URL。
2. 同一内容重复同步不产生网络请求。
3. 内容变化只替换同一目标中的对应账号文档。
4. OpenKB 回答明确标记 `authoritative=false`。
5. 重要结论能够回链到 Distiller `source_paths` 或 evidence ID。
6. OpenKB 停机不会破坏 Distiller 的任何核心流程。
