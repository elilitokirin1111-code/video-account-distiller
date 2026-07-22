# Phase 0/1/2/3/4/5/6 delivery overview

## What this delivery provides

Version `0.6.0` establishes a production-oriented, offline data and reporting kernel plus a standard
Agent Skill for video-account research. It imports user exports, preserves originals, maps and
validates fields, deduplicates records, writes Parquet, exposes DuckDB views, calculates
account-local robust metrics, reports project status through a stable Typer CLI, selects
representative samples, and generates traceable account-health reports.
It also imports subtitles, performs blind Schema-validated text analysis, and produces traceable
single-video reports before attaching account-local performance context.
It now analyzes redacted comments, clusters audience needs, produces account-local Patterns with
support and counterexamples, writes account distillation/knowledge artifacts, and builds
conservative benchmark transfer matrices.
It now scores scripts against a versioned nine-dimension Rubric, records immutable account-local
prediction intervals, links predictions to normalized publications, and turns actual snapshots into
prediction errors, retained counterexamples, pending-only change proposals, and next experiments.
It now also analyzes local media through FFmpeg/FFprobe, builds a timestamped shot/keyframe/audio
timeline, accepts optional schema-validated visual/OCR evidence, and exposes aggregate media
features through Parquet and DuckDB without uploading the file.

## Key user outcomes

- Start a repeatable research project without opening a platform session.
- Trace every normalized record back to its source hash and run.
- Keep unknown metrics as `null` and reject impossible negatives.
- Avoid direct raw comparisons across platforms.
- Query normalized data locally with DuckDB.
- Rank the latest video snapshots relative to the same account using Median, MAD, Robust Z-score,
  configurable weights, and S/A/B/C/D bands.
- Select a deterministic sample covering performance, recency, content type, duration, promotion,
  and outliers.
- Compare high, middle, and low account-local cohorts without claiming causality.
- Resolve every reported statistic and finding through a machine-readable evidence index.
- Import SRT/VTT/TXT/JSON subtitles without inventing missing timing.
- Extract Hook, structure, CTA, emotion, and content-pillar labels without seeing performance data.
- Retry invalid model output or degrade visibly to conservative low-confidence local analysis.
- Trace every cited subtitle segment and performance value to normalized and raw evidence.
- Redact common direct identifiers from comment analysis copies without altering raw comments.
- Turn comment intent, pain, objections, and purchase questions into traceable content opportunities.
- Preserve support samples, counterexamples, paid/outlier confounders, maturity, and confidence for
  every Pattern.
- Produce actionable account experiments without claiming causality or a validated rule.
- Keep benchmark and platform baselines separate while reviewing what can be tested or adapted.
- Score new scripts with visible dimensions, missing items, risks, and bounded low-maturity Rule
  influence.
- Save P25/P50/P75 predictions with assumptions, confidence, input hashes, and Rule/Rubric versions.
- Preserve prediction and publication records as append-only, content-addressed artifacts.
- Compare a real normalized snapshot with the prediction while retaining out-of-range results.
- Produce pending Rule/Rubric proposals and next experiments without silently changing policy.
- Preserve local media by SHA-256 and extract reproducible metadata, shots, keyframes, and bounded
  audio signal features.
- Keep visual/OCR unknown by default or attach only provider output that cites exact shot/keyframe
  timestamps.
- Degrade visibly when FFmpeg is unavailable, with an optional stable strict failure mode.

## Verification evidence

The repository includes unit, contract, integration, and golden tests; seven offline fixture groups;
a 100,000-row generator; Ruff, mypy, pytest, and Skill validation commands; and a GitHub Actions
workflow for Python 3.11 and 3.14.

Final local acceptance on 2026-07-22 produced the following evidence:

- Ruff passed with no findings; mypy passed across 98 source and test files.
- All 88 offline tests passed with 90.04% statement coverage.
- The official Skill quick validator accepted the Skill; wrapper smoke tests cover data, sampling,
  report, transcript, blind-analysis, local media, comment, distillation, comparison, score,
  prediction, publication, Retro, and status routes.
- A deterministic 100,000-video fixture imported all 100,000 rows in about 4.4 seconds and rebuilt
  the normalized Parquet tables in about 4.4 seconds on the delivery workstation, with zero rejected
  rows and zero data-quality warnings. Timings are indicative, not a cross-machine performance SLA.

## Not delivered yet

Phase 7 authorized platform and collaboration adapters remain explicit future work. The repository
does not include a cloud visual-model client or live collection. Level 4 approval remains
intentionally human-governed and requires repeated controlled evidence; Phase 5 produces only
pending proposals.

## Handoff

Read `README.md` for Quick Start, `docs/data-contracts.md` for machine contracts,
`docs/comment-and-account-distillation.md` for Phase 4 interpretation,
`docs/scoring-prediction-retro.md` for the Phase 5 learning loop,
`docs/local-media-analysis.md` for Phase 6 media evidence,
`docs/adapter-guide.md` for field mappings, `docs/privacy-and-compliance.md` for boundaries, and
`docs/release-notes.md` for current and future updates.
