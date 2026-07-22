# Scoring, prediction, publication, and Retro

Phase 5 closes the offline learning loop from a proposed script to an observed account-local
snapshot. It does not collect platform data and does not guarantee performance.

## Workflow

```text
account distillation + Pattern evidence
                 │
                 ▼
candidate Rules (versioned, low maturity)
                 │
script ──► nine-dimension Rubric score
                 │
                 ▼
account-local P25/P50/P75 prediction (immutable)
                 │
                 ▼
normalized publication video + metric snapshot
                 │
                 ▼
Retro ──► error + support/counterexample + pending proposals + next experiment
```

## Script scoring

Run scoring only after the account has normalized metrics and an account distillation:

```bash
uv run distiller score --project <dir> --account <account-id> \
  --script <script.md> --target-pillar <pillar> --planned-publish-hour 9 --json
```

The default Rubric totals 100 points:

| Dimension | Weight |
|---|---:|
| Account match | 15 |
| Audience need | 15 |
| Topic strength | 15 |
| Hook | 15 |
| Structure and value release | 15 |
| Credibility and evidence | 10 |
| Interaction and CTA | 5 |
| Production feasibility | 5 |
| Risk control | 5 |

Every score includes the raw dimension score, weight, weighted contribution, rationale, missing
items, matched Pattern/Rule IDs, risks, evidence index, warnings, input hashes, and run ID. The
script is copied byte-for-byte to `raw/candidates/` under its SHA-256; the candidate record points
to that immutable copy.

Phase 4 Patterns become versioned `candidate` Rules. They keep their source Pattern, scope,
evidence count, confidence, expected direction, and version. Candidate Rules can only make a small
bounded adjustment to one dimension. A score is a checklist, not a prediction.

## Immutable prediction

```bash
uv run distiller predict --project <dir> --account <account-id> \
  --script <script.md> --target-pillar <pillar> --target-age-hours 72 --json
```

Prediction first reuses or creates the score. For each configured metric it selects each video's
eligible snapshot nearest the requested target age from the same account, removes promoted and
Robust-outlier records, and requires at least three non-null observations. It computes empirical
P25/P50/P75 and applies a bounded, documented adjustment from the script score. A poorly aligned
baseline is exposed in warnings and lowers confidence.

`Prediction` records its target age, intervals, confidence, positive/negative factors,
uncertainties, assumptions, Rubric/Rule versions, canonical input hash and `immutable: true`.
`pred_*` is content-addressed from the inputs. Repeating identical inputs reuses the file; changing
the script, baseline, target age, Rubric, or Rule version creates a new ID. No command updates an
existing prediction.

The first implementation predicts `views` and `engagement_rate_by_view` when each metric has enough
eligible account-local history. It never compares raw values across platforms or accounts.

## Publication registration and snapshot plan

After publication, import and normalize the real video record, then run:

```bash
uv run distiller publish --project <dir> --prediction <pred-id> \
  --video <video-id> --json
```

The video must belong to the prediction account and target platform. Its normalized publication
time must follow the prediction creation time; an explicit `--published-at` cannot contradict the
normalized record. Publication stores the candidate/prediction linkage, normalized video,
URL/time, notes, immutable input hash, and snapshot plan. Default checkpoints are T+1h, T+24h,
T+3d, and T+7d. Registration never invents metric values.

Import later snapshots through `distiller import metrics`, then run `normalize` and `metrics` for
the account. Existing Phase 1 contracts remain the source of actual data.

## Retro

```bash
uv run distiller retro --project <dir> --publication <pub-id> --snapshot t3d --json
```

Supported labels are `t1h`, `t24h`, `t3d`, and `t7d`; use `--target-age-hours` for another age.
Retro selects the normalized snapshot nearest the requested age and warns when the difference is
outside tolerance. A materially mistimed, promoted, or Robust-outlier snapshot remains visible for
observation, but all matched Rules are marked inconclusive and no Rule/Rubric proposal is created
from that confounded evidence.

For every predicted metric Retro records the actual value, predicted P50, absolute/relative error,
and whether the actual is below P25, inside P25–P75, above P75, or unknown. Matched Rules are
classified as supported, counterexample, or inconclusive using the observed account-local band.
Promoted traffic, outliers, snapshot mismatch, and unobserved distribution events remain visible.

Retro outputs:

- `retro.json`, Markdown, evidence index, and warnings;
- an immutable knowledge-base review copy;
- versioned Rule change proposals with `approval_status: pending`;
- paired small Rubric change proposals when prediction error is large;
- proposed experiments with minimum sample requirements.

It never modifies the source Rule, current Rubric, or linked prediction. One result cannot produce
a Level 4 validated rule. Approval and multi-round evidence remain future human-governed actions.

## Validation and status

`distiller validate` checks candidate raw hashes, Rubric totals, Rule paths/versions, score and
prediction evidence companions, immutable IDs, publication links, Retro review copies, and next
experiment files.

`distiller status` reports score, prediction, publication and Retro counts, pending Rule/Rubric
proposal counts, the latest Phase 5 timestamps, and a bounded recent-video list containing the
canonical and platform video IDs needed by later commands.
