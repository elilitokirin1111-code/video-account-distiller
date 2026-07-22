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

## Future authorized adapters

A live adapter must be separately scoped, authorized, rate-limited, and contract-tested. It may use
an official API or user-provided export only. Authentication, CAPTCHA bypass, stealth automation,
or platform-control evasion is prohibited.
