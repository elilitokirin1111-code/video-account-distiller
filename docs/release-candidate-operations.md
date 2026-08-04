# 发布候选版操作手册

## 适用范围

本文用于维护者冻结 RC、验证安装包和执行可恢复发布。版本号、Git 标签和正式发布时间仍由
维护者决定；运行本文流程不会自动创建提交、标签或 GitHub Release。

真实 TikHub/MediaCrawler 授权采集、第二次账号快照、OpenKB、创作者后台导出和受控 GPT
调用没有完成时，只能标记为“内部功能 RC”，不能宣称所有外部集成已经生产验收。

## 1. 源码门禁

```powershell
python -m ruff format --check .
python -m ruff check .
python -m mypy src tests
python -m pytest
python -m video_account_distiller release audit --repository . --json
```

审计会检查：

- `pyproject.toml`、`PACKAGE_VERSION`、`SKILL_VERSION` 和 Skill 文档版本一致；
- `LICENSE`、`THIRD_PARTY_NOTICES.md`、隐私文档、生产手册和发布工作流存在；
- wheel 不包含 `third_party/`、`.env` 或 `.git`；
- sdist 包含根许可证和第三方声明；
- 若提供 `dist/`，wheel、sdist、文件名版本和 `SHA256SUMS.txt` 一致。

## 2. 构建与校验和

从空的 `dist/` 开始构建：

```powershell
uv build
Compress-Archive -Path skills\video-account-distiller `
  -DestinationPath dist\video-account-distiller-skill-1.0.0.zip
python -m video_account_distiller release checksums --artifacts dist --json
python -m video_account_distiller release audit --repository . --artifacts dist --json
```

`release checksums` 不覆盖已有 `SHA256SUMS.txt`。重新构建时使用新的输出目录，避免把旧工件
混入新清单。清单只记录文件名，不带 `dist/` 前缀，下载后可以在同一目录直接验证。

## 3. 干净环境安装

不要使用仓库的 editable 环境作为发布证据：

```powershell
uv venv .rc-venv --python 3.11
uv pip install --python .rc-venv\Scripts\python.exe `
  dist\video_account_distiller-1.0.0-py3-none-any.whl
.\.rc-venv\Scripts\python.exe -m video_account_distiller --version
.\.rc-venv\Scripts\python.exe -m video_account_distiller doctor --json
.\.rc-venv\Scripts\python.exe tools\release_acceptance.py `
  --fixtures tests\fixtures `
  --report acceptance-rc.json
```

安装后验收包含初始化、导入、校验、标准化、分析、报告、OpenKB 离线预检以及隔离的项目备份、
校验、恢复和清理演练。

## 4. 生产项目备份与回滚

升级或变更映射前，在项目目录外创建备份：

```powershell
distiller backup create `
  --project C:\data\distiller-project `
  --output D:\backups\distiller-project-before-rc.zip `
  --json
distiller backup verify `
  --archive D:\backups\distiller-project-before-rc.zip `
  --json
```

备份由 ZIP 和同名 `.zip.manifest.json` 组成，二者必须一起保留。manifest 记录项目 ID、
相对文件名、大小和逐文件 SHA-256；工具不跟随符号链接、不覆盖已有备份，也不允许把备份写回
源项目。

回滚只恢复到一个不存在的新目录：

```powershell
distiller backup restore `
  --archive D:\backups\distiller-project-before-rc.zip `
  --destination C:\data\distiller-project-restored `
  --json
```

确认恢复结果零错误并人工检查报告后，再把调用方切换到新目录。工具不会覆盖、删除或原地改写
旧项目。快速演练可运行：

```powershell
distiller backup drill --project C:\data\distiller-project --json
```

## 5. 隐私与许可证复核

- 备份包含项目中的全部原始数据、评论、媒体和派生结果；ZIP 本身不加密，必须放在受控、
  加密的存储中，并按授权期限删除。
- `.zip.manifest.json` 不包含文件内容，但文件名和项目 ID 仍属于敏感运维元数据。
- API Key、浏览器 Profile 和 Cookie 不应位于项目目录；若误放入项目，备份会原样包含。
- MediaCrawler 不进入根 wheel；商业交付前必须单独解决其非商业许可证边界。
- 发布包必须同时提供根 `LICENSE`、`THIRD_PARTY_NOTICES.md` 和校验和清单。

## 6. 冻结判定

只有以下条件全部满足才可冻结：

1. 源码门禁、RC 审计和干净安装验收通过；
2. wheel/sdist/Skill/公测证据包的校验和已冻结且与待发布文件一致；
3. 备份恢复演练通过，恢复目标零校验错误；
4. 隐私、第三方许可证、迁移、外部集成验收状态已人工签字；
5. 发布说明明确列出未完成的真实外部验收，且没有把 Fixture 当作生产证据。

对外稳定版还必须先按 `docs/public-beta-release.md` 生成版本匹配的确定性证据包，并运行：

```powershell
distiller release audit `
  --repository . `
  --artifacts dist `
  --public-beta-evidence dist\video-account-distiller-public-beta-1.0.0.zip `
  --require-public-beta-freeze `
  --json
```

证据缺失、冻结后篡改、门禁状态不可复现、目标版本错配或证据包不在校验和目录时，RC 审计
必须失败。稳定版标签工作流执行相同的强制门禁。
