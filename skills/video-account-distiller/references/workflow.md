# Phase 0/1/2 workflow

## Sequence

1. Confirm the task uses offline user-provided exports.
2. From the repository root, initialize a project with `uv run distiller init`.
3. Import accounts before videos, videos before metrics/comments where practical.
4. Inspect each import receipt and paired quality reports.
5. Run `uv run distiller validate` to verify raw hashes and staging schemas.
6. Run `uv run distiller normalize` to rebuild Parquet.
7. Run `uv run distiller status` and capture internal account IDs.
8. Run `uv run distiller metrics` separately for each account.
9. Run `uv run distiller sample` for a traceable stratified sample.
10. Run `uv run distiller report` for account-health JSON, Markdown, evidence, and warnings.
11. Query with DuckDB only after normalization.

## Idempotence

The same entity/platform/input hash returns the existing receipt and changes nothing. A dry run
must not change state, raw data, staging, Parquet, or manifests. Repeated normalization rebuilds the
same record population; repeated metrics replace that account's derived rows instead of appending
duplicates. Samples and reports use content-addressed IDs and reuse unchanged artifacts.

## Project evidence

- `.distiller-state.json`: imports and latest successful stages.
- `raw/imports/`: exact source bytes named by SHA-256.
- `staging/`: validated canonical JSONL.
- `normalized/`: Parquet source of analytical truth.
- `runs/<run-id>/manifest.json`: command, hashes, counts, warnings, outputs.
- `runs/<run-id>/quality-report.{json,md}`: data-quality evidence.
- `analyses/accounts/<account-id>/samples/<sample-id>/sample-manifest.json`: selection reasons and
  coverage.
- `reports/accounts/<account-id>/<report-id>/`: JSON, Markdown, evidence index, and warnings.

## Failure handling

Use the stable code in JSON output. Do not retry malformed data blindly. For mapping failures, show
missing and available fields and request a mapping file. For partial invalid files, preserve valid
rows and direct the user to the quality report. For raw hash mismatch, stop before normalization.
