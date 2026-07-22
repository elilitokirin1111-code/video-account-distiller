# Adapter guide

## Supported Phase 1 sources

`FileAdapter` accepts UTF-8/UTF-8-BOM CSV, JSON, JSONL, and NDJSON. A JSON root may be one object,
an array of objects, or `{ "records": [...] }`.

Supported platform identifiers are `douyin`, `xiaohongshu`, `wechat-channels`, `bilibili`,
`tiktok`, `youtube`, and `instagram`. These select field mappings only; no platform network is
contacted.

## Field mapping order

1. Explicit user `FieldMapping` supplied with `--mapping`.
2. Packaged platform aliases in `resources/platform_mappings.yaml`.
3. Canonical field names and common aliases.
4. Stable `E_FIELD_MAPPING_REQUIRED` error with available and missing fields.

Example mapping:

```yaml
schema_version: "0.1.0"
entity: accounts
platform: douyin
fields:
  platform_account_id: custom_uid
  display_name: custom_name
  follower_count_current: custom_fans
  snapshot_at: custom_snapshot
timezone: Asia/Shanghai
mapping_version: custom-1
```

Use it with:

```bash
distiller import accounts --project ./research --file accounts.csv \
  --platform douyin --mapping mapping.yaml --json
```

## Adding an offline adapter

1. Implement `SourceAdapter` from `adapters/base.py`.
2. Keep platform field aliases inside the adapter or centralized mapping resources.
3. Return dictionaries only; send them through Pydantic before persistence.
4. Preserve the original source and hash it before transformation.
5. Add contract tests for source validation, mapping, missing values, and malformed input.
6. Do not add network behavior to the analysis kernel.

## Transcript adapter

`TranscriptImportService` accepts SRT, VTT, TXT, JSON, and JSONL against an existing normalized
`video_id`. It is separate from platform field mappings because subtitle cues use timing/text
contracts rather than account export columns. JSON accepts `start_ms`/`end_ms` or Whisper-style
`start`/`end` seconds. Unknown TXT timing remains `null`.

Sources are copied to `raw/imports/transcripts/`, validated into `staging/transcripts/`, and
normalized to `transcripts.parquet`. This adapter performs no speech recognition and does not read
media files.

## Comment privacy boundary

Comment exports use the normal file Adapter and platform mappings. `author_id` is converted to a
SHA-256 `author_hash` during import; the raw identifier never enters normalized Parquet. Phase 4
then creates a separate analysis copy that redacts common direct identifiers from comment text.
Adapters must not pre-clean or overwrite the immutable source because validation and replay depend
on exact source bytes.

## Phase 5 publication snapshots

Publication registration does not add a new platform Adapter. Import the published video and every
actual T+ metric snapshot through the existing video/metrics file Adapter, then normalize and
recalculate metrics. `retro` reads only normalized `MetricSnapshot`/`DerivedMetrics`, selects the
nearest requested age, and preserves the actual snapshot ID/time. Adapters must not synthesize an
exact T+ checkpoint when the export contains a later or earlier observation.

## Phase 6 local media adapter

`FFmpegMediaBackend` implements the mockable `MediaBackend` protocol for user-provided local files.
It is not a platform adapter: it receives no credentials, does not resolve platform URLs, and never
opens a browser. Tests inject a fake backend rather than requiring system codecs. Alternative local
decoders must preserve metadata nulls, millisecond shot boundaries, deterministic keyframe
evidence, bounded audio decoding, and stable `MediaBackendFailure` behavior.

## Phase 7 authorized and collaboration adapters

`AuthorizedExportManifest` binds an entity/platform export to its SHA-256 and an explicit read
grant before handing it to the existing `ImportService`. This is the preferred path for platform
exports that do not require a live API.

`FeishuBitableAdapter` and `GoogleSheetsAdapter` implement the mockable `CollaborationAdapter`
contract. Both use fixed official API hosts, read tokens only from the configured environment
variable, validate a separate read/write grant, and pass pulled rows through the normal mapping and
Pydantic pipeline. Pushes read standardized Parquet rather than raw exports.

The HTTP executor is injectable. Contract tests use fake responses for pagination, malformed data,
HTTP 401/403, HTTP 429, retry exhaustion, and append responses; no test contacts a real service.
Identical completed pushes reuse a content-addressed Sync receipt to avoid duplicate appends.

See `authorized-collaboration-adapters.md` for connector Schemas, commands, batch manifests,
snapshot scheduling, team policy, and the complete compliance boundary. Authentication bypass,
CAPTCHA handling, stealth automation, scraping, or platform-control evasion remains prohibited.
