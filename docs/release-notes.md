# Release notes

Keep future changes under **Unreleased** while developing. Move them into a dated version section
when releasing; retain prior sections so downstream users can understand migrations and behavior
changes.

## Unreleased

### Added

- Placeholder for the next implementation phase.

### Changed

- None.

### Migration

- None.

## 0.1.0 — 2026-07-22

### Added

- Standard `video-account-distiller` Agent Skill and Python package.
- Offline project initialization and immutable run manifests.
- CSV, JSON, JSONL, custom mapping, validation, deduplication, and SHA-256 raw storage.
- Account, AccountSnapshot, Video, MetricSnapshot, Comment, DerivedMetrics, RunManifest,
  DataQualityIssue, FieldMapping, and project-state contracts.
- Atomic Parquet tables and read-only DuckDB query layer.
- Null-safe engagement/watch metrics, Median, MAD, Robust Z-score, configurable weighted score,
  account viral ratio, outlier flags, and performance bands.
- Typer CLI with JSON output, stable error codes, dry runs, and status.
- Offline fixtures, 100,000-row generator, tests, CI, and delivery documentation.

### Security and compliance

- No live scraping, login automation, CAPTCHA handling, platform bypass, or real-network tests.
- Comment author identifiers are hashed before normalized storage.
