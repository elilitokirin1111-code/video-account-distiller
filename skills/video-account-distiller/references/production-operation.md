# Production operation

## Installation acceptance

Prefer a wheel from a tagged GitHub Release over an editable repository install. Verify the
published SHA-256, install into a new Python 3.11+ environment, then run:

```bash
distiller --version
distiller doctor --json
```

Require the expected package version, `python_supported: true`, `capabilities.core: true`, and
`ok: true`. Local media is optional unless the requested workflow needs it. Feishu and Google
capabilities remain false until their token environment variables are present.

## Project acceptance

```bash
distiller doctor --project <dir> --json
distiller validate --project <dir> --json
distiller status --project <dir> --json
```

`doctor` is read-only; `validate` intentionally records an auditable run. Confirm project
readability/writability, zero validation errors, expected normalized counts, and traceable output
paths. Do not interpret a successful raw import as normalized readiness.

## Real work environment

For a first operational acceptance, use a dedicated project and authorized copies of representative
exports/media. Exercise import, validation, normalization, metrics, sample, report, comment
analysis, distillation, and local media where applicable. Keep the source data and generated project
outside Git. Record only non-sensitive counts, versions, statuses, and defect outcomes.

Certify live Feishu/Google integrations separately against a dedicated test table. Perform an
authorized read first, review dry-run output, write one controlled row, and read it back before any
production-table write.
