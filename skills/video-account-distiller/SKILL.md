---
name: video-account-distiller
description: "Initialize, import, validate, normalize, analyze, distill, compare, and report on offline video-account exports, transcripts, and comments with robust metrics, blind text labels, audience-need clusters, evidence-backed Patterns, counterexamples, and transfer matrices. Use for 拆解视频账号、蒸馏账号、分析评论、提炼用户需求、发现内容模式、寻找反例、对标迁移、拆解单条视频、导入字幕、提取 Hook/结构/CTA/情绪/内容支柱、账号体检、分层采样或生成账号报告，using user-provided exports from Douyin, Xiaohongshu, WeChat Channels, Bilibili, TikTok, YouTube, or Instagram Reels."
---

# Video Account Distiller

Use the Python package and `distiller` CLI for deterministic work. Keep source exports immutable and
perform Phase 0/1/2/3/4 tasks fully offline.

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
- Read `references/video-analysis.md` before importing subtitles, analyzing one video, explaining
  Hook/structure/emotion/CTA/content-pillar labels, or interpreting blind analysis.
- Read `references/model-providers.md` before supplying structured model output, choosing strict or
  degraded behavior, or handling a model Schema failure.
- Read `references/comment-analysis.md` before labeling comments, interpreting audience demand,
  or sharing comment evidence.
- Read `references/pattern-evidence.md` before creating or interpreting content clusters, Patterns,
  counterexamples, maturity, or confidence.
- Read `references/account-distillation.md` before distilling an account or building a benchmark
  transfer matrix.
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
  start a browser. Phase 0/1/2/3/4 is offline only.

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

Validation verifies raw hashes, staging schemas, and any generated video-analysis artifacts,
including blind-stage isolation and evidence references. Normalization rebuilds deduplicated
Parquet tables atomically. Use `--dry-run` on normalization when the user requests a preview.

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

### Import a transcript

Import subtitles only after the target video exists in normalized Parquet:

```bash
uv run distiller import transcripts --project <dir> --video <video-id> \
  --file <subtitle.srt> --language zh-CN --json
uv run distiller normalize --project <dir> --json
```

Accept SRT, VTT, TXT, JSON, or JSONL. Return segment counts, raw SHA-256, the immutable raw path,
and the normalized `transcripts.parquet` count. Preserve unknown timing as `null`. The video
argument may be an internal `vid_*` or a unique platform video ID.

### Analyze one video

Run blind text analysis first; performance context is attached only after labels are frozen:

```bash
uv run distiller analyze video --project <dir> --video <video-id> \
  --model-output <structured-output.json> --json
```

Omit `--model-output` for a conservative deterministic fallback. Add `--strict-model` when the user
prefers `E_MODEL_UNAVAILABLE` or `E_MODEL_SCHEMA_INVALID` over degraded output. Return the analysis,
blind-analysis, Markdown report, evidence index, and warnings paths. Never promote one video's
labels to an account rule. Run `distiller validate` after generation to verify the complete artifact
and evidence chain.

### Analyze comments

Run after comments and videos are normalized:

```bash
uv run distiller analyze comments --project <dir> --account <account-id> --json
```

Use the local deterministic fallback by default or pass an offline `--model-output`. Report direct
identifier redactions, label status, comment/video coverage, need clusters, evidence, and sampling
bias warnings. Never describe exported commenters as the whole audience.

### Distill an account

Run metrics first and comment/video analysis where available:

```bash
uv run distiller distill --project <dir> --account <account-id> --json
```

Return content clusters, positioning observations, comment needs, Patterns, support videos,
counterexamples, confounders, actions, experiments, knowledge-base paths, and warnings. Phase 4
Patterns may be observations or associations only; never promote them to Level 4 rules.

### Compare benchmark accounts

Distill the target and every benchmark separately, then run:

```bash
uv run distiller compare --project <dir> --target <account-id> \
  --benchmarks <benchmark-id-1>,<benchmark-id-2> --json
```

Keep each platform/account baseline separate. Judge transferability from content features, scope,
resources, risk, and Pattern maturity; do not compare raw views across accounts or platforms.

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

Point users to generated quality reports, sample manifest, account-health report, single-video
analysis, comment analysis, account distillation, transfer matrix, evidence index, warnings, and
run manifest. Never infer an account strategy from one video or from Phase 2 statistics alone.

## Scripts

The wrappers under `scripts/` prepend the correct CLI route and call the installed Python package;
they contain no analysis logic. Use `scripts/install-skill.py` only when the user asks to install or
uninstall this Skill.

## Current boundary

Scoring, prediction, retrospective, Level 3/4 rule validation, visual/audio multimodal analysis,
and live adapters belong to later phases. Phase 4 uses normalized exports and text artifacts only;
do not fabricate visual/audio evidence, audience representativeness, causality, or validated rules.
