# Architecture

## Phase 0/1/2/3/4/5/6/7/8 data flow

```text
Douyin homepage URL
        │
        ▼
AccountCollectionService → bounded Provider adapter
        │                   ├── MediaCrawler controlled sidecar
        │                   │     └── visible Chrome + manual authentication
        │                   └── optional fixed-host TikHub API
        │                         ├── URL → sec_user_id
        │                         ├── public account profile/posts
        │                         └── bounded public comment samples
        ▼
immutable raw Provider batch + canonical accounts/videos/metrics/comments JSON
        │
        └──────────────────────────────────────────────┐
                                                       ▼
CSV / JSON / JSONL
        │
        ▼
FileAdapter → MappingResolver → Pydantic validation
        │               │
        │               └── platform templates or user FieldMapping
        ▼
immutable raw copy + SHA-256
        │
        ▼
validated JSONL staging
        │
        ▼
NormalizationService → deduplicated Parquet
        │                         │
        │                         └── DuckDB read-only views
        ▼
MetricsService → DerivedMetrics Parquet
        │
        ▼
SamplingService → content-addressed sample manifest
        │
        ▼
ReportService → report.json + report.md + evidence index + warnings
        │
        ├── SRT / VTT / TXT / JSON
        │            │
        │            ▼
        │    TranscriptImportService → transcripts.parquet
        │            │
        │            ▼
        └── VideoAnalysisService
                    ├── blind fact extraction + semantic labels
                    └── post-label performance context + video report
        │
        ├── normalized comments → redacted analysis copies
        │                         └── CommentAnalysisService
        │                             ├── intent/pain/objection labels
        │                             └── account-local need clusters
        │
        └── AccountDistillationService
                    ├── content clusters + account-local Patterns
                    ├── support samples + counterexamples + confounders
                    ├── account report + knowledge-base Patterns
                    └── BenchmarkComparisonService → transfer matrix
        │
        └── ScoringService → candidate Rules + versioned Rubric + script score
                    │
                    ▼
            PredictionService → immutable account-local P25/P50/P75
                    │
                    ▼
            PublicationService → normalized video link + snapshot plan
                    │
                    ▼
            RetroService → error + counterexamples + pending proposals + experiments
        │
        └── local media → LocalMediaAnalysisService
                    ├── FFprobe metadata + FFmpeg scene cuts/keyframes
                    ├── bounded PCM audio features
                    ├── optional visual/OCR Provider
                    └── timeline/evidence + media_features.parquet
        │
        └── explicit grant + official table/export source
                    ├── AuthorizedExportManifest → ImportService
                    ├── Feishu/Google Adapter → immutable raw pages → ImportService
                    ├── normalized Parquet → content-addressed remote append
                    └── Batch/Team/Snapshot interfaces → collaboration artifacts
```

The Agent Skill orchestrates the CLI. Deterministic behavior lives in the Python package. Phase 3
and Phase 4 use versioned prompts and a mockable text-provider boundary and ship no network model
provider. Phase 7 network access is isolated behind mockable official-table adapters. Phase 8
account access is isolated behind the `AccountCollectionProvider` protocol. Its default
MediaCrawler implementation runs in the upstream pinned `uv` environment and returns one strict
JSON envelope to the parent process; the optional TikHub implementation keeps its injectable HTTP
boundary. Neither implementation enters the analysis packages. Only the controlled MediaCrawler
bridge may launch a browser: a visible dedicated Chrome profile with manual authentication and no
proxy, stealth, automatic-login, CAPTCHA, or platform-control-evasion feature.

## Components

- `adapters/`: file parsing and centralized platform mapping templates.
- `ingestion/`: raw preservation, hashing, conversion, Pydantic validation, row deduplication, and
  import receipts.
- `normalization/`: deterministic cross-import deduplication and Parquet rebuilds.
- `metrics/`: null-safe ratios, Median, MAD, Robust Z-score, weighted score, and account-local
  performance bands.
- `sampling/`: normalized account dataset joins and deterministic stratified selection.
- `transcripts/`: SRT/VTT/TXT/JSON parsing, immutable raw storage, and normalized segments.
- `features/`: blind content bundle, versioned prompts, structured provider validation, retry,
  conservative degradation, and post-label performance merge.
- `comments/`: redacted comment copies, intent labeling, deterministic fallback, and need clusters.
- `distillation/`: content clusters, Pattern evidence/counterexamples, account knowledge, and
  benchmark transfer review.
- `closed_loop/`: Rule/Rubric materialization, explainable script scoring, immutable prediction,
  publication registration, snapshot selection, prediction error, and pending-only Retro changes.
- `media/`: local FFmpeg/FFprobe adapter, scene/keyframe/audio pipeline, and mockable visual/OCR
  provider boundary.
- `adapters/collaboration.py`: fixed-host official API clients, injectable HTTP, authorization,
  bounded retry, provider parsing, and table row contracts.
- `collaboration/`: authorized export/import orchestration, normalized exports, idempotent Sync
  receipts, batch execution, snapshot planning, and credential-free team policy.
- `collection/`: Douyin URL validation, provider selection, controlled MediaCrawler sidecar,
  optional fixed-host TikHub access, bounded post/comment sampling, public-field mapping, immutable
  response storage, and orchestration into the existing import/analysis kernel.
- `third_party/MediaCrawler`: Git submodule pinned to an audited commit and governed by its own
  non-commercial learning license; it is not relicensed by the root project.
- `reports/`: null-safe account statistics, high/middle/low comparisons, evidence collection, and
  Jinja2 Markdown rendering.
- `storage/`: project state, run manifests, atomic Parquet writes, and DuckDB views.
- `quality.py`: paired JSON/Markdown reports.
- `cli.py`: Typer commands and stable error envelopes.

## Persistence and traceability

Original files are copied under `raw/imports/<entity>/` using their SHA-256 as the filename. Every
staged and normalized record includes `schema_version`, `run_id`, `raw_hash`, source identifiers,
timestamps, and data-quality flags. Every mutating operation writes `runs/<run-id>/manifest.json`.

Phase 2 samples and reports use stable content-addressed `smp_*` and `rpt_*` identifiers. Repeating
the same input/configuration reuses the artifact. Report evidence resolves `evi_*` identifiers to
normalized record IDs, source record IDs, raw hashes, and source run IDs.

Phase 3 transcript imports are keyed by video plus raw hash. Single-video analyses use stable
content-addressed `vta_*` IDs. `blind-analysis.json` is frozen before metric lookup; cited transcript
segment IDs resolve through the video evidence index to normalized records and raw source hashes.

Phase 4 comment analyses use stable `cma_*` IDs; raw authors remain hashed and direct identifiers
are removed only from analysis copies. Account distillations use `dst_*`, Patterns use `pat_*`, and
benchmark comparisons use `cmp_*`. Every referenced `evi_*` resolves to normalized records and raw
hashes. Promoted and Robust-outlier videos remain visible as confounders but do not count as Pattern
support or counterexamples.

Phase 5 scripts are copied under `raw/candidates/` by SHA-256 and described by stable `cand_*`
records. Scores use `score_*`; Rubrics and Rules use `rub_*` and `rule_*` with explicit versions.
Predictions use `pred_*` derived from a canonical input hash and are never overwritten.
Publications use `pub_*` and require prediction-before-publication chronology. Retros use `retro_*`
and preserve the actual metric snapshot. Materially mistimed, promoted, and Robust-outlier
snapshots cannot propose policy changes. Other proposed Rule/Rubric changes remain pending and do
not modify their source files. Proposed experiments use `exp_*` and are stored separately from
validated rules.

Phase 6 copies media to `raw/media/<sha256>.<ext>`, creates content-addressed `mda_*` analyses,
stable `shot_*` and `key_*` timestamp evidence, and aggregate `mdf_*` rows in
`media_features.parquet`. Structured visual output is preserved under `raw/vision-outputs/`.
Keyframe hashes and timeline copies are validated against the main media artifact.

Phase 7 preserves official API pages under `raw/collaboration/<connector>/<sha256>.json`; pulled
rows still pass through `MappingResolver`, strict Pydantic models, staging, and normalization. Sync
receipts use `sync_*` IDs derived from connector, direction, entity, and content. Identical pushes
reuse an existing receipt instead of appending again. Batch and schedule outputs live under
`collaboration/`; `team.yaml` contains policy and environment-variable names but no secret values.

Phase 8 preserves a complete provider-neutral batch and all original response pages under
`raw/account-collections/<provider>/<sha256>/`. Canonical account, video, and metric JSON files in
the same directory then enter `ImportService`; Provider payloads never become report inputs
directly. The MediaCrawler browser profile lives outside the project and repository. Browser
session contents are never copied into artifacts. `TIKHUB_API_KEY` remains an environment variable
and is never persisted or returned.

Normalized Parquet is reproducible from staging. Project state is stored in
`.distiller-state.json`; later rule and task workflows may introduce SQLite without changing the
Phase 1 table contracts.

## Failure model

Expected failures use stable `E_*` codes. CLI JSON goes to stdout; human error text goes to stderr.
Atomic writes prevent partially replaced state and Parquet files. Validation can detect altered or
missing raw inputs by recalculating SHA-256.

`distiller doctor` composes package/dependency discovery with `validate_project(persist=False)`.
It reads the same contracts as normal validation but creates no run directory and does not update
project state. Its capability flags report optional FFmpeg, MediaCrawler-Douyin, TikHub-Douyin,
and collaboration readiness without revealing credential values or browser-session data.

## Current boundaries

Phase 7 accesses only explicitly authorized user exports or the documented Feishu Bitable and Google
Sheets APIs. Phase 8 accepts a user-provided Douyin homepage. The default MediaCrawler path is
restricted to the declared personal non-commercial research scope and its controlled bridge;
TikHub remains an optional paid API route with explicit cost confirmation. The project does not
automate credentials, CAPTCHA/slider handling, proxy rotation, stealth, risk-control evasion, or a
background collector. Phase 6 media remains local, and no bundled network vision provider uploads
media. The system still does not infer visual causality, audience representativeness, or
automatically validated Level 4 rules.
