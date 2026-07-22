---
name: video-account-distiller
description: "Initialize, import, validate, normalize, sample, query, and report on offline video-account exports with robust account-local metrics and traceable evidence. Use for 拆解视频账号、账号体检、分层采样、高中低表现对照、生成账号报告、导入或分析账号数据、计算互动率或完播效率、检查数据质量，or work with user-provided CSV/JSON exports from Douyin, Xiaohongshu, WeChat Channels, Bilibili, TikTok, YouTube, or Instagram Reels."
---

# Video Account Distiller

Use the Python package and `distiller` CLI for deterministic work. Keep source exports immutable and
perform Phase 0/1/2 tasks fully offline.

## Load references

- Read `references/workflow.md` for every project initialization, import, validation,
  normalization, metric, query, or status task.
- Read `references/data-contracts.md` before mapping fields, interpreting nulls, changing schemas,
  or using Parquet/DuckDB.
- Read `references/metrics.md` before calculating or explaining derived metrics, robust scores, or
  performance bands.
- Read `references/sampling.md` before selecting representative videos or explaining sample
  coverage.
- Read `references/account-health.md` before generating or interpreting an account-health report,
  high/middle/low comparison, evidence index, or warning file.
- Read `references/privacy.md` for comments, identifiers, credentials, raw exports, or any request
  that could involve online collection.
- Read the matching `references/platform-*.md` only when mapping that platform's export.

## Operating contract

- Accept user-provided CSV, JSON, JSONL, and explicit mapping files.
- Never log or silently alter original data. Store an immutable SHA-256-addressed copy first.
- Use Pydantic contracts and preserve unknown values as `None`, not zero, empty string, or false.
- Keep platform aliases inside adapters. Do not scatter source-column names through analysis code.
- Normalize to Parquet before analysis; never make reports read raw CSV directly.
- Compare raw performance only within the same account/platform context. Use account-local robust
  metrics for ranking.
- Emit machine JSON to stdout and logs/errors to stderr. Preserve stable `E_*` error codes.
- Do not access real platforms, automate login, bypass CAPTCHA/rate limits/risk controls, scrape, or
  start a browser. Phase 0/1/2 is offline only.

## Route tasks

Run commands from the repository root with `uv run distiller`; a directly installed `distiller`
console script is equivalent.

### Initialize

Run:

```bash
uv run distiller init <project-dir> --json
```

Do not overwrite existing config or state. Return the created paths and next import commands.

### Import data

Select one entity: `accounts`, `videos`, `metrics`, or `comments`.

```bash
uv run distiller import <entity> --project <dir> --file <path> --platform <platform> --json
```

Add `--mapping <mapping.yaml>` for nonstandard columns. Report accepted, rejected, and duplicate
rows. If a non-empty file has no valid rows, stop on `E_SCHEMA_INVALID` after preserving evidence.

### Validate and normalize

```bash
uv run distiller validate --project <dir> --json
uv run distiller normalize --project <dir> --json
```

Validation verifies raw hashes and staging schemas. Normalization rebuilds deduplicated Parquet
tables atomically. Use `--dry-run` on normalization when the user requests a preview.

### Calculate performance

Read the account ID from `uv run distiller status --json`, then run:

```bash
uv run distiller metrics --project <dir> --account <account-id> --json
```

Explain that Phase 1 uses the latest snapshot per video and compares it to the same account.

### Select representative samples

Run metrics first, then select a deterministic sample:

```bash
uv run distiller sample --project <dir> --account <account-id> --size 40 --json
```

Report population and selected coverage for performance, recency, `content_type` pillar proxy,
duration, promotion, and outliers. Do not describe a sample as representative when the manifest
contains `sampling_gap` or `small_sample` warnings.

### Generate an account-health report

```bash
uv run distiller report --project <dir> --account <account-id> --json
```

When the user requested an exact sample size, add `--sample-size <n>` so the report reuses or
reconstructs the same content-addressed sample.

Return the JSON and Markdown report paths plus `evidence-index.json` and `warnings.json`. Treat every
high/middle/low difference as an account-local statistical association, not a causal content rule.

### Query or inspect status

```bash
uv run distiller status --project <dir> --json
```

For custom SQL, use `video_account_distiller.storage.duckdb_store.DuckDBStore`. Allow only
`SELECT`/`WITH` queries and return source IDs with analytical results.

## Output contract

Return a concise summary first:

1. What succeeded or failed.
2. Input hashes, row counts, rejects, and duplicates.
3. Data-quality warnings and cross-platform limitations.
4. Output paths and account IDs.
5. The safest next command.

Point users to generated quality reports, sample manifest, account-health report, evidence index,
warnings, and run manifest. Never infer content strategy from Phase 2 statistics alone.

## Scripts

The wrappers under `scripts/` prepend the correct CLI route and call the installed Python package;
they contain no analysis logic. Use `scripts/install-skill.py` only when the user asks to install or
uninstall this Skill.

## Current boundary

Subtitle/video semantic analysis, comment intent, full account distillation, pattern/rule discovery,
scoring, prediction, retrospective, multimodal analysis, and live adapters belong to later phases.
Phase 2 account health is deterministic statistics only; state this instead of fabricating content
semantics or strategy.
