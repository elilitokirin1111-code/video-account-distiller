# Authorized collaboration adapters

## Safety gate

Require one of these before reading platform-derived data:

- a user-provided export plus `AuthorizedExportManifest`; or
- a connector config with an explicit unexpired `AuthorizationGrant` and a token environment-
  variable name.

Never store a token value in connector YAML, `team.yaml`, a prompt, a report, a run manifest, or Git.
Do not automate login, reuse browser cookies, solve CAPTCHA, scrape pages, or evade rate limits.

## Authorized export

Copy `assets/authorized-export.example.json`, replace its file path/hash/grant fields, and run:

```bash
uv run distiller import authorized-export --project <dir> \
  --manifest <manifest.json> --json
```

Use `--mapping` when columns are not canonical. Stop on a hash mismatch or missing/expired read
scope. The import preserves both the export and validated manifest. Then run `distiller normalize`
before analysis, querying, or a collaboration push; a successful raw import does not rebuild
Parquet automatically.

## Feishu Bitable and Google Sheets

Start from `assets/feishu-bitable.example.yaml` or `assets/google-sheets.example.yaml`. Keep only
the token's environment-variable name in the file, set the real value in the process environment,
and set `authorization.source_reference` to the exact canonical resource reference shown by the
asset (`bitable:<app-token>/<table-id>` or `sheets:<spreadsheet-id>/<range>`). Then run:

```bash
uv run distiller sync pull --project <dir> --connector-config <connector.yaml> \
  --entity <accounts|videos|metrics|comments> --platform <platform> --json

uv run distiller sync push --project <dir> --connector-config <connector.yaml> \
  --entity <accounts|videos|metrics|comments> --dry-run --json
```

For pull, add `--mapping` if the first provider row does not use canonical names. A pull dry run
still performs an authorized remote read, but changes no project files. A push dry run reads local
Parquet and performs no remote write. Remove `--dry-run` only after reviewing row count, target,
columns, scope, and retention policy.

Expect:

- `E_ADAPTER_AUTH` for a missing/expired grant, missing token environment value, or HTTP 401/403;
- `E_RATE_LIMIT` when HTTP 429 remains after bounded retry;
- `E_ADAPTER_RESPONSE` for malformed or unexpected provider responses.

Do not retry those errors manually in a tight loop. Correct permission/configuration or wait for the
provider window.

## Batch

Start from `assets/batch.example.yaml`. Use paths relative to the batch file when convenient.

```bash
uv run distiller batch run --project <dir> --file <batch.yaml> --dry-run --json
```

Supported operations are `authorized-export`, `sync-pull`, `sync-push`, and `snapshot-plan`.
Review each task result independently. Use `continue_on_error: false` when later tasks must not run
after a failure.
For a non-dry batch, the JSON result includes `artifact_path`; the default is
`collaboration/batches/<batch-id>/batch-result.json`.

## Snapshot plan

```bash
uv run distiller snapshot plan --project <dir> --json
```

Treat `due` tasks as requests for a later explicitly authorized metrics import. `future` is not due;
`available` means a normalized snapshot already meets the target age. This command does not collect
platform data or install a scheduler.

## Team policy

```bash
uv run distiller team init --project <dir> --owner <member-id> --json
uv run distiller team validate --project <dir> --json
```

Edit `team.yaml` to add members, owner/editor/viewer roles, connector policies, and token environment
names. Keep at least one owner. Grant members only known connector IDs. Do not place credentials or
personal access tokens in the file.

## Validate and report

After a non-dry operation, run:

```bash
uv run distiller validate --project <dir> --json
uv run distiller status --project <dir> --json
```

Report the grant ID, connector ID, direction, entity, raw/source hash, accepted/rejected row count,
Sync/Batch paths, warnings, and next safe action. Never print the token or authorization header.
