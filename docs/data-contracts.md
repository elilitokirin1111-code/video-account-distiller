# Data contracts

Schema version: `0.1.0`.

The authoritative planning dictionary is `docs/planning/04_DATA_SCHEMA.md`; executable contracts
are Pydantic models in `src/video_account_distiller/models/core.py` and reject unknown fields.

## Core tables

| Parquet table | Pydantic model | Primary identity |
|---|---|---|
| `accounts.parquet` | `Account` | `account_id` / `record_id` |
| `account_snapshots.parquet` | `AccountSnapshot` | `account_snapshot_id` |
| `videos.parquet` | `Video` | `video_id` / `record_id` |
| `metric_snapshots.parquet` | `MetricSnapshot` | `metric_snapshot_id` |
| `comments.parquet` | `Comment` | `comment_id` / `record_id` |
| `derived_metrics.parquet` | `DerivedMetrics` | stable ID from metric snapshot and schema |

All core records carry source platform/type/URI/record ID, collection and ingestion timestamps,
run ID, raw hash, schema version, and quality flags. Unknown values are `null`, never fabricated as
zero, empty string, or false.

## Stable IDs

Internal IDs are deterministic SHA-256 prefixes derived from platform and source identifiers:
`acc_`, `vid_`, `ms_`, `cmt_`, and `dm_`. Reimporting the same export yields the same record IDs.

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

There is no previous schema to migrate in version `0.1.0`. Future changes must increment
`schema_version`, document compatibility in release notes, and provide a deterministic migration
before existing Parquet or knowledge records are rewritten.
