# Scoring, prediction, publication, and Retro

## Preconditions

1. Normalize account, video, and metric exports.
2. Calculate account-local derived metrics.
3. Distill the target account so every scoring Rule has a source Pattern, support, and
   counterexamples.
4. Use a UTF-8 Markdown or text script. Specify `target_pillar` when known.

## Rubric and Rule behavior

The default Rubric has nine visible dimensions totaling 100 points: account match, audience need,
topic strength, Hook, structure/value release, credibility/evidence, interaction/CTA, production
feasibility, and risk control. Keep every dimension visible; never return only a total.

Phase 4 Patterns materialize as versioned `candidate` Rules. Candidate and experimental Rules may
only make a bounded score adjustment. Only a human-approved `validated` Rule may have full Rubric
influence. Do not infer validation from support count alone.

`distiller score` creates an immutable raw copy of the script plus a ContentCandidate, Rubric,
Rules, ScoreResult, Markdown report, evidence index, warnings, and run manifest. It does not create
a prediction.

## Prediction contract

`distiller predict` first reuses or creates the score, then selects each video's eligible snapshot
nearest the requested age and calculates same-account P25/P50/P75. Exclude promoted and
Robust-outlier observations from the baseline. Require at least three observations for a metric,
expose age mismatch, and lower confidence for small or poorly aligned samples.

The prediction records:

- target snapshot age;
- account-local metric intervals;
- confidence and uncertainty;
- Rubric and Rule versions;
- assumptions and positive/negative factors;
- a canonical input hash and `immutable: true`.

Never overwrite a prediction after publication. A changed script, baseline, Rubric, Rule version,
or target age must create a different `pred_*` record.

## Publication and snapshots

Register only a normalized video belonging to the prediction account and target platform. The
publication stores the linked candidate/prediction, video, URL/time, and planned T+1h, T+24h,
T+3d, and T+7d snapshots. The normalized publication time must follow prediction creation, and an
explicit time must not contradict the normalized record. It does not fabricate missing metrics.

Import actual snapshots with `distiller import metrics`, normalize, and recalculate account metrics.
Retro selects the normalized snapshot nearest the requested age and warns when the difference is
outside tolerance. Treat a materially mistimed, promoted, or Robust-outlier snapshot as
confounded: retain its actual values, mark matched Rules inconclusive, and do not generate
Rule/Rubric change proposals from it.

## Retro and approval boundary

Retro compares actual values with P25/P50/P75, retains out-of-range results, and classifies matched
Rules as supported, counterexample, or inconclusive from the observed account-local performance
band. One publication cannot validate causality.

Retro may propose:

- a new version and status for a Rule;
- a paired, small Rubric weight adjustment;
- a controlled next experiment.

All changes must remain `pending`. Do not write the proposed Rule version or modify the current
Rubric automatically. Preserve source Rule files and the original prediction byte-for-byte.

## Interpretation warnings

- Score is a checklist, not a prediction.
- Prediction is a historical account-local interval, not a guarantee.
- Snapshot age, paid traffic, outliers, execution differences, trends, and platform distribution
  can invalidate comparison.
- Rule support from a Retro is evidence for another experiment, not automatic Level 4 validation.
