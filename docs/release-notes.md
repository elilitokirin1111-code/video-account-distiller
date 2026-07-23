# Release notes

Keep future changes under **Unreleased** while developing. Move them into a dated version section
when releasing; retain prior sections so downstream users can understand migrations and behavior
changes.

## Unreleased

### Added

- None.

### Changed

- None.

## 1.0.0 — 2026-07-23

### Added

- Stable installed-version output through `distiller --version`.
- Read-only `distiller doctor --json` diagnostics for Python, dependencies, FFmpeg, optional
  collaboration credentials, and project integrity/readiness.
- Reusable installed-wheel production acceptance runner and Windows installed-wheel CI.
- Tag-gated GitHub Release workflow with wheel, source distribution, and SHA-256 checksums.
- Production installation, operation, release, and acceptance documentation.

### Changed

- Package and Skill version advanced to `1.0.0`; Phase 0–7 artifact schema versions remain
  unchanged.
- Machine JSON uses ASCII-safe escaping so redirected Windows output remains portable when paths or
  values contain Chinese text.
- Project validation supports a non-persisting read-only mode used by `doctor`.

### Acceptance

- Installed the built wheel into a clean Python 3.11 Windows environment.
- Completed 18 operator commands across import, validation, normalization, metrics, sampling,
  reporting, comment analysis, distillation, and local analysis of a real hotel MP4.
- Accepted 30 videos, 30 metric snapshots, and 18 comments with zero final validation errors or
  warnings. See `docs/production-acceptance-v1.0.0.md`.

### Migration

- Existing projects require no data migration and are not rewritten automatically.
- Live Feishu/Google writes still require tenant-specific acceptance against a dedicated test table.

## 0.7.0 — 2026-07-22

### Added

- Strict authorization grants, export manifests, Feishu/Google connector configs, Sync receipts,
  Batch results, snapshot tasks, and Team policy contracts.
- SHA-256-verified authorized platform-export ingestion through the existing immutable import
  pipeline.
- Official Feishu Bitable paginated read/batch-create and Google Sheets v4 values read/append
  adapters behind an injectable dependency-free HTTP executor.
- Bounded 429/5xx retry with `Retry-After`, plus stable `E_ADAPTER_AUTH`, `E_RATE_LIMIT`, and
  `E_ADAPTER_RESPONSE` failures.
- `distiller sync pull/push`, `import authorized-export`, `batch run`, `snapshot plan`, and
  `team init/validate` commands with JSON and dry-run behavior where applicable.
- Content-addressed raw collaboration pages and idempotent push receipts, batch/schedule outputs,
  status counters, project validation, offline adapter contracts, integration tests, Skill routes,
  templates, and Phase 7 documentation.

### Changed

- Package and Skill version advanced to `0.7.0`.
- Project initialization adds collaboration raw/artifact directories and credential-name examples.
- Normalized remote exports read Parquet directly so the collaboration layer does not add a hidden
  timezone dependency to DuckDB result conversion.
- Live-table grants are bound to exact canonical resources with timezone-aware timestamps; non-dry
  Batch JSON returns its saved artifact path.

### Migration

- Core and Phase 2–6 Schemas remain unchanged; Phase 7 artifacts use Schema `0.7.0`.
- Existing `distiller.yaml` and `.distiller-state.json` files load through defaults for the new
  collaboration policy and timestamps.
- No existing analysis, prediction, publication, media, or Parquet artifact is rewritten.

### Security and compliance

- Connector and team files contain environment-variable names but never token values.
- Only user-provided exports and explicitly authorized official Feishu Bitable/Google Sheets APIs
  are supported. No login automation, CAPTCHA handling, scraping, or rate-limit evasion was added.
- The test suite disables network and injects fake provider responses for every adapter contract.

## 0.6.0 — 2026-07-22

### Added

- Strict metadata, shot, keyframe, audio, OCR, visual annotation, evidence, analysis, and aggregate
  media-feature contracts.
- Mockable `MediaBackend` plus local FFmpeg/FFprobe metadata, scene detection, JPEG extraction, and
  bounded mono PCM decoding.
- Deterministic RMS/peak dBFS, dynamic-range, loudness-variance, silence/activity, and silence-
  interval calculations.
- Mockable `VisionModelProvider` and offline structured JSON replay with retry and strict/degraded
  modes.
- `distiller analyze media` CLI route, thin Skill wrapper, timestamped JSON/Markdown artifacts,
  content-addressed raw media/vision storage, and DuckDB `media_features` view.
- Phase 6 status counters, full artifact/hash/timeline validation, unit/contract/integration tests,
  and local-media documentation.

### Changed

- Package and Skill version advanced to `0.6.0`.
- Project initialization adds raw media, raw vision-output, and media-analysis directories.
- Project status reports the latest media analysis, artifact count, and aggregate Parquet row count.

### Migration

- Core Schema `0.1.0` and Phase 2–5 Schemas remain unchanged.
- New media artifacts and `media_features.parquet` use Schema `0.6.0`.
- Existing config and state load through defaults for the new `media`, `vision_provider`, and
  `last_media_analysis_at` fields.

### Security and compliance

- Local mode never uploads media or opens a browser; no network vision client is bundled.
- Raw media, frames, OCR, and visual reports are treated as sensitive content-addressed evidence.
- Missing FFmpeg degrades visibly by default; strict mode returns stable `E_MEDIA_DECODE`.

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
