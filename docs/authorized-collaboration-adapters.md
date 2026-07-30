# Authorized collaboration adapters

Phase 7 adds narrow, auditable collaboration interfaces. It does not add scraping, browser login,
CAPTCHA handling, cookie reuse, or an unrestricted platform client.

## Authorization model

Every source requires an `AuthorizationGrant` containing:

- a stable grant ID;
- the connector kind;
- who confirmed access and when;
- explicit `read` and/or `write` scopes;
- the exact canonical resource reference for live table connectors;
- an optional expiry.

The grant is evidence, not a credential. Connector files contain only a `token_env` name; the token
value must be supplied by the process environment and is never written to project state, receipts,
logs, reports, or team configuration.

Stable failures are:

- `E_ADAPTER_AUTH` / exit 16 for missing, expired, rejected, or insufficient authorization;
- `E_RATE_LIMIT` / exit 17 after bounded 429 retries are exhausted;
- `E_ADAPTER_RESPONSE` / exit 18 for malformed or unexpected provider responses.

## Authorized platform exports

Create a manifest next to a user-provided CSV/JSON/JSONL export:

```json
{
  "schema_version": "0.7.0",
  "entity": "accounts",
  "platform": "douyin",
  "data_file": "accounts.csv",
  "data_sha256": "<64-lowercase-hex>",
  "exported_at": "2026-07-22T08:00:00Z",
  "authorization": {
    "grant_id": "grant-douyin-export-20260722",
    "connector": "authorized-export",
    "confirmed_by": "content-owner",
    "confirmed_at": "2026-07-22T08:01:00Z",
    "scopes": ["read"],
    "source_reference": "Downloaded by the account owner",
    "expires_at": null
  }
}
```

Import only after the hash and grant validate:

```bash
uv run distiller import authorized-export --project ./demo-project \
  --manifest ./export/manifest.json --json
uv run distiller normalize --project ./demo-project --json
```

Add `--mapping mapping.yaml` for noncanonical columns. The original data enters the normal immutable
import pipeline; a validated manifest copy is retained under `raw/authorized-manifests/`.
The import receipt records `data_source_tier: authorized_private` and the grant ID.

`entity: metrics` accepts the v2 creator mapping for impressions, watch time, completion, profile
visits, follows, clicks, leads, orders, and revenue. `entity: audience_profiles` accepts the
versioned long-table contract:

```csv
account_id,snapshot_at,dimension,bucket,share,audience_count,sample_size,source_schema_version
account-1,2026-07-29T08:00:00Z,gender,female,0.62,,100,douyin-creator-profile/2026-07
```

`share` must be between 0 and 1. A segment requires either `share` or `audience_count`; missing
values remain null. Normalization writes `normalized/audience_profiles.parquet`.

## Feishu Bitable

Use a credential-free connector file:

```yaml
connector: feishu-bitable
connector_id: hotel-operations
app_token: bascn_xxx
table_id: tbl_xxx
token_env: FEISHU_BITABLE_TOKEN
api_base: https://open.feishu.cn
page_size: 500
authorization:
  grant_id: grant-feishu-hotel
  connector: feishu-bitable
  confirmed_by: team-owner
  confirmed_at: 2026-07-22T08:00:00Z
  scopes: [read, write]
  source_reference: bitable:bascn_xxx/tbl_xxx
  expires_at: null
retry:
  max_retries: 3
  base_seconds: 0.5
  timeout_seconds: 30
```

Set the token only in the environment, then pull or append normalized rows:

```bash
uv run distiller sync pull --project ./demo-project \
  --connector-config ./feishu.yaml --entity metrics --platform douyin --json

uv run distiller sync push --project ./demo-project \
  --connector-config ./feishu.yaml --entity metrics --dry-run --json
```

The adapter uses the documented Bitable records list and batch-create endpoints, follows page
tokens, and limits a create batch to 500 rows. See the official
[record list](https://open.larksuite.com/document/uAjLw4CM/ukTMukTMukTM/reference/bitable-v1/app-table-record/list)
and [batch create](https://open.larksuite.com/document/uAjLw4CM/ukTMukTMukTM/reference/bitable-v1/app-table-record/batch_create)
contracts.

After a successful non-dry pull, run `distiller normalize` before querying, analysis, or push. Raw
import success and normalized Parquet availability are deliberately separate states.

## Google Sheets

```yaml
connector: google-sheets
connector_id: hotel-sheet
spreadsheet_id: spreadsheet-id
range: Metrics!A:Z
token_env: GOOGLE_SHEETS_TOKEN
columns: [video_id, snapshot_at, views, likes, comments, shares, saves]
authorization:
  grant_id: grant-google-hotel
  connector: google-sheets
  confirmed_by: team-owner
  confirmed_at: 2026-07-22T08:00:00Z
  scopes: [read, write]
  source_reference: sheets:spreadsheet-id/Metrics!A:Z
  expires_at: null
retry:
  max_retries: 3
  base_seconds: 0.5
  timeout_seconds: 30
```

Pull treats the first row as unique, non-empty headers. Push appends rows in configured column order
using `valueInputOption=RAW` and `insertDataOption=INSERT_ROWS`. See the official Google Sheets
[`values.get`](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/get)
and [`values.append`](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/append)
contracts.

An identical completed push is content-addressed and reused instead of appending duplicates.
`--dry-run` validates local normalized data and never performs the remote write. A pull dry run still
performs an authorized remote read so field mapping can be validated, but does not change project
files.

## Batch tasks

Batch manifests support authorized exports, sync pull/push, and snapshot planning:

```yaml
schema_version: "0.7.0"
batch_id: batch-20260722
continue_on_error: true
tasks:
  - task_id: pull-metrics
    operation: sync-pull
    parameters:
      connector_config: ./feishu.yaml
      entity: metrics
      platform: douyin
  - task_id: publish-normalized-metrics
    operation: sync-push
    parameters:
      connector_config: ./google.yaml
      entity: metrics
  - task_id: plan-snapshots
    operation: snapshot-plan
```

```bash
uv run distiller batch run --project ./demo-project --file ./batch.yaml --dry-run --json
```

Each task has an isolated success/error result. `continue_on_error: false` stops after the first
failure. Non-dry batches return `artifact_path` and write a validated result under
`collaboration/batches/<batch-id>/`.

## Snapshot scheduling interface

```bash
uv run distiller snapshot plan --project ./demo-project --json
```

The command compares each immutable publication's T+ plan with normalized metric snapshots and
emits `future`, `due`, or `available` tasks plus `next_due_at`. It does not install a Windows task,
cron job, or collect data. An external scheduler may invoke this command and then run an explicitly
authorized metrics import.

## Team policy

```bash
uv run distiller team init --project ./demo-project \
  --owner owner-id --owner-name "Hotel Operator" --json
uv run distiller team validate --project ./demo-project --json
```

`team.yaml` contains roles and connector IDs only. At least one owner is required; duplicate members,
duplicate connectors, and unknown connector references fail validation. Keep actual token values in
the environment or an external secret manager.

## Evidence and validation

Pulls preserve original provider pages at
`raw/collaboration/<connector>/<sha256>.json`, then route mapped rows through the existing Pydantic
ingestion pipeline. Pushes read only standardized Parquet. `distiller validate` checks raw hashes,
sync IDs, batch IDs, snapshot plans, and team policy Schema. `distiller status` reports collaboration
artifact counts without exposing credentials.
