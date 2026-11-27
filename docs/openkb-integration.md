# OpenKB 集成已退役

自决策 ID-084 起，项目不再提供 OpenKB 的 Web、API、CLI、任务队列、环境变量或自动同步入口。

新的脱敏知识包写入 `knowledge-outbox/local/`，仅供本地归档、Obsidian 和人工验证使用：

```bash
uv run distiller knowledge package export \
  --project ./demo-project \
  --account <acc_id> \
  --json
```

此前已经生成的 `knowledge-outbox/openkb/` 历史文件不会自动迁移或删除，仍可按普通文件读取。
