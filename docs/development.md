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

- `tests/unit/`: formulas, models, transcript/comment privacy, IDs, project state, sampling, reports,
  Rubric totals, prediction intervals, and Rule approval requirements.
- `tests/contract/`: CLI JSON/error contracts, platform mapping, blind provider prompts, retries,
  Phase 2/3/4/5 commands, and DuckDB guard.
- `tests/integration/`: full file-to-Parquet pipeline, idempotence, invalid rows, custom mappings,
  cross-platform warnings, raw integrity, transcript normalization, single-video analysis, comment
  needs, account distillation, Pattern counterexamples, transfer matrices, immutable predictions,
  publication linkage, and Retro proposals.
- `tests/golden/`: stable performance bands plus a 30-video, three-pillar Phase 2 sample-coverage
  fixture with outliers and promotion.
  Phase 3 Golden checks stable Hook, structure, CTA, emotion, and pillar labels.
  Phase 4 Golden checks content-cluster coverage, Pattern support, and counterexample retention.
  Phase 5 Golden checks dimension order/weights, interval ordering, Rule versions, and warnings.

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

## Phase 3 smoke test

After videos and metrics are normalized:

```bash
uv run distiller import transcripts --project ./demo-project --video <vid_id> \
  --file ./subtitle.srt --language zh-CN --json
uv run distiller normalize --project ./demo-project --json
uv run distiller analyze video --project ./demo-project --video <vid_id> \
  --model-output ./structured-output.json --json
uv run distiller validate --project ./demo-project --json
```

Verify `blind-analysis.json` contains no performance keys; every cited segment ID exists in
`evidence-index.json`; invalid model candidates retry; and degraded mode never produces a validated
account rule. The video argument may be an internal `vid_*` or a unique platform video ID.

## Phase 4 smoke test

After comments, videos, and metrics are normalized and metrics are calculated:

```bash
uv run distiller analyze comments --project ./demo-project --account <acc_id> --json
uv run distiller distill --project ./demo-project --account <acc_id> --json
uv run distiller validate --project ./demo-project --json
```

Verify comment artifacts contain no raw author IDs or direct identifiers; every need cluster and
Pattern evidence ID exists; every Pattern has support and a counterexample field; support and
counterexample sets are disjoint; and maturity never exceeds Level 1.

After distilling every account:

```bash
uv run distiller compare --project ./demo-project --target <acc_id> \
  --benchmarks <benchmark_id_1>,<benchmark_id_2> --json
```

Verify cross-platform items keep separate baselines and never compare raw views.

## Phase 5 smoke test

After the target account has a distillation and a UTF-8 script exists:

```bash
uv run distiller score --project ./demo-project --account <acc_id> \
  --script ./script.md --target-pillar <pillar> --json
uv run distiller predict --project ./demo-project --account <acc_id> \
  --script ./script.md --target-pillar <pillar> --target-age-hours 72 --json
```

Verify nine dimension weights total 100, candidate Rules remain low maturity, prediction quantiles
are ordered, baseline snapshot-age warnings are visible, and repeating identical inputs preserves
the same prediction bytes.

After importing and normalizing the published video and metric snapshots:

```bash
uv run distiller publish --project ./demo-project --prediction <pred_id> \
  --video <vid_id> --json
uv run distiller retro --project ./demo-project --publication <pub_id> \
  --snapshot t3d --json
uv run distiller validate --project ./demo-project --json
```

Verify publication time follows prediction creation, the prediction and source Rule files are
unchanged, every proposal remains `pending`, counterexamples are retained, experiment files exist,
and Phase 5 validation reports no errors. Also test a materially mistimed snapshot: its matched
Rules must be inconclusive and its Rule/Rubric proposal lists must be empty.

## Skill validation

Run `skills-ref validate skills/video-account-distiller` when available. The repository-compatible
fallback is:

```bash
python /path/to/skill-creator/scripts/quick_validate.py skills/video-account-distiller
```
