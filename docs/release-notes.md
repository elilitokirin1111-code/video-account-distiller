# Release notes

Keep future changes under **Unreleased** while developing. Move them into a dated version section
when releasing; retain prior sections so downstream users can understand migrations and behavior
changes.

## Unreleased

### Added

- Phase 8 collection schema `0.8.0` and strict request, canonical account/video/metric, raw-page,
  and Provider batch contracts.
- Backward-compatible collection schema `0.8.1` with optional canonical comments, one-page
  high-comment-video sampling, immutable comment companions, and automatic redacted comment
  analysis before account distillation.
- `distiller account analyze` for a user-approved Douyin homepage URL, bounded 1～100 post
  pagination, `latest`/`popular` order, no-network dry-run, and explicit paid-call confirmation.
- Fixed-host TikHub Provider with environment-only credential, bounded retry, stable
  authorization/rate-limit/response errors, and injectable offline HTTP tests.
- Pinned `NanmiCoder/MediaCrawler` Git submodule and controlled sidecar Provider for the declared
  personal non-commercial learning/research workflow.
- Visible dedicated Chrome profile with manual authentication, stable runtime/login/timeout errors,
  offline bridge Fixtures, and a third-party licensing notice.
- Dedicated Microsoft Edge support, browser-specific login profiles, a bounded configurable login
  timeout, and navigation-safe manual authentication.
- Immutable Provider batches and canonical companions under `raw/account-collections/`, routed
  through the existing import, Parquet, robust-metric, report, and account-distillation services.
- Phase 8 project validation, status counters, `doctor` capability, offline Fixtures, CLI/provider
  contracts, integration tests, Skill route, live-acceptance guide, and architecture/data docs.
- Pinned MIT `bradautomates/claude-video` workflow reference and project-native
  `AccountMediaEnrichmentService`.
- `distiller account enrich-media` plus opt-in `account analyze --media-limit`, with retained
  Douyin-source allowlisting, immutable media, local Whisper Chinese transcription, scene/keyframe/
  audio analysis, single-video semantics, and account re-distillation.
- Strict `AccountMediaEnrichment`, `VideoMediaEnrichment`, and `TranscriptionSummary` contracts;
  stable media-download/transcription errors; project validation/status/doctor coverage; and
  network-disabled unit, contract, and integration tests.
- Loopback-only `OllamaVisionProvider` with `qwen3-vl:8b`, strict JSON Schema, bounded keyframe
  batches, frame-to-shot evidence mapping, OCR, scene/color/composition/camera/lighting,
  artistic-text, motion-graphic, and branding fields.
- Content-addressed `abp_*` account benchmark profiles that retain likes/comments/shares/saves,
  comment-like and semantic aggregates, content pillars, visual identity, snapshot times, hashes,
  and unavailable-field warnings for future comparisons.
- Same-platform account ranking based on per-video public-interaction medians and optional
  per-1,000-follower interactions, with per-account coverage and explicit view exclusion.
- `distiller account benchmark-profile`, automatic profile generation after homepage analysis and
  retained-media enrichment, profile validation, status counts, report tables, and offline tests.

### Changed

- The default `account analyze` provider is now MediaCrawler and the command completes collection,
  immutable import, Parquet/DuckDB normalization, metrics, comment analysis, reporting, and
  distillation in one run. TikHub remains available through `--provider tikhub`.
- Comment sampling defaults to 10 comments from each of at most three high-comment collected
  videos; `--comments-per-video 0` disables it.
- Only the controlled MediaCrawler bridge is approved: visible Chrome and manual authentication,
  with no proxy, stealth, automatic-login, CAPTCHA, or risk-control-evasion features.
- Contradictory public `play_count = 0` values with positive interactions are normalized as missing,
  and all-tied performance scores use neutral band `B` instead of labeling every work `S`.
- TikHub Douyin homepage posts now default to the welcome-credit-compatible Web endpoint. Operators
  with paid credit can opt into the more stable APP V3 endpoint with
  `TIKHUB_DOUYIN_POSTS_MODE=app-v3`; there is no automatic paid fallback.
- The first real MediaCrawler Edge acceptance passed on 2026-07-23 with 10 videos, 10 metric
  snapshots, and 30 comments accepted, zero row rejections, and zero project validation findings.
  Package and Skill remain `1.0.0` until an explicit release/tag decision; existing core and
  Phase 2～7 artifact schemas are unchanged.
- The conservative no-model video fallback now classifies only explicit Chinese hotel keywords at
  confidence no greater than `0.45`. Account positioning also reports measured orientation, median
  shot duration, audio activity, and any schema-backed visual annotations, while preserving
  unknown visual semantics and causal limits.
- Long clips with too few detected cuts now receive bounded uniform keyframe coverage, and repeated
  analyses/distillations select the newest timestamped media artifact rather than relying on an ID
  sort. Media-chain status and degraded local semantic status are reported independently.
- Qwen3-VL structured output is accepted from Ollama's local `message.content` or
  `message.thinking`, then validated identically; empty or malformed output still fails with the
  stable model Schema error.
- Cross-platform accounts remain available for conservative Pattern transfer but are excluded from
  public-interaction ranking. Missing views remain unknown and never enter the composite score.

### Acceptance

- A separately approved local run enriched two retained public videos (106.4 seconds and
  318.8 seconds) with local Whisper, yielding 53 and 208 transcript segments.
- The refreshed media kernel produced 12 keyframes for the long single-shot clip and 151 detected
  shots with 16 bounded keyframes for the longer edited clip.
- The account report reached 2/10 evidence-linked semantic coverage, added two measured
  media-production records, and passed final project validation with zero errors and zero warnings.
  See `docs/phase8-media-enrichment-acceptance-2026-07-23.md`.
- Ollama and `qwen3-vl:8b` were installed on the D drive for local visual acceptance; exact
  versions, model digest, real-project result, and validation outcome are recorded in the current
  `docs/local-vision-and-benchmark-acceptance-2026-07-23.md` note.

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
