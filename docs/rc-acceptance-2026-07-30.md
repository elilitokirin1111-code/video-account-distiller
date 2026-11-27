# 发布候选版验收记录（2026-07-30）

## 结论

本轮完成内部功能 RC 所需的源码门禁、包审计、干净安装和备份回滚演练。验收使用临时构建目录
和全新 Python 3.11 环境，没有复用仓库 editable 环境，也没有发布 Git 标签或上传工件。

真实 TikHub/MediaCrawler 授权采集、第二次账号快照、OpenKB、真实创作者后台导出和受控 GPT
调用仍未完成，因此当前结论是“内部功能 RC 就绪”，不是“全部外部集成商业发布就绪”。

## 源码质量

- 全量测试：250 passed。
- 总覆盖率：85.13%。
- Ruff：通过。
- Ruff format：通过。
- mypy（138 个源码文件）：通过。
- `git diff --check`：通过。

## 模块化结果

- CLI 公共 JSON/人类输出和稳定错误边界迁入 `cli_runtime.py`。
- 项目备份命令迁入独立 `cli_backup.py`，发布审计命令迁入 `cli_release.py`。
- OpenKB 与采集批次完整性校验迁入 `validators/openkb.py` 和
  `validators/collection.py`。
- `validate_project` 从 576 个语句降到 510 个语句；后续仍可继续拆分媒体、闭环和协作段，
  但高风险 Provider/OpenKB 边界已经独立测试。

## 构建与工件审计

从当前源码构建：

- `video_account_distiller-1.0.0-py3-none-any.whl`
  - SHA-256：`78523e0f17522530e0d33ce1288dc1f99a9e1f9b55204f2a22375be3f308c2f0`
- `video_account_distiller-1.0.0.tar.gz`
  - SHA-256：`b52f1744a0d08c0e0863d86f43fe3926ab82efbcdf8128d79d53eb4178a36fa2`
- `video-account-distiller-skill-1.0.0.zip`
  - SHA-256：`ecdb21d416ac5a3252b9744d1730a53d42512ac07cc946f885e22505ee72fb77`

RC 审计确认：

- pyproject、包常量和 Skill 文档版本均为 `1.0.0`；
- 根许可证、第三方声明、隐私文档、生产手册和发布工作流齐全；
- wheel 不包含 `third_party/`、`.env` 或 `.git`；
- sdist 包含 `LICENSE` 与 `THIRD_PARTY_NOTICES.md`；
- Skill ZIP 包含 `video-account-distiller/SKILL.md`，且文件名版本一致；
- `SHA256SUMS.txt` 与 wheel/sdist 一致。

这些哈希属于本轮临时验收构建；正式发布必须在冻结提交上重新构建并冻结新哈希。

## 干净环境安装

- Python：3.11.15。
- 平台：Windows。
- 安装来源：本轮构建 wheel，不是源码 editable 安装。
- 安装版本检查：`1.0.0`。
- 安装后验收：23 步全部成功。
- 最终标准化数据：1 个账号、1 个账号快照、30 条视频、30 条指标、18 条评论。
- 最终项目校验：0 error / 0 warning。
- 覆盖初始化、TikHub 离线预检、四类导入、校验、标准化、指标、抽样、报告、评论分析、
  蒸馏、增长边界、GPT 上下文、OpenKB 导出/同步预检、doctor/status。

## 备份与回滚

新增命令：

```text
distiller backup create
distiller backup verify
distiller backup restore
distiller backup drill
```

验收确认：

- 备份只能写到项目外部且不能覆盖已有文件；
- ZIP 与 `.zip.manifest.json` 逐文件记录大小和 SHA-256；
- 不跟随符号链接，恢复成员拒绝绝对路径、`..`、反斜杠、驱动器和 ADS 风格路径；
- 篡改 ZIP 会以 `E_RAW_INTEGRITY` 失败；
- 恢复只能写入不存在的新目录，不覆盖原项目；
- 恢复后执行只读项目校验；
- 隔离演练结束后临时工作区已删除。

## 发布流程修正

原 GitHub Release 工作流在仓库根目录运行 `sha256sum dist/...`，生成的清单带 `dist/` 前缀，
用户下载到同一目录后无法直接校验。本轮改为进入 `dist/` 后生成清单，并增加
`distiller release audit` 作为 GitHub Release 创建前门禁。

`release checksums` 只纳入 wheel、sdist 和 Skill ZIP，不会把 `uv build` 自动创建的
`.gitignore` 混入发布校验和。

## 未解除阻塞

- 授权真实账号的 TikHub/MediaCrawler 限量采集与第二次账号快照；
- OpenKB 真实同步、重复同步和查询；
- 真实创作者后台导出字段/单位冻结；
- 受控 GPT 付费回归；
- 多账号并发、迁移升级、故障注入、跨机器兼容和 7～14 天试运行；
- 维护者对版本、冻结提交、标签和发布窗口的最终决定。
