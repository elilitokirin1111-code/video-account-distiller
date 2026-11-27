# Video Account Distiller 全链路与桌面化架构

本文记录 `integration/unified-product` 分支在 2026-09-01 的真实实现，而不是按文件名或产品文案推测。核对范围包括代码知识图谱、入口与路由、领域服务、项目数据目录、任务数据库、现有测试，以及 `Video_Account_Distiller_增量功能开发方案.docx`。该 DOCX 仅作为历史设计参考；其中提出的四项增量能力目前大多已经落地。

## 1. 系统边界与入口

当前仓库同时提供三类入口：

- CLI：`distiller`，直接调用领域服务，适合脚本与维护。
- REST API：`distiller-api`，FastAPI 在 `127.0.0.1:8000` 提供 82 个项目、采集、分析、任务和知识同步路由。
- Web：`distiller-web`，Streamlit 在 `8501` 提供页面，通过 HTTP 调用本地 API。

旧的 `distiller-tray.exe` 不是桌面产品 UI。它只启动 API/Streamlit 并打开 `http://localhost:8501`，因此仍依赖浏览器。

桌面化采用 Qt 原生控件（PySide6）作为独立表现层，内嵌启动同一个 FastAPI 应用和持久化任务工作池。桌面端通过本机回环地址调用现有 API；CLI、API 和 Streamlit 保持兼容，不复制领域逻辑。

```text
Qt Desktop UI ─┐
Streamlit Web ─┼─> FastAPI application service ─> SQLite task queue/workers
CLI ───────────┘                                  │
                                                  ├─ collection
                                                  ├─ normalization/metrics/comments
                                                  ├─ media/transcription/vision
                                                  ├─ operational distillation
                                                  ├─ video knowledge distillation
                                                  └─ export/WeKnora
```

## 2. 账号主页采集、视频列表与重复运行

### 2.1 请求规划

`AccountDistillWorkflowParams` 继承账号采集参数。主要输入为账号主页 URL、采集档位、数量或全量、时间/热度排序、采集 Provider、评论范围、调用预算、媒体数量以及蒸馏模式。

`resolve_profile_options()` 和 `build_collection_plan()` 先把档位解析成有界的作品、评论和 Provider 调用计划。TikHub 是付费 API，实际执行前要求明确确认成本；MediaCrawler 通过受控桥接进程使用本机浏览器登录态，不实现验证码、认证或平台控制绕过。

### 2.2 Provider 行为

- MediaCrawler：主页 URL 解析后读取账号资料，按游标分页作品列表，再补作品详情与公开评论。全量模式有页数和作品数安全上限，并检测重复游标。
- TikHub：通过已文档化端点解析账号、主页资料、作品页和评论；Provider 响应会经过 drift contract 检查。

两者都映射为统一的 `AccountCollectionBatch`，包含账号、视频、指标快照、评论和原始响应页。

### 2.3 持久化与“增量”的真实语义

每次采集都会对完整 Provider 批次计算 SHA-256 指纹，并写入：

```text
raw/account-collections/{provider}/{fingerprint}/
  provider-batch.json
  accounts.json
  videos.json
  metrics.json
  comments.json           # 有评论时
  drift-report.json       # TikHub
```

导入层按源哈希幂等，原始输入不可变；规范化层按稳定记录 ID 去重并写 Parquet。账号和指标保留时间快照，因此重复运行可以追加新快照、发现新作品并重算增长/指标/蒸馏。

需要准确区分：当前是“重复全范围采集 + 指纹幂等 + 稳定 ID 去重 + 快照追加”，不是“记住上一条游标/发布时间并只请求新增作品”的网络层真增量。全量账号重复运行仍会重新分页到请求边界，成本和耗时不会按新增数量线性下降。

## 3. 视频下载、音频、转写与视觉分析

`AccountMediaEnrichmentService` 读取规范化视频记录和 Provider 保留的媒体地址，按数量选择视频后执行：

1. 有界 HTTP 下载到 `raw/media`，限制允许的 URL/响应大小并保留下载元数据。
2. 使用 ffprobe/ffmpeg 读取容器、视频流和音频流；抽取镜头、关键帧、音频 PCM 与可解释的音频特征。
3. 使用 `faster-whisper` 或 OpenAI Whisper CLI 生成本地转写和时间分段；`auto` 优先可用的 faster-whisper。
4. 使用 Ollama、llama.cpp 或 OpenAI-compatible 云端视觉模型分析关键帧/OCR 信息。
5. 生成单视频媒体分析、文字盲分析、证据引用和降级警告，供两种蒸馏模式共同消费。

媒体能力允许受控降级：ffmpeg、ASR 或视觉模型不可用时，可依据严格模式决定失败或记录 unknown/warning。账号工作流成功生成持久化分析后，`DownloadedMediaCleanupService` 只删除经过路径校验且已被分析引用的 `raw/media` 原视频；派生分析、转写和证据保留。失败时原视频保留，便于重试。

## 4. 两类蒸馏模式

账号工作流入口为 `AccountDistillWorkflow.run()`，底层采集和媒体证据共享，分流发生在解释/知识层。

### 4.1 运营蒸馏 `creative_learning`

执行采集、规范化、指标、评论、媒体、转写和视频分析后，继续生成：

- 账号模式/反例蒸馏；
- 账号健康报告、基准画像和分析上下文；
- 可选远程账号综合分析；
- 叙事报告；
- 本地知识导出。

`analysis_focus=general|hospitality` 只影响账号综合解释。`hospitality` 保留通用分析主体，在末尾增加酒旅迁移解释；不修改底层观察证据。

### 4.2 纯知识蒸馏 `knowledge`

`distillation_mode=knowledge`（或兼容字段 `distill_video_knowledge=true`）要求媒体分析。采集阶段关闭运营报告、评论洞察和账号 Pattern 输出，随后由 `AccountVideoKnowledgeService` 对每条具备文字分析证据的视频调用 `SingleVideoKnowledgeService`。

知识模型输出独立 Schema，区分视频陈述、事实性条目、概念、方法、案例、数据、新闻、作者观点、建议与模型推断；保留 transcript 时间段和视觉/OCR 引用。系统不联网替视频做外部事实核验。

## 5. 单视频与账号级知识产物

单视频知识原始产物位于：

```text
analyses/videos/{video_id}/knowledge/{knowledge_id}/
  knowledge.json
  knowledge.md
  evidence.json
  warnings.json
```

账号级批量产物位于：

```text
knowledge/accounts/{account_id}/video-knowledge/{manifest_id}/
  manifest.json
  README.md
  documents/
    {原视频标题}.md
    {重复标题}（2）.md
```

批量服务读取账号全部规范化视频，缺少文字分析的视频进入 `skipped`，其余视频生成一视频一文档。文件名规则为：

- 优先使用原视频标题，缺失时使用 `video_id`；
- 删除 Windows 非法控制字符和 `\\ / : * ? \" < > |`；
- 规避 Windows 保留名；
- 限制文件名长度并去掉尾部点/空格；
- 同名标题增加全角序号 `（2）`、`（3）`；
- manifest ID 由账号、版本、知识 ID 和跳过视频 ID 稳定生成，已有完整 manifest 时复用缓存。

桌面应用在此目录之上提供 ZIP 知识包导出，不改变领域产物身份；ZIP 内保留 `manifest.json`、`README.md` 和标题命名的 `documents/`。

## 6. 任务状态、恢复与重试

API 任务存储默认位于当前用户目录：

```text
~/.video-account-distiller/api/tasks.sqlite3
```

`TaskStore` 使用 SQLite 保存 durable task、轻量摘要列、完整 payload、checkpoint、worker lease 和取消标记。`TaskWorkerPool` 按资源类别和并发配置领取任务，并定期续租。

主要状态为 queued、running、completed、failed、cancelled。账号工作流在采集、媒体、报告、知识导出等安全阶段写 checkpoint。进程异常退出后，过期 lease 会恢复为可重试状态；账号任务重试从原始 secret-free 参数和最近 checkpoint 重建，可在白名单内覆盖 Provider、范围、模型和模式。

`GET /api/tasks` 直接查询轻量摘要列，不反序列化大型 result；`GET /api/tasks/{id}` 只在查看详情时读取完整 payload。桌面端轮询摘要，选择单项时再拉详情，并提供取消和失败重试。

## 7. WeKnora 同步

`WeKnoraSyncService` 支持读取用户可见知识库、账号运营报告同步、单视频创作蒸馏同步、单视频知识同步和账号逐视频知识包同步。

同步不会自动创建知识库。用户提供 WeKnora 地址、API Key 和目标 KB；桌面端把 API Key 保存到 Windows Credential Manager，只在同步请求时从凭据库读出并发送给本机 API。仓库、项目配置和桌面设置 JSON 均不保存该密钥。

文档归属 metadata 至少包含 `source=video-account-distiller`、`document_type`、账号/视频 ID、knowledge/distillation ID 和模式。替换旧文档时纳入 `document_type`，因此同一视频的 `creative_learning` 与 `video_knowledge` 不互删。账号逐视频知识同步只接受 complete、无 degraded/skipped 且文件齐全的最新 manifest。

## 8. 配置、密钥、模型与本地服务

- 项目配置：`{project}/distiller.yaml`，保存非秘密的媒体、隐私、模型端点和模型名。
- 项目状态：`.distiller-state.json`；运行审计：`runs/{run_id}/manifest.json`。
- 云模型密钥：现有 `KeyringCloudCredentialStore` 保存到操作系统凭据库。
- WeKnora 密钥：桌面专用凭据键，同样保存到操作系统凭据库。
- 桌面非秘密设置：当前用户应用数据目录，不进入项目或 Git。
- 本地 API：桌面进程自动在空闲回环端口启动并停止。
- Ollama：桌面展示 `/api/tags` 可用性；若安装了 `ollama.exe` 且用户选用 Ollama，可由桌面启动 `ollama serve`。
- llama.cpp、WeKnora：视为用户配置的本地/远程服务，桌面显示探测状态，不擅自修改其部署。
- MediaCrawler：采集任务按需启动受控桥接进程和浏览器；登录/挑战需要用户在允许的浏览器流程中完成。

## 9. 前后端调用关系

桌面和 Streamlit 共用下列核心 API：

- `POST /api/projects/init`：初始化项目，不覆盖已有文件。
- `GET /api/projects/{path}/validate|status`：项目和能力状态。
- `POST /api/projects/{path}/workflows/account-distill`：提交账号全链路。
- `GET /api/tasks`、`GET /api/tasks/{id}`：摘要和详情。
- `POST /api/tasks/{id}/cancel|retry`：取消和持久化重试。
- `POST /api/projects/{path}/knowledge/local/accounts/{id}/distill-videos`：已有账号逐视频知识提取。
- `POST /api/projects/{path}/knowledge/weknora/knowledge-bases`：列出 KB。
- `POST /api/projects/{path}/knowledge/weknora/accounts/{id}/sync`：账号运营或逐视频知识同步。
- `PUT /api/cloud-model/credentials/{provider}`：探测并保存云模型密钥到 OS keyring。

UI 不导入采集、ASR 或蒸馏实现；API job handler 打开 `ProjectLayout`，构造 Provider 和工作流，再把进度/checkpoint 写回任务存储。领域服务因此仍可由 CLI 和测试直接调用。

## 10. 已确认问题与处理优先级

### 已在桌面化任务中处理

1. 浏览器依赖：新增原生 Qt 桌面入口，旧 Streamlit 入口保留为兼容能力。
2. 服务生命周期不可见：桌面统一启动/停止 API，展示 API、任务队列、Ollama 和 WeKnora 状态。
3. 密钥入口分散：桌面只通过 OS keyring 保存云模型与 WeKnora 密钥，不把密钥写入设置或任务参数。
4. 结果发现困难：桌面直接展示最新账号知识 manifest、文档数量、降级/跳过状态，支持打开目录和导出 ZIP。
5. 云端工作流参数漏传：当前 `execute_account_distill()` 没有把 `cloud_base_url/cloud_text_model/cloud_vision_model` 完整传入工作流，且知识模型云端密钥依赖任务 body；桌面化时改为从 keyring 在 worker 执行阶段解析 secret-free credential reference。
6. API 生产启动使用 `reload=True`：桌面内嵌服务器和打包入口固定关闭 reload。
7. Windows 安装交付缺失：增加 PyInstaller 规格、便携包/安装脚本和实际构建验证。

### 保留但明确记录的限制

1. 网络层不是真增量：重复账号任务仍重新分页；当前增量只体现在不可变批次、导入幂等、规范化去重和快照追加。
2. WeKnora 替换不是事务：现有逻辑先删除匹配旧文档再上传新文档；中途失败可能造成暂时缺文档，需要重试。
3. 完整性门禁严格：账号知识包只要有 skipped/degraded 就拒绝整包同步；这是防止残缺知识污染 KB 的安全选择，但需要用户修复模型/媒体问题后重跑。
4. 原视频成功后删除：这是现有存储策略，不是桌面层行为；需要保留原视频时应在未来增加显式产品配置。
5. MediaCrawler 与 Whisper 仍依赖体积较大的浏览器、ffmpeg 和模型运行时；桌面 EXE 可以启动和诊断，但不能把所有模型权重内嵌进安装包。
6. 初始全量测试在 Windows Python 3.14 上为 406 passed、4 failed；四个失败均是 API 合同测试仅等待约 1 秒导致后台 dry-run 任务未及时结束，而非断言结果错误。桌面化任务会把等待方式改成事件上限更合理的稳定测试并重新执行全套检查。

## 11. 桌面分层

```text
video_account_distiller_desktop/
  main.py                 # Qt 生命周期和单进程入口
  window.py               # 原生页面、表格、表单、状态展示

video_account_distiller/application/
  desktop_api.py          # 类型化本机 API client 与友好错误
  desktop_runtime.py      # 内嵌 API/Ollama 生命周期和服务探测
  desktop_settings.py     # 非秘密用户设置 + OS keyring secret store
  knowledge_packages.py   # manifest 发现与 ZIP 导出应用服务

video_account_distiller/
  collection, media, workflows, distillation, knowledge, api, ...
                           # 现有领域与兼容入口
```

依赖方向固定为 `desktop UI -> application services -> existing API/domain`。领域层不依赖 Qt；应用服务可在无 UI 环境下单测；Streamlit/CLI 不依赖桌面包。
