# Release notes

Keep future changes under **Unreleased** while developing. Move them into a dated version section
when releasing; retain prior sections so downstream users can understand migrations and behavior
changes.

## Unreleased

### Added

- Placeholder for Phase 4 development.

### Changed

- None.

### Migration

- None.

## 0.3.0 — 2026-07-22

### Added

- Immutable SRT, VTT, TXT, JSON, and JSONL transcript import tied to normalized video IDs.
- `TranscriptSegment` Parquet records with nullable timing, confidence flags, source hashes, and
  run provenance.
- Versioned video fact-extraction and semantic-labeling Prompt assets.
- Hook, structure, CTA, emotion timeline, content pillar, audience task, and language Schema.
- Mockable `TextModelProvider` and deterministic offline structured-file provider.
- Configurable Schema retries, low-confidence deterministic degradation, and strict error mode.
- Blind content bundles and `blind-analysis.json` that exclude all performance fields.
- Stage-two account-local performance context without relabeling blind content.
- Content-addressed single-video JSON/Markdown reports, evidence indexes, warnings, and `vta_*`
  IDs.
- `distiller import transcripts` and `distiller analyze video` commands, Skill routes/wrappers,
  Phase 3 Fixture, and unit/contract/integration/Golden tests.

### Changed

- Package and Skill version advanced to `0.3.0`.
- Project status includes transcript imports, normalized segment counts, video-analysis counts, and
  latest Phase 3 timestamps.
- DuckDB exposes the optional `transcripts` view.
- Transcript import and video analysis accept either internal or unique platform video IDs.
- Project validation now checks Phase 3 artifact integrity, blind-stage isolation, and evidence
  references.

### Migration

- Existing core schema `0.1.0` and Phase 2 analysis schema `0.2.0` remain unchanged.
- New transcript and text-analysis contracts use schema `0.3.0`.
- Existing configuration/state loads unchanged because model policy and Phase 3 timestamps have
  defaults.

### Security and compliance

- No network model or platform provider is included.
- Structured model responses are stored locally by hash; blind Prompt inputs contain no metrics.
- Transcript excerpts may contain sensitive content and must be reviewed before report sharing.

## 0.2.0 — 2026-07-22

### Added

- Deterministic stratified sampling with explicit selection reasons and coverage summaries.
- Population-aware sample sizing and content-addressed `smp_*` artifacts.
- Account-level cadence, stability, metric distribution, and content-type proxy statistics.
- High (S/A), middle (B), and low (C/D) account-local cohort comparison.
- Content-addressed account-health JSON and Markdown reports.
- Machine-readable evidence index resolving report values to normalized records, raw hashes, and
  run IDs.
- Report warnings for small samples, missing metrics, promotion, outliers, content-type proxy use,
  causal limits, and cross-platform scope.
- `distiller sample` and `distiller report` commands, Skill routes, 30-video Golden Fixture, and
  Phase 2 unit/contract/integration/Golden tests.

### Changed

- Package and Skill version advanced to `0.2.0`.
- Project status now reports sample/report artifact counts and latest timestamps.

### Migration

- Existing normalized/staging records remain on core schema `0.1.0` and are not rewritten.
- New Phase 2 artifacts use analysis schema `0.2.0`.
- Existing project config/state files load unchanged because new fields have defaults.

### Security and compliance

- Phase 2 remains fully offline and reads normalized Parquet rather than raw exports.
- Reports do not infer causal content rules or compare raw metrics across platforms.

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
