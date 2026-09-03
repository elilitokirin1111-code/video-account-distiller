# OpenKB curated knowledge workflow

Use this reference only for the optional OpenKB sidecar. Distiller remains the source of truth.

## Boundary

- Export only from `AnalysisContextService`, reports, analyses, and approved `knowledge-base/`
  artifacts.
- Write only to `knowledge-outbox/openkb/`.
- Never let OpenKB scan the project root, `raw/`, `normalized/`, credentials, browser profiles,
  signed URLs, or media files.
- Never export raw comment text. The comment section contains aggregate analysis only.
- Treat OpenKB answers as derived synthesis. Important claims must resolve to Distiller
  `source_paths` or embedded evidence IDs.
- OpenKB compilation and query may invoke the model configured inside OpenKB. Require explicit
  `--confirm-model-processing` for every real sync or query.

## Configuration

Run OpenKB as a separate process and environment:

```bash
openkb-web --host 127.0.0.1 --port 7566
```

Distiller settings come from environment variables:

```text
DISTILLER_OPENKB_BASE_URL=http://127.0.0.1:7566
DISTILLER_OPENKB_KB=distiller-project
DISTILLER_OPENKB_API_TOKEN=<optional local token>
```

The token value is never written to the project. Plain HTTP is accepted only for loopback.
Remote targets require HTTPS and a bearer token.

## Sequence

1. Ensure the account has normalized data and useful report/analysis artifacts.
2. Preview the curated document:

   ```bash
   uv run distiller knowledge openkb export --project <dir> \
     --account <account-id> --dry-run --json
   ```

3. Inspect `manifest.source_paths`, `redacted_fields`, `byte_size`, and limitations.
4. Preview sync without contacting OpenKB:

   ```bash
   uv run distiller knowledge openkb sync --project <dir> \
     --account <account-id> --dry-run --json
   ```

5. Confirm the OpenKB KB name, target, model provider, cloud/local behavior, and likely cost.
6. Perform the one-way sync:

   ```bash
   uv run distiller knowledge openkb sync --project <dir> \
     --account <account-id> --confirm-model-processing --json
   ```

7. Inspect local and optional remote status:

   ```bash
   uv run distiller knowledge openkb status --project <dir> \
     --account <account-id> --json
   uv run distiller knowledge openkb status --project <dir> \
     --account <account-id> --remote --json
   ```

8. Query compiled knowledge only after confirmation:

   ```bash
   uv run distiller knowledge openkb query \
     "Compare the recurring content patterns and their counterexamples." \
     --project <dir> --confirm-model-processing --json
   ```

9. Verify important answer claims against the cited Distiller paths/evidence before acting.

## Idempotence

- The export payload excludes volatile generation time and uses a canonical SHA-256 hash.
- Re-exporting unchanged analysis does not rewrite the Markdown document.
- Re-syncing the same payload to the same target is skipped locally without a model call.
- A changed payload removes the previous document from the same OpenKB target before upload.
- `--force` deliberately recompiles an unchanged document and therefore still requires
  confirmation.
- Switching to a different OpenKB target does not attempt to delete data from the old target.

## REST routes

```text
POST /api/projects/{project}/knowledge/openkb/accounts/{account}/export
POST /api/projects/{project}/knowledge/openkb/accounts/{account}/sync
GET  /api/projects/{project}/knowledge/openkb/accounts/{account}/status
POST /api/projects/{project}/knowledge/openkb/query
```

Sync and query run through the persistent API task contract. Poll `/api/tasks/{task_id}`.
The API reads OpenKB connection settings from environment variables and does not accept an
arbitrary base URL in request bodies.

## Failure handling

- `E_PROVIDER_COST_CONFIRMATION_REQUIRED`: preview or obtain approval, then pass the confirmation
  flag.
- `E_ADAPTER_AUTH`: set the configured token environment variable; do not paste the value into
  chat, logs, YAML, or JSON.
- `E_ADAPTER_RESPONSE`: check that `openkb-web` is running, the KB API version matches the
  documented contract, and the target is reachable.
- `E_RATE_LIMIT`: wait before retrying; do not increase retry counts without reviewing model cost.
- `E_RAW_INTEGRITY`: inspect `knowledge-outbox/openkb/manifest.json` or `sync-state.json`; do not
  silently overwrite malformed state.
- Size-limit failure: reduce `--max-video-analyses` or export a narrower period rather than raising
  the limit without review.
