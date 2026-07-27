# Architecture

## Phase 0/1/2/3/4/5/6/7/8 data flow

```text
Douyin homepage URL
        │
        ▼
AccountCollectionService → bounded Provider adapter
        │                   ├── default fixed-host TikHub API
        │                   │     ├── URL → sec_user_id
        │                   │     ├── public account profile/posts
        │                   │     └── bounded public comment samples
        │                   └── optional MediaCrawler controlled sidecar
        │                         └── visible Chrome + manual authentication
        ▼
immutable raw Provider batch + canonical accounts/videos/metrics/comments JSON
        │
        ├── explicit --media-limit / account enrich-media
        │       └── AccountMediaEnrichmentService
        │             ├── allowlisted retained play URL → immutable raw media
        │             ├── LocalMediaAnalysisService → shots/keyframes/audio
        │             ├── local Whisper CLI → TranscriptImportService
        │             ├── VideoAnalysisService
        │             └── AccountDistillationService
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
        │
        └── bounded AnalysisContext + curated artifacts
                    └── KnowledgeExportService → knowledge-outbox/openkb/
                              └── OpenKBIntegrationService → optional OpenKB REST sidecar
                                        └── derived query answer + Distiller backlinks
```

The Agent Skill orchestrates the CLI. Deterministic behavior lives in the Python package. Phase 3
and Phase 4 use versioned prompts and a mockable text-provider boundary and ship no network model
provider. Phase 7 network access is isolated behind mockable official-table adapters. Phase 8
account access is isolated behind the `AccountCollectionProvider` protocol. Its default TikHub
implementation keeps an injectable, fixed-host HTTP boundary. The optional MediaCrawler
implementation runs in the upstream pinned `uv` environment and returns one strict JSON envelope
to the parent process. Neither implementation enters the analysis packages. Only the controlled MediaCrawler
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
- `benchmarking/`: immutable account interaction/comment/content/visual profiles and
  same-platform percentile ranking with per-account data coverage.
- `closed_loop/`: Rule/Rubric materialization, explainable script scoring, immutable prediction,
  publication registration, snapshot selection, prediction error, and pending-only Retro changes.
- `media/`: local FFmpeg/FFprobe adapter, scene/keyframe/audio pipeline, loopback-only
  Ollama/Qwen visual/OCR Provider, retained-source downloader, local Whisper adapter, and account
  media enrichment orchestration.
- `adapters/collaboration.py`: fixed-host official API clients, injectable HTTP, authorization,
  bounded retry, provider parsing, and table row contracts.
- `collaboration/`: authorized export/import orchestration, normalized exports, idempotent Sync
  receipts, batch execution, snapshot planning, and credential-free team policy.
- `collection/`: Douyin URL validation, default fixed-host TikHub access, optional controlled
  MediaCrawler sidecar, bounded default pagination, explicit full-homepage pagination with emergency
  guards, opt-in bounded comment sampling, public-field mapping, immutable response storage, and
  orchestration into the existing import/analysis kernel.
- `knowledge/`: privacy-aware account knowledge rendering, canonical content hashes, one-way
  OpenKB synchronization, separate target validation, explicit model-call confirmation, and
  derived query contracts.
- `third_party/MediaCrawler`: Git submodule pinned to an audited commit and governed by its own
  non-commercial learning license; it is not relicensed by the root project.
- `third_party/claude-video`: MIT Git submodule pinned to the audited workflow reference. The
  production account path uses a project-native adapter rather than executing upstream `watch.py`.
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

Reusable account snapshots use stable `abp_*` IDs under
`analyses/accounts/<account>/benchmark-profiles/`. Their identity includes normalized latest
public metrics, the exact `dst_*` distillation and `cma_*` comment analysis. New inputs create a new
profile; old profiles remain available. `cmp_*` embeds the profiles used and a target-platform-only
ranking. Views are excluded because public homepage visibility is not reliable.

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
The bundled live visual path accepts only loopback Ollama on port 11434, requests a strict JSON
Schema, and maps every result back to a sampled keyframe. It does not upload frames to a cloud
endpoint.

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

Opt-in account media enrichment derives source candidates only from that retained batch. Signed
URLs remain inside raw Provider evidence and are never copied into the enrichment artifact. The
adapter accepts only HTTPS Douyin/CDN hosts, stores downloaded bytes through the existing
content-addressed media pipeline, invokes local Whisper without shell execution or cloud upload,
and routes generated transcript segments through normal import and normalization contracts.
`ame_*` artifacts link source batch hash, media IDs, transcript hashes, text-analysis IDs, and the
resulting `dst_*` account distillation.

OpenKB exports live under `knowledge-outbox/openkb/`, outside both raw evidence and the validated
`knowledge-base/` Rule/Pattern store. The export manifest records a canonical payload hash, bounded
source paths, redacted fields, and byte size. Identical payloads are not rewritten or re-synced.
Changed payloads replace only the corresponding document on the same OpenKB target. Tokens remain
environment-only. OpenKB output is explicitly non-authoritative and cannot update Rule/Rubric
files automatically.

Normalized Parquet is reproducible from staging. Project state is stored in
`.distiller-state.json`; later rule and task workflows may introduce SQLite without changing the
Phase 1 table contracts.

## Failure model

Expected failures use stable `E_*` codes. CLI JSON goes to stdout; human error text goes to stderr.
Atomic writes prevent partially replaced state and Parquet files. Validation can detect altered or
missing raw inputs by recalculating SHA-256.

`distiller doctor` composes package/dependency discovery with `validate_project(persist=False)`.
It reads the same contracts as normal validation but creates no run directory and does not update
project state. Its capability flags report optional FFmpeg, local Whisper, local vision, account media
enrichment, MediaCrawler-Douyin, TikHub-Douyin, and collaboration readiness without revealing
credential values or browser-session data.

## Current boundaries

Phase 7 accesses only explicitly authorized user exports or the documented Feishu Bitable and Google
Sheets APIs. Phase 8 accepts a user-provided Douyin homepage. TikHub is the bounded default API route
with explicit cost confirmation. MediaCrawler is an optional adapter restricted to the declared
personal non-commercial research scope and its controlled bridge. The project does not
automate credentials, CAPTCHA/slider handling, proxy rotation, stealth, risk-control evasion, or a
background collector. Phase 6 media remains local; the bundled Ollama Provider is loopback-only,
and no cloud vision Provider uploads media. Opt-in retained-source downloads and transcription stay
local and bounded. The system still
does not infer visual causality, audience representativeness, or
automatically validated Level 4 rules.
OpenKB is optional, runs in a separate environment, and receives only curated Markdown after an
explicit model-processing confirmation. Its absence or failure does not affect collection,
normalization, analysis, reports, or the closed loop.
