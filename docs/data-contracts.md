# Data contracts

Core normalized schema version: `0.1.0`. Phase 2 analysis artifact schema version: `0.2.0`.
Phase 3 transcript/text-analysis schema version: `0.3.0`.

The authoritative planning dictionary is `docs/planning/04_DATA_SCHEMA.md`; executable contracts
are Pydantic models in `src/video_account_distiller/models/core.py` and reject unknown fields.
Phase 2 contracts are in `src/video_account_distiller/models/analysis.py` and use the same strict
unknown-field policy. Phase 3 contracts are in `models/text_analysis.py`.

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

Version `0.3.0` does not rewrite existing accounts, videos, metrics, comments, derived metrics,
samples, or reports. Existing project config/state files remain valid because new model policy and
timestamps have defaults. Projects gain an optional `transcripts.parquet` table and new `vta_*`
analysis artifacts.

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
