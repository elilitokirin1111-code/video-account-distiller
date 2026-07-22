# Implementation decisions

This document records Phase 0/1 choices where the planning pack was incomplete or contained
requirements from later phases.

## ID-001 — Create the repository from the planning-only archive

- **Decision:** Treat the archive as a planning pack for a new repository. Copy
  `docs/planning/AGENTS.md.template` to the repository root as `AGENTS.md`.
- **Reason:** The archive contained no source repository and no root `AGENTS.md`; its own README
  explicitly instructs this promotion.

## ID-002 — Phase 0/1 scope wins over later-phase acceptance items

- **Decision:** Implement only initialization, offline CSV/JSON ingestion, core models,
  normalization, query, deterministic metrics, status, fixtures, and supporting documentation.
  Sampling, semantic video analysis, reports, pattern discovery, scoring, prediction, and
  retrospectives remain unimplemented.
- **Reason:** `07_MILESTONE_PLAN.md` and the user request explicitly constrain this round to Phase
  0 and Phase 1, while parts of the P0 checklist describe the eventual product.

## ID-003 — Use current Agent Skill frontmatter

- **Decision:** Keep only `name` and `description` in `SKILL.md` frontmatter. Put UI metadata in
  `agents/openai.yaml`.
- **Reason:** The current Skill specification is more specific than the older blueprint example,
  which placed license, compatibility, and metadata in frontmatter.

## ID-004 — JSON state before SQLite

- **Decision:** Use `.distiller-state.json` plus immutable run manifests during Phase 1.
- **Reason:** Rule/task state that benefits from SQLite arrives in later phases. JSON keeps Phase 1
  deterministic, inspectable, and migration-light while meeting the status requirement.

## ID-005 — Latest snapshot for account performance scoring

- **Decision:** Preserve every `MetricSnapshot` in Parquet, but calculate the Phase 1 account
  performance table from the latest snapshot per video.
- **Reason:** Mixing multiple lifecycle snapshots would overweight older videos. Cohort-by-age
  scoring can be added when snapshot scheduling is implemented.

## ID-006 — MAD equals zero

- **Decision:** When a metric has observations but MAD is zero, assign `0.0` Robust Z-score to
  known observations and preserve missing observations as `None`.
- **Reason:** There is no measurable relative dispersion; returning zero is stable and avoids
  infinite or fabricated differences.

## ID-007 — Partial invalid imports

- **Decision:** Preserve the original input, accept valid rows, reject invalid rows, and write both
  JSON and Markdown quality reports. Return nonzero only when a non-empty file yields no valid rows.
- **Reason:** This preserves evidence and supports repair without losing usable records.

## ID-008 — Python development pin on this Windows workspace

- **Decision:** Declare package support for Python 3.11+ and test 3.11 in CI, while pinning the local
  development environment to Python 3.14.
- **Reason:** Python 3.11 on this non-ASCII Windows path does not load Hatch's UTF-8 editable `.pth`
  file. Python 3.14 handles the path correctly. Users who must use 3.11 on such a path can run
  `uv sync --no-editable`.

## ID-009 — No online adapter behavior

- **Decision:** Ship only the `SourceAdapter` protocol, offline file adapters, and platform mapping
  templates. Do not include login, scraping, browser automation, CAPTCHA handling, or live API
  calls.
- **Reason:** This is an explicit safety and Phase 1 boundary.

## ID-010 — Skill validation compatibility

- **Decision:** Treat the repository's current Skill validator as authoritative. Run `skills-ref
  validate` when that executable is available; otherwise run the bundled `quick_validate.py` and
  record the exact result in delivery notes.
- **Reason:** The planning pack names `skills-ref`, but does not vendor or pin it.
