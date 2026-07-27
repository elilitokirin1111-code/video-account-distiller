# Data contracts

Core normalized schema version: `0.1.0`. Phase 2 analysis artifact schema version: `0.2.0`.
Phase 3 transcript/text-analysis schema version: `0.3.0`.
Phase 4 comment/distillation schema version: `0.4.0`.
Phase 5 scoring/prediction/Retro schema version: `0.5.0`.
Phase 6 local media-analysis schema version: `0.6.0`.
Phase 7 collaboration schema version: `0.7.0`.
Phase 8 account-collection schema version: `0.8.2`.

The authoritative planning dictionary is `docs/planning/04_DATA_SCHEMA.md`; executable contracts
are Pydantic models in `src/video_account_distiller/models/core.py` and reject unknown fields.
Phase 2 contracts are in `src/video_account_distiller/models/analysis.py` and use the same strict
unknown-field policy. Phase 3 contracts are in `models/text_analysis.py`; Phase 4 contracts are in
`models/distillation.py`; Phase 5 contracts are in `models/closed_loop.py`; Phase 6 contracts are in
`models/media.py`; account media-enrichment contracts are in `models/media_enrichment.py`.
Phase 7 authorization, connector, Sync, Batch, Snapshot, and Team contracts are in
`models/collaboration.py`.
Phase 8 collection request, canonical Provider row, raw-page, and batch contracts are in
`models/collection.py`.

## Core tables

| Parquet table | Pydantic model | Primary identity |
|---|---|---|
| `accounts.parquet` | `Account` | `account_id` / `record_id` |
| `account_snapshots.parquet` | `AccountSnapshot` | `account_snapshot_id` |
| `videos.parquet` | `Video` | `video_id` / `record_id` |
| `metric_snapshots.parquet` | `MetricSnapshot` | `metric_snapshot_id` |
| `comments.parquet` | `Comment` | `comment_id` / `record_id` |
| `transcripts.parquet` | `TranscriptSegment` | `segment_id` / `record_id` |
| `derived_metrics.parquet` | `DerivedMetrics` | stable ID from metric snapshot and schema |
| `media_features.parquet` | `MediaFeatureRecord` | `mdf_*` from media analysis ID |

All core records carry source platform/type/URI/record ID, collection and ingestion timestamps,
run ID, raw hash, schema version, and quality flags. Unknown values are `null`, never fabricated as
zero, empty string, or false.

## Stable IDs

Internal IDs are deterministic SHA-256 prefixes derived from platform and source identifiers:
`acc_`, `vid_`, `ms_`, `cmt_`, `ts_`, and `dm_`. Reimporting the same export yields the same record
IDs.

## Raw and staging contracts

- Original bytes: `raw/imports/<entity>/<sha256>.<extension>`.
- Validated staging: `staging/<entity>/<sha256>.jsonl`.
- Import receipt: `.distiller-state.json`.
- Quality output: `runs/<run-id>/quality-report.json` and `.md`.
- Run metadata: `runs/<run-id>/manifest.json`.

Staging is an adapter artifact and may be rebuilt by reimporting the immutable raw file. Reports and
manifests include run ID, input hashes, schema version, counts, warnings, and output paths.

## Null, zero, and invalid values

- Unknown numerator or denominator produces a `null` derived rate.
- Known zero numerator with a positive denominator produces `0.0`.
- Zero denominator produces `null`.
- Negative counts, durations, or monetary values fail Pydantic validation and appear as rejected
  rows in the quality report.

## Deduplication

Within one file, duplicate internal record IDs keep the first valid row and add a warning. Across
imports, identical records collapse. Conflicting duplicates choose the latest `ingested_at`, then
`raw_hash` as a deterministic tie-breaker, and retain a quality warning.

## Migration policy

Package version `1.0.0` does not rewrite existing accounts, videos, metrics, comments, derived metrics,
samples, reports, Patterns, or distillations. Existing project config/state files remain valid
because scoring/media/collaboration policy and timestamps have defaults. Phase 7 adds collaboration
artifacts and state timestamps; all Phase 0–7 artifact schema versions remain unchanged from the
`0.7.0` package. Package stability and artifact contract versions are intentionally independent.

## Phase 2 analysis artifacts

| Path | Contract | Identity |
|---|---|---|
| `analyses/accounts/<account>/samples/<smp_*>/sample-manifest.json` | `SampleManifest` | content-addressed sample ID |
| `reports/accounts/<account>/<rpt_*>/report.json` | `AccountHealthReport` | content-addressed report ID |
| `reports/accounts/<account>/<rpt_*>/evidence-index.json` | `EvidenceIndex` | report ID + `evi_*` items |
| `reports/accounts/<account>/<rpt_*>/warnings.json` | warning envelope | report ID |

`SampleManifest` records population/requested/target/selected sizes, coverage by performance,
recency, content pillar proxy, duration and special flags, selected video IDs, reasons, raw input
hashes, and run ID.

Every scalar or distribution in `AccountHealthReport` carries an evidence ID. `EvidenceIndex`
resolves it to normalized table/record IDs, original source record IDs, raw hashes, calculations,
and source run IDs. See `docs/sampling-and-reporting.md` for the complete behavior contract.

## Phase 3 transcript and video-analysis artifacts

| Path | Contract | Identity |
|---|---|---|
| `normalized/transcripts.parquet` | `TranscriptSegment` | stable `ts_*` from video/timing/text |
| `analyses/videos/<video>/<vta_*>/blind-analysis.json` | `BlindContentAnalysis` | content bundle + prompts + model result |
| `analyses/videos/<video>/<vta_*>/analysis.json` | `SingleVideoAnalysis` | blind result + latest performance context |
| `analyses/videos/<video>/<vta_*>/evidence-index.json` | `VideoAnalysisEvidenceIndex` | segment and metric evidence |
| `analyses/videos/<video>/<vta_*>/report.md` | Jinja2 text report | analysis ID |

Transcript start/end may be `null` when the source, such as TXT, has no timing. Known intervals must
be non-negative and ordered. Model output rejects unknown fields and must cite existing segment IDs
for known semantic labels. The blind bundle and blind artifact exclude all performance fields.

## Phase 4 comment and account artifacts

| Path | Contract | Identity |
|---|---|---|
| `analyses/comments/<account>/<cma_*>/analysis.json` | `CommentAnalysis` | redacted signals + provider traces + clusters |
| `analyses/comments/<account>/<cma_*>/evidence-index.json` | `ArtifactEvidenceIndex` | comment and cluster evidence |
| `reports/accounts/<account>/<dst_*>/distillation.json` | `AccountDistillation` | account inputs + config + upstream analyses |
| `knowledge-base/patterns/<pat_*>.json` | `Pattern` | feature + support + counterexamples + version |
| `analyses/accounts/<account>/benchmark-profiles/<abp_*>/profile.json` | `AccountBenchmarkProfile` | latest normalized metrics + exact comment/distillation artifacts |
| `reports/comparisons/<cmp_*>/comparison.json` | `BenchmarkComparison` | target + benchmark distillations + exact `abp_*` profiles |

`CommentSignalAnnotation` rejects empty intent labels and out-of-range probabilities/confidence.
`CommentAnalysis` counts must match its signals and unique videos. `ContentCluster.video_count` must
match unique video IDs. `Pattern` requires at least one support video, exact support/counterexample
counts, disjoint sets, evidence IDs, scope, confidence, maturity, and version.

`AccountBenchmarkProfile` preserves account and latest metric snapshot time, sampled/analyzed
coverage, likes/comments/shares/saves totals and per-video medians, interaction mix, optional
interactions per 1,000 followers, comment-like coverage/total/median, semantic comment aggregates,
content pillars, visual identity, input hashes, and explicit warnings. Unknown views and followers
remain `null`. `AccountRankingEntry` contains target-platform rank, available-dimension percentile
scores, raw indicators, composite score, data coverage, and limitations.

`ArtifactEvidenceIndex` resolves Phase 4 conclusions to normalized comment/account/video/metric
records, source IDs, source runs, and raw hashes. `distiller validate` verifies companion files,
artifact identities, account scope, evidence references, evidence sources, and knowledge Pattern
files.

## Phase 5 closed-loop artifacts

| Path | Contract | Identity |
|---|---|---|
| `raw/candidates/<sha256>.<ext>` | original script bytes | SHA-256 |
| `candidates/<cand_*>/candidate.json` | `ContentCandidate` | account + script hash + target context |
| `knowledge-base/rules/<rule_*>/<version>.json` | `Rule` | account + source Pattern |
| `knowledge-base/rubrics/<account>/<rub_*>.json` | `Rubric` | distillation + Rule versions + weights |
| `reports/scoring/<account>/<score_*>/score.json` | `ScoreResult` | candidate + Rubric/Rule versions |
| `predictions/<pred_*>/prediction.json` | `Prediction` | canonical immutable input hash |
| `publications/<pub_*>/publication.json` | `Publication` | prediction + video + publication facts |
| `reports/retros/<pub_*>/<retro_*>/retro.json` | `Retro` | publication + prediction + actual snapshot |
| `knowledge-base/experiments/<exp_*>.json` | `Experiment` | Retro + tested Rule or weak dimension |

`Rubric` requires unique dimensions whose weights sum to exactly 100. `Rule` stores source Pattern,
scope, conditions, evidence/experiment counts, status and version; `validated` additionally requires
human approval metadata.

`ScoreResult.total_score` must equal the weighted dimension contributions. A score contains
evidence IDs and separate missing/risk fields; it is not a prediction.

`Prediction` requires ordered non-negative P25/P50/P75 intervals, a canonical `input_hash`,
Rubric/Rule versions, assumptions and `immutable: true`. Its directory ID must equal the stable ID
derived from that input hash. `Publication` is likewise content-addressed and immutable.
Its publication time must match the normalized video when present and must follow prediction
creation.

`Retro` records the selected normalized metric snapshot, per-metric error and interval position,
disjoint supported/counterexample Rule sets, external factors, lessons, pending Rule/Rubric change
proposals, and proposed experiments. Proposals never overwrite source Rule/Rubric files.
Materially mistimed, promoted, or Robust-outlier snapshots are retained as observations but cannot
produce Rule/Rubric change proposals.

## Phase 6 local media artifacts

| Path | Contract | Identity |
|---|---|---|
| `raw/media/<sha256>.<ext>` | immutable local media bytes | SHA-256 |
| `raw/vision-outputs/<sha256>.json` | optional offline Provider result | SHA-256 |
| `analyses/media/<video>/<mda_*>/media-analysis.json` | `MediaAnalysis` | media/features/config/provider result |
| `analyses/media/<video>/<mda_*>/timeline.json` | shot/keyframe/audio/vision timeline | analysis ID |
| `analyses/media/<video>/<mda_*>/keyframes/<key_*>.jpg` | frame evidence | shot + timestamp + media hash |
| `analyses/media/<video>/<mda_*>/evidence-index.json` | `MediaEvidenceIndex` | timestamp evidence |
| `normalized/media_features.parquet` | `MediaFeatureRecord` | `mdf_*` from analysis ID |

Shots require ordered non-negative intervals and exact durations. Keyframes cite one shot, timestamp,
local path, and SHA-256. OCR cites an existing shot/keyframe and interval. Missing decoder/audio/
visual information remains `null`, `skipped`, or absent; it is never represented as observed zero.

Account-level media enrichment adds strict artifacts without adding a new normalized table:

| Path | Contract | Identity |
|---|---|---|
| `analyses/accounts/<account>/media-enrichments/<ame_*>/enrichment.json` | `AccountMediaEnrichment` | source batch + downstream analysis IDs |
| `analyses/accounts/<account>/media-enrichments/<ame_*>/warnings.json` | warning list | enrichment ID |

`AccountMediaEnrichment` links a retained Provider batch SHA-256 to 1–10
`VideoMediaEnrichment` results. Each result may cite a media hash/analysis, local transcription
summary and raw hash, and single-video analysis. Signed source URLs are deliberately excluded from
the contract. `TranscriptionSummary.status` distinguishes `complete`, `reused`, `skipped`, and
`failed`; unknown model, language, hashes, or paths remain `null`.
`VideoMediaEnrichment.status` describes the acquisition/media/transcription chain, while
`text_analysis_status` independently records `complete` or bounded-local-heuristic `degraded`
semantic analysis.

## Phase 7 authorization and collaboration artifacts

| Path | Contract | Identity |
|---|---|---|
| user-supplied manifest | `AuthorizedExportManifest` | entity + platform + data SHA-256 + grant |
| user-supplied connector YAML/JSON | `FeishuBitableConfig` / `GoogleSheetsConfig` | connector ID |
| `raw/authorized-manifests/<sha256>.json` | validated manifest copy | manifest SHA-256 |
| `raw/collaboration/<connector>/<sha256>.json` | original provider pages | canonical payload SHA-256 |
| `collaboration/syncs/<sync_*>/sync.json` | `SyncReceipt` | connector + direction + entity + content |
| `collaboration/batches/<batch>/batch-result.json` | `BatchResult` | caller batch ID |
| `collaboration/schedules/snapshot-plan.json` | `SnapshotScheduleResult` | generated task set |
| `team.yaml` | `TeamConfig` | stable team ID |

`AuthorizationGrant` carries an explicit connector, confirmer, timezone-aware timestamp, exact
canonical resource reference, read/write scopes, and optional expiry. It never contains token
material. Feishu grants use `bitable:<app-token>/<table-id>` and Google grants use
`sheets:<spreadsheet-id>/<range>` so a grant for one table cannot authorize another. Connector
configs accept only uppercase `token_env` names; Feishu hosts are restricted to official
Feishu/Lark domains and Google Sheets uses its fixed v4 API host.

Pulled provider rows are not normalized directly: the original pages are preserved, then the rows
enter the existing mapping, Pydantic, quality, staging, deduplication, and Parquet pipeline. Pushes
read only normalized Parquet. Batch errors use the standard JSON error object per task, and a
non-dry result returns its `artifact_path`. Snapshot tasks are `future`, `due`, or `available` and
do not claim that platform collection occurred.

## Phase 8 account-homepage collection artifacts

| Path | Contract | Identity |
|---|---|---|
| CLI request | `AccountCollectionRequest` | URL + optional count limit + sort + bounded comment options + Provider |
| Provider result | `AccountCollectionBatch` | strict provider-neutral batch |
| `raw/account-collections/<provider>/<sha256>/provider-batch.json` | full batch and original pages | canonical payload SHA-256 |
| `raw/account-collections/<provider>/<sha256>/accounts.json` | `CollectedAccount[]` | Provider account ID |
| `raw/account-collections/<provider>/<sha256>/videos.json` | `CollectedVideo[]` | Provider video ID |
| `raw/account-collections/<provider>/<sha256>/metrics.json` | `CollectedMetricSnapshot[]` | video ID + collection time |
| `raw/account-collections/<provider>/<sha256>/comments.json` | optional `CollectedComment[]` | Provider comment ID |

`AccountCollectionRequest` allows only HTTPS `douyin.com` hosts, no URL credentials, and no custom
port. `count=null` is the default and means “continue until the Provider reports that the homepage
is exhausted”; an explicit count from 1 through 20,000 is an optional limit. Full-homepage mode has
a 1,000-page/20,000-video emergency guard, repeated-cursor detection, and a visible warning if the
guard rather than Provider exhaustion stops collection. The default Provider is `mediacrawler`;
`tikhub` is an explicit alternative. Comment sampling defaults to 10 top-level comments for each
of at most three high-comment collected videos, is capped at 20 comments for each of at most 10
videos, and can be disabled with `comments_per_video=0`. `Collected*` models contain only canonical
fields accepted by the offline importer; Provider-specific execution remains in
`collection/mediacrawler.py` or `collection/providers.py`, while canonical aliases stay
centralized in the collection mapping helpers.

Unknown public fields stay `null`. In particular, the current follower count is not substituted for
`follower_count_at_publish`, and missing completion/watch-time data is not fabricated. The full
Provider response is preserved before canonical rows enter the existing immutable import,
Pydantic, staging, deduplication, Parquet, and evidence pipeline.

Raw Provider comment pages may contain public usernames and source identifiers. Canonical
`CollectedComment` rows retain only an `author_hash`; the importer and Phase 4 redaction pipeline
remain the privacy boundary for normalized and reported comment data.
