# Release notes

Keep future changes under **Unreleased** while developing. Move them into a dated version section
when releasing; retain prior sections so downstream users can understand migrations and behavior
changes.

## Unreleased

### Added

- Placeholder for Phase 6 development.

### Changed

- None.

### Migration

- None.

## 0.5.0 — 2026-07-22

### Added

- Strict Rule, Rubric, ContentCandidate, ScoreResult, Prediction, Publication, PredictionError,
  Retro, change-proposal, and Experiment contracts.
- Deterministic nine-dimension script scoring with visible weights, explanations, missing items,
  risks, Pattern/Rule evidence, and bounded low-maturity adjustments.
- Versioned candidate Rules derived from Phase 4 Patterns and account-specific Rubrics totaling
  100 points.
- Immutable account-local P25/P50/P75 predictions with target age, confidence, assumptions,
  uncertainties, input hash, and Rubric/Rule versions.
- Publication registration that requires a normalized same-account video and records T+1h,
  T+24h, T+3d, and T+7d snapshot plans.
- Snapshot Retro with actual-vs-predicted error, interval position, Rule support/counterexamples,
  external factors, pending Rule/Rubric proposals, and proposed next experiments.
- `distiller score`, `distiller predict`, `distiller publish`, and `distiller retro` CLI routes and
  thin Skill wrappers.
- Phase 5 status counters, artifact validation, offline script Fixture, and unit/contract/
  integration/Golden tests.

### Changed

- Package and Skill version advanced to `0.5.0`.
- Project initialization adds candidate, Rubric, scoring, prediction, publication, Retro, review,
  and experiment directories.
- Status includes Phase 5 artifacts, pending proposal counts, latest timestamps, and a bounded list
  of recent canonical/platform video IDs.
- Project validation checks candidate raw hashes, Rubric totals, Rule versions, immutable IDs,
  linked artifacts, evidence companions, reviews, and experiments.

### Migration

- Core Schema `0.1.0`, Phase 2 Schema `0.2.0`, Phase 3 Schema `0.3.0`, and Phase 4 Schema `0.4.0`
  remain unchanged.
- New closed-loop artifacts use Schema `0.5.0`; existing config/state files load through defaults.
- New scoring config controls target snapshot age, snapshot plan, predicted metrics, and maximum
  Rule adjustment.

### Security and compliance

- Phase 5 remains fully offline and adds no network/platform/model provider.
- Script candidates are preserved by SHA-256 and may contain confidential content.
- Predictions and publications are append-only content-addressed records.
- Publication rejects retrospective predictions and normalized/override timestamp contradictions.
- Retro never auto-approves or mutates Rule/Rubric versions; every eligible proposed change is
  pending, while materially mistimed, promoted, or outlier snapshots cannot propose changes.

## 0.4.0 — 2026-07-22

### Added

- Privacy-preserving comment analysis copies with direct-identifier redaction.
- Strict comment sentiment, intent, pain-point, question, objection, purchase-intent, opportunity,
  spam, confidence, and unknown Schema.
- Mockable comment model calls, structured-file retries, deterministic fallback, and visible
  degradation.
- Readable account-local need clusters with frequency, intensity, representative comments, and
  traceable evidence.
- Content clusters using blind semantic pillars with explicit `content_type` proxy fallback.
- Versioned `Pattern` objects with support videos, counterexamples, confounders, scope, maturity,
  confidence, replicability, risks, and evidence.
- Account distillation JSON/Markdown with positioning observations, strengths, failure modes,
  copyable/noncopyable factors, actions, and experiments.
- Knowledge-base account profiles, immutable Pattern JSON, and rebuildable index.
- Benchmark transfer matrices with separate account/platform baselines and conservative verdicts.
- `distiller analyze comments`, `distiller distill`, and `distiller compare` CLI routes and Skill
  wrappers.
- Phase 4 artifact validation, status counters, offline Fixtures, and unit/contract/integration/
  Golden tests.

### Changed

- Package and Skill version advanced to `0.4.0`.
- Project status includes comment analyses, account distillations, comparisons, and timestamps.
- Account dataset input hashes now include derived metrics used by downstream artifacts.
- Structured-file providers fail on exhausted candidates instead of silently reusing the last
  response.

### Migration

- Core Schema `0.1.0`, Phase 2 Schema `0.2.0`, and Phase 3 Schema `0.3.0` remain unchanged.
- Phase 4 artifacts use Schema `0.4.0`; existing config/state files load through defaulted fields.
- New config fields control Pattern support, future validated-rule support, and comment analysis
  caps; direct-identifier redaction is mandatory for comment analysis copies.

### Security and compliance

- No network model or platform provider is included.
- Raw comments remain immutable; reports omit author IDs/hashes and use best-effort redacted text.
- Comment demand and transfer results are explicitly biased hypotheses, not population or causal
  claims.

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
