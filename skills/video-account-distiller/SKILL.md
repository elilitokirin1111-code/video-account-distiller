---
name: video-account-distiller
description: "Initialize, import, validate, normalize, analyze, distill, compare, score, predict, register, and retrospect on video-account exports, explicitly authorized Feishu Bitable or Google Sheets data, local MP4/MOV/MKV media, scripts, transcripts, comments, and metrics with robust evidence, batch jobs, snapshot planning, team policy, and production-release diagnostics. Use for 拆解或蒸馏视频账号、授权导出导入、正式版安装验收、运行环境诊断、飞书多维表格或 Google Sheets 同步、批量任务、定时快照计划、团队配置、分析本地视频、镜头切分、OCR、评论需求、内容模式、对标迁移、脚本评分、发布预测或复盘，using user-provided or explicitly authorized data from Douyin, Xiaohongshu, WeChat Channels, Bilibili, TikTok, YouTube, or Instagram Reels."
---

# Video Account Distiller

Use the Python package and `distiller` CLI for deterministic work. Keep source exports immutable and
perform Phase 0/1/2/3/4/5/6 tasks offline and Phase 7 table sync only with explicit authorization.

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
- Read `references/media-analysis.md` before analyzing MP4/MOV/MKV media, scene cuts, keyframes,
  audio features, OCR, visual labels, decoder degradation, or a shot timeline.
- Read `references/model-providers.md` before supplying structured model output, choosing strict or
  degraded behavior, or handling a model Schema failure.
- Read `references/comment-analysis.md` before labeling comments, interpreting audience demand,
  or sharing comment evidence.
- Read `references/pattern-evidence.md` before creating or interpreting content clusters, Patterns,
  counterexamples, maturity, or confidence.
- Read `references/account-distillation.md` before distilling an account or building a benchmark
  transfer matrix.
- Read `references/scoring-prediction.md` before scoring a script, creating a prediction,
  registering a publication, selecting a metric snapshot, running a Retro, or interpreting a
  Rule/Rubric change proposal.
- Read `references/collaboration-adapters.md` before importing an authorized manifest, contacting
  Feishu Bitable or Google Sheets, exporting normalized rows, running a batch, planning snapshots,
  or editing team policy.
- Read `references/production-operation.md` before validating an installed release, running
  `doctor`, accepting a real work environment, or diagnosing deployment readiness.
- Read `references/privacy.md` for comments, identifiers, credentials, raw exports, or any request
  that could involve online collection.
- Read the matching `references/platform-*.md` only when mapping that platform's export.

## Operating contract

- Accept user-provided CSV, JSON, JSONL, local media, subtitles, and explicit mapping files.
- Never log or silently alter original data. Store an immutable SHA-256-addressed copy first.
- Use Pydantic contracts and preserve unknown values as `None`, not zero, empty string, or false.
- Keep platform aliases inside adapters. Do not scatter source-column names through analysis code.
- Normalize to Parquet before analysis; never make reports read raw CSV directly.
- Compare raw performance only within the same account/platform context. Use account-local robust
  metrics for ranking.
- Emit machine JSON to stdout and logs/errors to stderr. Preserve stable `E_*` error codes.
- Access only a user-approved official table API or a user-provided export. Never automate login,
  bypass CAPTCHA/rate limits/risk controls, scrape, reuse browser sessions, or start a browser.
  Never upload media in local mode. Keep tokens in environment variables only.

## Route tasks

Run commands from the repository root with `uv run distiller`; a directly installed `distiller`
console script is equivalent.

### Verify a production installation

```bash
distiller --version
distiller doctor --json
distiller doctor --project <dir> --json
```

Treat `doctor` as read-only. Report core readiness separately from optional local-media,
Feishu-Bitable, and Google-Sheets capabilities. Never print credential values.

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

### Analyze local media

Run only after the video exists in normalized Parquet:

```bash
uv run distiller analyze media --project <dir> --video <video-id> \
  --file <local-video.mp4> --json
```

Use `--vision-output <offline.json>` only for local schema-targeted visual/OCR results. Omit it to
keep visual fields unknown while still extracting FFprobe metadata, scene cuts, keyframes, and
audio features. Add `--strict-media` when missing or failed FFmpeg must return `E_MEDIA_DECODE`
instead of a degraded artifact; add `--strict-vision` for strict visual Schema behavior. Return
`media-analysis.json`, `timeline.json`, Markdown, evidence, warnings, keyframes, and the
`media_features.parquet` path. Run `distiller validate` afterward. Never infer unobserved visual
details or upload the media without separate explicit authorization.

Use `--max-keyframes <1-100>` to cap evenly distributed keyframes and `--scene-threshold <0-1>` to
override scene sensitivity. These options, Provider output, and extracted features are part of the
content-addressed result, so meaningful differences may create another immutable `mda_*` analysis.
The artifact's `warnings.json` describes analysis limitations; a later validation report may still
show zero validator warnings when that limitation was correctly recorded rather than an integrity
failure. Status summarizes counts; inspect the returned analysis paths for configuration differences.

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

### Score a script

Distill the account first, then run:

```bash
uv run distiller score --project <dir> --account <account-id> \
  --script <script.md> --target-pillar <pillar> --json
```

Return all nine dimension scores, Rubric/Rule versions, missing items, risks, evidence, and warnings.
Treat the score as an explainable pre-publication checklist, not a performance prediction. Candidate
and experimental rules may only make bounded adjustments.

### Save an immutable prediction

```bash
uv run distiller predict --project <dir> --account <account-id> \
  --script <script.md> --target-pillar <pillar> --target-age-hours 72 --json
```

The command scores first, then saves account-local P25/P50/P75 intervals with assumptions, input
hash, Rubric version, Rule versions, and `immutable: true`. Never promise a result or compare raw
cross-platform baselines.

### Register and review a publication

After importing and normalizing the published video, link it to the prediction:

```bash
uv run distiller publish --project <dir> --prediction <pred-id> --video <video-id> --json
uv run distiller retro --project <dir> --publication <pub-id> --snapshot t3d --json
```

Require the normalized publication time to follow prediction creation. Do not use
`--published-at` to contradict the normalized video record.

Import later metric snapshots through the existing metrics Adapter and recalculate metrics before
running Retro. Report interval error, supported/counterexample/inconclusive Rule IDs, external
factors, pending-only Rule/Rubric proposals, and proposed next experiments. Never mutate the linked
prediction or auto-approve a rule change. If the selected snapshot is materially mistimed,
promoted, or a Robust outlier, keep the observation but mark matched Rules inconclusive and do not
propose Rule/Rubric changes from it.

### Query or inspect status

```bash
uv run distiller status --project <dir> --json
```

Use `videos.recent` to obtain both canonical `video_id` and source `platform_video_id`; the list is
bounded and reports whether it was truncated.

For custom SQL, use `video_account_distiller.storage.duckdb_store.DuckDBStore`. Allow only
`SELECT`/`WITH` queries and return source IDs with analytical results.

### Import or sync authorized collaboration data

Read `references/collaboration-adapters.md` and require a recorded grant before proceeding. Prefer
a user-provided export manifest when live API access is unnecessary:

```bash
uv run distiller import authorized-export --project <dir> \
  --manifest <manifest.json> --json
uv run distiller normalize --project <dir> --json
```

For an explicitly approved Feishu Bitable or Google Sheets resource, copy the matching example
asset, keep the token value in the named environment variable, and run `sync pull` or a `sync push
--dry-run`. Confirm connector/resource, entity, platform, row count, columns, scope, and retention
before removing `--dry-run` from a push. Pulled rows still require mapping/Pydantic validation;
run `normalize` after a successful import or pull before analysis or push. Pushes read only
normalized Parquet. Never print token values or authorization headers.

Use `batch run --dry-run` for multiple authorized tasks, `snapshot plan` to emit due work without
collecting it, and `team init`/`team validate` for credential-free roles. Run project validation
after non-dry work and return Sync/Batch paths plus stable adapter errors. `batch run --json`
returns `artifact_path` for non-dry batches.

## Output contract

Return a concise summary first:

1. What succeeded or failed.
2. Input hashes, row counts, rejects, and duplicates.
3. Data-quality warnings and cross-platform limitations.
4. Output paths and account IDs.
5. The safest next command.

Point users to generated quality reports, sample manifest, account-health report, single-video
analysis, media timeline/keyframes, comment analysis, account distillation, transfer matrix,
evidence index, warnings, and run manifest. Include score, immutable prediction, publication,
Retro, and pending proposal paths
when present. Never infer an account strategy from one video or from Phase 2 statistics alone.

## Scripts

The wrappers under `scripts/` prepend the correct CLI route and call the installed Python package;
they contain no analysis logic. Use `scripts/install-skill.py` only when the user asks to install or
uninstall this Skill.

## Current boundary

Package `1.0.0` stabilizes the completed Phase 0–7 workflow. Phase 7 supports authorized export
manifests and official Feishu Bitable/Google Sheets table APIs,
not platform-page scraping or login automation. It exposes batches and snapshot plans but installs
no background scheduler. Phase 6 still ships no network vision client. The system does not
auto-approve Level 4 rules: repeated controlled evidence and explicit human approval remain
required. Do not fabricate visual/audio evidence, causality, authorization, or platform access.
