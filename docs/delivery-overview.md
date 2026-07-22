# Phase 0/1/2 delivery overview

## What this delivery provides

Version `0.2.0` establishes a production-oriented, offline data and reporting kernel plus a standard
Agent Skill for video-account research. It imports user exports, preserves originals, maps and
validates fields, deduplicates records, writes Parquet, exposes DuckDB views, calculates
account-local robust metrics, reports project status through a stable Typer CLI, selects
representative samples, and generates traceable account-health reports.

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

## Verification evidence

The repository includes unit, contract, integration, and golden tests; four offline fixture groups;
a 100,000-row generator; Ruff, mypy, pytest, and Skill validation commands; and a GitHub Actions
workflow for Python 3.11 and 3.14.

Final local acceptance on 2026-07-22 produced the following evidence:

- Ruff passed with no findings; mypy passed across 57 source and test files.
- All 39 offline tests passed with 94.50% statement coverage.
- The official Skill quick validator accepted the Skill; wrapper smoke tests cover data, sampling,
  report, and status routes.
- A deterministic 100,000-video fixture imported all 100,000 rows in about 4.4 seconds and rebuilt
  the normalized Parquet tables in about 4.4 seconds on the delivery workstation, with zero rejected
  rows and zero data-quality warnings. Timings are indicative, not a cross-machine performance SLA.

## Not delivered yet

Phase 3+ work remains explicit: subtitle/video semantic analysis, comment intent, full account
distillation, pattern evidence, content scoring, prediction/retro, multimodal analysis, and
authorized platform or collaboration adapters.

## Handoff

Read `README.md` for Quick Start, `docs/data-contracts.md` for machine contracts,
`docs/adapter-guide.md` for field mappings, `docs/privacy-and-compliance.md` for boundaries, and
`docs/release-notes.md` for current and future updates.
