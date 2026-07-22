# Development

## Environment

The package supports Python 3.11+. This repository pins Python 3.14 for reliable editable installs
on its non-ASCII Windows workspace. Python 3.11 is tested in CI; on a non-ASCII Windows path use
`uv sync --no-editable` if the editable `.pth` is not loaded.

```bash
uv sync
uv run distiller --help
```
## Quality gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
uv build
```

Pytest disables sockets. Tests must use `tests/fixtures/` or temporary directories and must not
contact any network service.

## Test layers

- `tests/unit/`: formulas, models, parsing, IDs, project state, sampling, and report statistics.
- `tests/contract/`: CLI JSON/error contract, platform mapping, Phase 2 commands, and DuckDB guard.
- `tests/integration/`: full file-to-Parquet pipeline, idempotence, invalid rows, custom mappings,
  cross-platform warnings, and raw integrity.
- `tests/golden/`: stable performance bands plus a 30-video, three-pillar Phase 2 sample-coverage
  fixture with outliers and promotion.

## Large offline fixture

Generate 100,000 rows without committing the result:

```bash
uv run python tools/generate_large_fixture.py --output ./tmp/large-fixture --rows 100000
```

Initialize a temporary project, import `accounts.csv` and `videos.csv`, normalize, and inspect
counts with `distiller status --json`. Generated files remain under ignored `tmp/`.

## Adding behavior

1. Read `AGENTS.md` and planning sources.
2. Record contract tradeoffs in `docs/implementation-decisions.md`.
3. Add or update Pydantic models and tests first.
4. Keep platform logic behind adapters.
5. Preserve raw inputs and `None` semantics.
6. Run all quality gates.
7. Update `docs/release-notes.md` under `Unreleased`.

## Phase 2 smoke test

After the normal import/normalize/metrics sequence:

```bash
uv run distiller sample --project ./demo-project --account <acc_id> --size 40 --json
uv run distiller report --project ./demo-project --account <acc_id> --json
uv run distiller status --project ./demo-project --json
```

Verify all report `evidence_id` and finding `evidence_ids` values exist in `evidence-index.json`.
Dry runs must not create sample or report files.

## Skill validation

Run `skills-ref validate skills/video-account-distiller` when available. The repository-compatible
fallback is:

```bash
python /path/to/skill-creator/scripts/quick_validate.py skills/video-account-distiller
```
