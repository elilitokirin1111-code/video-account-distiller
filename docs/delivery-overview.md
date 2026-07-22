# Phase 0/1 delivery overview

## What this delivery provides

Version `0.1.0` establishes a production-oriented, offline data kernel and a standard Agent Skill
for video-account research. It imports user exports, preserves originals, maps and validates fields,
deduplicates records, writes Parquet, exposes DuckDB views, calculates account-local robust metrics,
and reports project status through a stable Typer CLI.

## Key user outcomes

- Start a repeatable research project without opening a platform session.
- Trace every normalized record back to its source hash and run.
- Keep unknown metrics as `null` and reject impossible negatives.
- Avoid direct raw comparisons across platforms.
- Query normalized data locally with DuckDB.
- Rank the latest video snapshots relative to the same account using Median, MAD, Robust Z-score,
  configurable weights, and S/A/B/C/D bands.

## Verification evidence

The repository includes unit, contract, integration, and golden tests; three offline fixture groups;
a 100,000-row generator; Ruff, mypy, pytest, and Skill validation commands; and a GitHub Actions
workflow for Python 3.11 and 3.14.

Final local acceptance on 2026-07-22 produced the following evidence:

- Ruff passed with no findings; mypy passed across 44 source and test files.
- All 28 offline tests passed with 93.61% statement coverage.
- The official Skill quick validator accepted the Skill, and all seven Skill command wrappers
  passed their help smoke tests.
- A deterministic 100,000-video fixture imported all 100,000 rows in about 4.4 seconds and rebuilt
  the normalized Parquet tables in about 4.4 seconds on the delivery workstation, with zero rejected
  rows and zero data-quality warnings. Timings are indicative, not a cross-machine performance SLA.

## Not delivered yet

Phase 2+ work remains explicit: representative sampling, account reports, subtitle/video analysis,
comment intent, pattern evidence, content scoring, prediction/retro, multimodal analysis, and
authorized platform or collaboration adapters.

## Handoff

Read `README.md` for Quick Start, `docs/data-contracts.md` for machine contracts,
`docs/adapter-guide.md` for field mappings, `docs/privacy-and-compliance.md` for boundaries, and
`docs/release-notes.md` for current and future updates.
