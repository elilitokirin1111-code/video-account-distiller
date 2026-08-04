# 公测试运行、迁移与版本冻结

本流程用于正式发布前的 7～14 个自然日试运行。它把多账号并发、故障隔离、任务恢复、
项目备份恢复、升级迁移回滚和跨机器兼容性记录为不可覆盖的 JSON 证据。冻结命令只有在
全部门禁通过后才会生成 `freeze.json`；开发测试不能替代真实经过的试运行日期。

## 1. 升级前预检和迁移

先执行只读预检：

```powershell
distiller release migrate preview --project C:\path\to\project --json
```

如果输出中的 `migration_required` 为 `true` 且 `supported` 为 `true`，在项目目录外选择一个
全新的备份路径，再显式确认迁移：

```powershell
distiller release migrate apply `
  --project C:\path\to\project `
  --backup D:\distiller-backups\project-before-1.0.0.zip `
  --confirm-migration `
  --json
```

执行器会先创建并验证备份，然后写入状态、执行项目校验并生成
`<project>\migrations\<migration-id>.json`。写入或校验失败时会恢复原始状态文件并校验原始
SHA-256。当前版本只支持显式的 `0.0.0 -> 0.1.0` 状态迁移；未来版本或未知版本会在创建
备份和写文件之前拒绝执行。若项目已经是当前版本，命令是无写入的幂等操作。

## 2. 创建一次公测 campaign

证据目录应位于项目目录之外，并纳入受控备份。campaign 配置一经创建不可修改；需要改变
版本或门禁时应使用新的 campaign ID。

```powershell
distiller release beta init `
  --evidence D:\distiller-release-evidence `
  --campaign v1-0-0-pilot `
  --target-version 1.0.0 `
  --min-days 7 `
  --min-machine-profiles 2 `
  --min-account-labels 3 `
  --json
```

允许的试运行时长为 7～14 天。默认门禁要求至少 7 个不同观察日、2 种机器环境和 3 个不同
账号标签。`--target-version` 必须与实际安装包版本一致。

## 3. 每日记录真实观察

每天在实际使用的机器上至少执行一次；试运行期间至少覆盖两种机器配置和三个真实账号。
账号和机器标签应使用稳定但不含秘密的别名，证据文件只保存这些标签的稳定哈希。

```powershell
distiller release beta observe `
  --evidence D:\distiller-release-evidence `
  --campaign v1-0-0-pilot `
  --project C:\path\to\project `
  --machine-label windows-office-a `
  --account-label account-a `
  --account-label account-b `
  --account-label account-c `
  --notes "daily production workflow completed" `
  --json
```

一次观察会执行并记录：

- 当前 OS、架构、Python、包版本、项目版本、`doctor` 和项目校验结果；
- 真实 SQLite 工作者池的多账号有界并发、单任务故障隔离和显式重试；
- 持久任务的中断与恢复演练；
- 当前项目的完整备份与临时目录恢复演练；
- 旧状态升级、校验、备份回滚及 Unicode/空格路径清理演练。

备份演练会读取完整项目，运行前应确认磁盘空间充足。并发和迁移演练只写系统临时目录，
结束时会验证临时数据库和工作区已清理。任一演练异常都会被写入当天证据，并使该 campaign
无法冻结；不要删除或手工修改失败记录。

## 4. 记录事故和检查门禁

试运行中发生问题时立即追加事故记录：

```powershell
distiller release beta incident `
  --evidence D:\distiller-release-evidence `
  --campaign v1-0-0-pilot `
  --severity high `
  --summary "worker recovery exceeded the operating limit" `
  --json
```

`high` 或 `critical` 事故会永久阻止当前 campaign 冻结。修复后应建立新的 campaign，重新
完成真实试运行。`low` 和 `medium` 会保留在证据中，但不会单独阻断冻结。

随时可读取当前状态：

```powershell
distiller release beta status `
  --evidence D:\distiller-release-evidence `
  --campaign v1-0-0-pilot `
  --json
```

常见阻断项包括实际日期不足、观察日不足、机器或账号覆盖不足、观察失败、严重事故、未来
时间戳以及目标版本与已安装版本不一致。日期按 UTC 证据时间计算；不得通过修改系统时间、
复制或编辑 JSON 来缩短试运行。

## 5. 冻结发布证据

只有 `eligible_for_freeze` 为 `true` 时，才执行显式冻结：

```powershell
distiller release beta freeze `
  --evidence D:\distiller-release-evidence `
  --campaign v1-0-0-pilot `
  --confirm-freeze `
  --json
```

生成的 `freeze.json` 包含目标版本、最终门禁快照和所有 campaign/观察/事故证据的规范化
SHA-256。冻结后不能追加观察或事故；重复冻结只读取同一记录。`freeze.json` 是进入正式
发布审计的门票，不会自动修改版本号、构建安装包或替代校验和、许可证、隐私及回滚审核。

冻结后先执行只读复验，再生成确定性证据包：

```powershell
distiller release beta verify `
  --evidence D:\distiller-release-evidence `
  --campaign v1-0-0-pilot `
  --json

distiller release beta bundle `
  --evidence D:\distiller-release-evidence `
  --campaign v1-0-0-pilot `
  --output release-evidence\video-account-distiller-public-beta-1.0.0.zip `
  --json
```

复验会重新计算证据哈希、门禁状态、版本、ID 和文件路径，并拒绝冻结后的修改、重复记录、
未跟踪 JSON 或错版证据。bundle 命令只接受复验通过的冻结目录；相同证据会生成字节一致的
ZIP，且 ZIP 内清单记录每个文件的 SHA-256。不要手工编辑或重新压缩证据包。

证据结构如下：

```text
<evidence-root>/
└── <campaign-id>/
    ├── campaign.json
    ├── observations/<YYYY-MM-DD>/<observation-id>.json
    ├── incidents/<incident-id>.json
    └── freeze.json
```

正式发布时应把完整 campaign 目录作为只读交付证据，与 RC 构建产物及
`SHA256SUMS.txt` 一起归档。对外发布的 RC 审计必须消费刚生成的证据包：

```powershell
Copy-Item `
  release-evidence\video-account-distiller-public-beta-1.0.0.zip `
  dist\video-account-distiller-public-beta-1.0.0.zip
distiller release checksums --artifacts dist --json

distiller release audit `
  --repository . `
  --artifacts dist `
  --public-beta-evidence dist\video-account-distiller-public-beta-1.0.0.zip `
  --require-public-beta-freeze `
  --json
```

当提供 `--artifacts` 时，证据包必须位于同一个工件目录并出现在 `SHA256SUMS.txt` 中。
稳定版本标签工作流固定从 `release-evidence/` 读取与标签版本一致的 ZIP；缺失、篡改、错版或
未纳入校验和都会阻止 GitHub Release。
