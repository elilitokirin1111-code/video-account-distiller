# Implementation decisions

This document records implementation choices where the planning pack was incomplete or contained
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

## ID-011 — Subsequent user instruction advances the milestone

- **Decision:** Implement only Phase 2 in version `0.2.0` while preserving the completed Phase 0/1
  interfaces.
- **Reason:** `08_CODEX_MASTER_PROMPT.md` freezes its original round at Phase 0/1, while the user
  explicitly requested the next development step and `07_MILESTONE_PLAN.md` defines that step as
  Phase 2.

## ID-012 — Separate core and analysis schema versions

- **Decision:** Keep normalized Phase 1 records on core schema `0.1.0` and version new sampling and
  report artifacts as analysis schema `0.2.0`.
- **Reason:** Phase 2 adds new contracts but does not require rewriting stable Parquet or staging
  data. Package and Skill versions advance independently to `0.2.0`.

## ID-013 — `content_type` is a temporary pillar proxy

- **Decision:** Use the normalized `Video.content_type` field for Phase 2 pillar coverage and label
  it explicitly as a proxy in manifests, reports, warnings, and Skill guidance.
- **Reason:** Semantic content-pillar extraction belongs to Phase 3. Inventing semantic labels from
  titles or performance would violate the fact/inference boundary.

## ID-014 — Content-addressed samples and reports

- **Decision:** Derive stable `smp_*` and `rpt_*` IDs from account, inputs, policy/version, size, and
  selected IDs. Reuse unchanged artifacts instead of overwriting or duplicating them.
- **Reason:** This preserves idempotence, supports versioned future outputs, and keeps historical
  run manifests meaningful.

## ID-015 — Evidence-linked deterministic health reports

- **Decision:** Wrap report statistics with `evi_*` references and write a separate evidence index
  containing normalized/source IDs, raw hashes, calculations, and source runs. Limit findings to
  facts, account-local associations, and warnings.
- **Reason:** Phase 2 must make all report data traceable without prematurely implementing Phase 3
  semantic analysis or Phase 4 pattern claims.

## ID-016 — Subsequent user instruction advances to Phase 3

- **Decision:** Implement the complete Phase 3 milestone in package and Skill version `0.3.0`,
  preserving Phase 0/1/2 interfaces and artifacts.
- **Reason:** The user requested the next development stage; `07_MILESTONE_PLAN.md` identifies the
  third round as transcript-level video analysis.

## ID-017 — Offline structured-file provider before network clients

- **Decision:** Define a mockable `TextModelProvider` protocol and ship an offline structured JSON
  provider plus deterministic fallback, but no cloud or platform client.
- **Reason:** Phase 3 requires model-Schema behavior and Prompt assets, while repository policy
  requires offline tests and the user has not authorized content upload to a model service.

## ID-018 — Freeze blind labels before metric lookup

- **Decision:** Build a strict `BlindVideoBundle`, run fact and semantic tasks without performance
  fields, persist `blind-analysis.json`, and only then attach the latest metric context.
- **Reason:** This directly enforces the anti-hindsight requirement and prevents circular labels
  such as inferring Hook quality from views.

## ID-019 — Retry, degrade, and strict modes

- **Decision:** Retry invalid structured output up to a configured attempt limit. By default,
  degrade to conservative low-confidence local output; `--strict-model` instead returns stable
  model unavailable or Schema-invalid errors.
- **Reason:** The Phase 3 exit condition permits retry or degradation. Supporting both makes batch
  processing resilient while allowing callers to require model-complete output.

## ID-020 — Separate Phase 3 contract version

- **Decision:** Keep existing core schema `0.1.0` and Phase 2 analysis schema `0.2.0`; version new
  transcript/text-analysis records and artifacts as `0.3.0`.
- **Reason:** Existing Parquet, samples, and reports need no rewrite. New contracts can migrate
  independently.

## ID-021 — Preserve structured model output as raw evidence

- **Decision:** Hash and copy user-provided model output into local content-addressed raw storage,
  and derive stable `vta_*` analysis IDs from content, prompts, output, and metric context.
- **Reason:** Model results are analytical inputs and require the same immutability and replay
  guarantees as data exports.

## ID-022 — Prompt assets have one tracked source

- **Decision:** Keep versioned Prompt Markdown under the Skill assets and force-include that folder
  in built wheels; source checkouts load the same files directly.
- **Reason:** This avoids divergent Prompt copies while keeping both the installed Skill and Python
  package self-contained.

## ID-023 — Resolve user-facing platform video IDs at the service boundary

- **Decision:** Accept either the canonical internal `vid_*` or a unique platform video ID for
  transcript import and single-video analysis, then persist only the canonical internal ID.
- **Reason:** Forward-testing the Skill showed that requiring users to inspect staging data for a
  generated ID made the documented workflow unnecessarily brittle. Ambiguous platform IDs still
  fail explicitly instead of guessing.

## ID-024 — Extend project validation to Phase 3 artifacts

- **Decision:** Make the existing `validate` command check raw model-output hashes, analysis
  Schema, content-addressed identities, blind-stage performance isolation, artifact paths, and
  evidence references.
- **Reason:** Phase 3 needs one repeatable acceptance command rather than relying on manual JSON
  inspection after every video analysis.

## ID-025 — Analyze redacted comment copies without mutating source data

- **Decision:** Keep raw and normalized comments immutable, but redact common phone, email, URL,
  handle, and contact identifiers in the Phase 4 analysis copy before prompting or reporting.
- **Reason:** Pattern and intent analysis needs comment evidence while privacy rules prohibit
  exposing author identifiers or silently changing source records.

## ID-026 — Use readable deterministic need clusters before embeddings

- **Decision:** Group comments by a documented primary-intent priority and attach representative
  comment IDs, frequency, intensity, opportunities, and evidence.
- **Reason:** Phase 4 must work fully offline and cannot treat opaque embedding cluster numbers as
  business conclusions. Embedding providers remain an optional later enhancement.

## ID-027 — Cap Phase 4 Pattern maturity at Level 1

- **Decision:** Generate only Level 0 observations and Level 1 account-local associations. Require
  support videos and a counterexample field, keep sets disjoint, and never emit Level 4 rules.
- **Reason:** One offline historical sample cannot establish causality or repeated experimental
  validation, even when an association is strong.

## ID-028 — Exclude paid and Robust-outlier videos from Pattern counts

- **Decision:** Preserve promoted and Robust-outlier videos as explicit confounders but exclude
  them from Pattern support and counterexample counts.
- **Reason:** Their performance may be driven by distribution or external events; deleting them
  would hide risk, while counting them as ordinary evidence would inflate confidence.

## ID-029 — Prefer semantic pillars and degrade to labeled proxies

- **Decision:** Build content clusters from completed blind semantic pillars when available and use
  normalized `content_type` only as an explicit proxy for uncovered videos.
- **Reason:** Account distillation must remain useful before full Phase 3 coverage without
  presenting source categories as model-derived semantics.

## ID-030 — Transfer matrices never compare raw account metrics

- **Decision:** Distill every account independently and review transfer through features, scope,
  maturity, platform alignment, replicability, and risk. Cross-platform items default to
  understanding rather than direct migration.
- **Reason:** Account sizes and platform mechanics make raw views non-comparable; transfer is a
  planning hypothesis that requires a bounded target-account experiment.

## ID-031 — Materialize Phase 4 Patterns only as candidate Rules

- **Decision:** Create versioned Rule records from account-local Patterns, but keep them in
  `candidate` status and cap their scoring influence. Do not promote historical associations to
  validated rules.
- **Reason:** Phase 4 evidence has support and counterexamples but no repeated controlled
  experiments. Phase 5 needs executable scoring inputs without weakening the maturity contract.

## ID-032 — Use a deterministic nine-dimension Rubric

- **Decision:** Score scripts with the planned 100-point Rubric using transparent text checks and
  bounded Rule adjustments. Store every dimension, explanation, missing item, risk, and evidence;
  do not call a model or return only a black-box total.
- **Reason:** The closed loop must work offline and remain testable. Model-assisted scoring can be
  added later behind a strict provider, but deterministic behavior is the safe baseline.

## ID-033 — Predict account-local empirical intervals, not guaranteed outcomes

- **Decision:** Build P25/P50/P75 from each video's eligible snapshot nearest the requested age in
  the same account, exclude paid and Robust-outlier records, require at least three observations per
  metric, expose timing mismatch, and apply only a bounded score adjustment.
- **Reason:** There is no trained causal model or comparable peer panel. The result is a calibrated
  historical interval with visible assumptions, not a promise or cross-platform forecast.

## ID-034 — Enforce logical immutability with content addressing and validation

- **Decision:** Derive `pred_*` and `pub_*` from canonical input hashes, never expose an update or
  overwrite route, reuse exact repeats, and make `distiller validate` check ID/hash/link integrity.
  Do not set filesystem read-only flags.
- **Reason:** Read-only flags are unreliable across operating systems and can obstruct backup or
  deletion. Content addressing plus an append-only service contract is portable and testable.

## ID-035 — Require a chronological normalized video before publication registration

- **Decision:** Link a prediction only to an existing normalized video from the same account and
  target platform. Require the normalized publication time to follow prediction creation and reject
  an explicit time that contradicts the normalized record. Continue importing actual snapshots
  through the existing metrics Adapter.
- **Reason:** This prevents invented platform IDs and metrics, keeps the Adapter boundary intact,
  prevents retrospective predictions from being presented as pre-publication forecasts, and makes
  every Retro actual value traceable to normalized and raw evidence.

## ID-036 — Select the nearest snapshot and expose timing mismatch

- **Decision:** Retro evaluates the normalized snapshot nearest the requested T+ age and emits a
  warning when the distance exceeds tolerance rather than fabricating or interpolating a value.
  A materially mistimed, promoted, or Robust-outlier snapshot may be reviewed, but it marks all
  matched Rules inconclusive and cannot generate Rule/Rubric change proposals.
- **Reason:** Exports often omit exact checkpoints. Keeping the real snapshot age is more honest
  than pretending a late snapshot represents T+3d exactly, while the eligibility gate prevents
  confounded observations from silently changing policy.

## ID-037 — Keep all Rule and Rubric changes pending

- **Decision:** Retro may propose a version, status, scope, or small paired weight change and write
  next experiments, but it never creates the proposed Rule version or mutates the current Rubric.
- **Reason:** One observed publication may support or contradict a hypothesis but cannot establish
  causality or approve a Level 4 rule. Human review and repeated experiments remain mandatory.

## ID-038 — Add an independent Phase 5 schema version

- **Decision:** Advance package and Skill to `0.5.0` and use `0.5.0` for closed-loop artifacts while
  preserving core `0.1.0`, Phase 2 `0.2.0`, Phase 3 `0.3.0`, and Phase 4 `0.4.0` contracts.
- **Reason:** No existing Parquet or analysis artifact needs rewriting; independent versions keep
  migrations narrow and preserve reproducibility.

## ID-039 — Implement Phase 6 as an offline local-media adapter

- **Decision:** Analyze only user-provided local files through FFmpeg/FFprobe and keep live platform
  collection outside the media package.
- **Reason:** Phase 6 requires multimodal evidence, while repository policy prohibits implicit
  platform access and the user asked to defer real collection until later adaptation.

## ID-040 — Prefer FFmpeg CLI over mandatory computer-vision dependencies

- **Decision:** Ship a small mockable subprocess adapter without making OpenCV, PySceneDetect,
  librosa, or a GPU runtime mandatory dependencies.
- **Reason:** FFmpeg already provides portable metadata, scene scores, frame extraction, and PCM
  decoding. A lighter install is easier to test across Python 3.11/3.14 and can be replaced behind
  the same protocol when a specialist decoder is justified.

## ID-041 — Degrade explicitly when the local decoder is unavailable

- **Decision:** Default to a content-addressed degraded artifact with unknown fields and warnings;
  `--strict-media` returns `E_MEDIA_DECODE`.
- **Reason:** This satisfies the Phase 6 exit condition without fabricating media observations and
  supports both resilient batch work and strict automation.

## ID-042 — Keep visual/OCR results separate, optional, and timestamp-cited

- **Decision:** Define a mockable vision Provider and offline structured-file replay. Require every
  annotation to cite existing shot/keyframe evidence; ship no network client.
- **Reason:** Visual models can change independently and may require content upload. The boundary
  preserves privacy defaults, replay, Schema validation, and exact evidence timing.

## ID-043 — Store detailed timelines as JSON and aggregates as Parquet

- **Decision:** Persist shots, frames, audio intervals, and OCR in content-addressed JSON artifacts,
  while writing one traceable aggregate `MediaFeatureRecord` per analysis to Parquet/DuckDB.
- **Reason:** Nested timelines remain readable and precisely validated, while account-level queries
  get a stable columnar table without flattening or duplicating every interval.

## ID-044 — Advance the prior offline-only boundary for Phase 7

- **Decision:** Add only explicitly authorized export ingestion and official Feishu Bitable/Google
  Sheets APIs; continue to prohibit login automation, scraping, CAPTCHA handling, and platform-
  control evasion.
- **Reason:** The user requested the next milestone after Phase 6, and Phase 7 explicitly requires
  authorized platform or export adapters plus collaboration tables. This supersedes ID-009 only for
  those narrow official interfaces, not for unrestricted platform collection.

## ID-045 — Keep credentials out of project and team configuration

- **Decision:** Connector files store only an uppercase environment-variable name. Authorization
  grants record who approved which read/write scope and when, but never store a token value.
- **Reason:** Connector configs, team policy, manifests, logs, and Git history must remain safe to
  inspect and share. A missing/expired grant or credential returns stable `E_ADAPTER_AUTH`.

## ID-046 — Put retry and provider parsing behind a mockable HTTP executor

- **Decision:** Implement bounded retry for HTTP 429/5xx, honor `Retry-After`, map exhausted limits
  to `E_RATE_LIMIT`, map HTTP 401/403 to `E_ADAPTER_AUTH`, and test both official adapters with fake
  executors rather than real network access.
- **Reason:** Phase 7 needs reliable permission/rate-limit behavior while the acceptance suite must
  remain offline, deterministic, and independent of any third-party account.

## ID-047 — Treat collaboration pulls as immutable imports and pushes as content-addressed syncs

- **Decision:** Preserve raw provider pages under `raw/collaboration/<connector>/<hash>.json`, route
  pulled rows through the existing mapping/Pydantic/import pipeline, export only normalized
  Parquet rows, and reuse a completed push receipt for identical connector/entity/content hashes.
- **Reason:** This keeps analysis platform-neutral, maintains raw traceability, and prevents an
  accidental repeated batch from appending identical rows twice.

## ID-048 — Expose scheduling without installing a background scheduler

- **Decision:** Generate stable due/future/available snapshot tasks from immutable publications and
  normalized metric snapshots. Let an external scheduler invoke the JSON CLI; do not create an OS
  service or silently collect platform data.
- **Reason:** Phase 7 asks for a scheduled-snapshot interface, while deployment cadence, credentials,
  and external side effects must stay under explicit operator control.

## ID-049 — Bind live-table grants to one canonical resource

- **Decision:** Require timezone-aware authorization timestamps and an exact connector-specific
  source reference: `bitable:<app-token>/<table-id>` or
  `sheets:<spreadsheet-id>/<range>`. Return a non-dry Batch result's artifact path directly in JSON.
- **Reason:** A provider-level grant must not be reusable accidentally for another table. The path
  addition also resolves the Phase 7 forward-test finding that callers otherwise had to discover
  the Batch artifact by scanning the project tree.

## ID-050 — Release completed phases as package 1.0 without renumbering artifact schemas

- **Decision:** Mark the installable package and Skill as `1.0.0`, while retaining the Phase 0–7
  artifact schema versions from `0.1.0` through `0.7.0`.
- **Reason:** The package is now operationally stable, but changing immutable artifact version
  values without a schema change would create a false migration and break traceability.

## ID-051 — Make production diagnostics read-only and Windows JSON pipe-safe

- **Decision:** Add `distiller doctor`, call project validation with `persist=False`, and use
  ASCII-safe JSON escaping for all `--json` stdout envelopes.
- **Reason:** A diagnostic command must not create runs or update project state. Real Windows UAT
  also showed that locale-dependent bytes could break UTF-8 automation when Chinese paths were
  redirected through a pipe; JSON escapes preserve the decoded value without encoding ambiguity.

## ID-052 — Add homepage parsing through a replaceable documented Provider

- **Decision:** Accept a user-provided Douyin homepage URL and use TikHub's documented
  `sec_user_id`, profile, and homepage-post endpoints for the first arbitrary-public-account
  Provider. Keep the Provider behind `AccountCollectionProvider` and an injectable HTTP executor.
- **Reason:** Douyin's official account-video API requires the account owner's OAuth authorization
  and therefore cannot analyze arbitrary benchmark accounts from only a public homepage URL.
  Isolating TikHub prevents its response schema from leaking into the normalized analysis kernel
  and leaves an upgrade path for official/self-account adapters.

## ID-053 — Require fixed hosts, dry-run, and explicit cost confirmation

- **Decision:** Allow only HTTPS Douyin input hosts and only the fixed TikHub API hosts
  `api.tikhub.dev` or `api.tikhub.io`. `--dry-run` performs no network or writes; a real call
  requires `--confirm-provider-cost`. Keep `TIKHUB_API_KEY` outside the project.
- **Reason:** URL allowlisting blocks the collection command from becoming a general SSRF client,
  while cost confirmation prevents accidental paid calls. Environment-only credentials keep raw
  artifacts, logs, support bundles, and Git history safe.

## ID-054 — Route Provider data through the existing immutable data kernel

- **Decision:** Preserve the complete Provider batch under
  `raw/account-collections/<provider>/<sha256>/`, emit strict canonical account/video/metric JSON,
  and call `ImportService`, `NormalizationService`, `MetricsService`, `ReportService`, and
  `AccountDistillationService` unchanged.
- **Reason:** A live source must not bypass mapping, validation, raw hashing, quality reports,
  Parquet normalization, or evidence boundaries. Reusing the kernel also makes offline fixtures
  representative of the real workflow.

## ID-055 — Keep package 1.0.0 until a real-token acceptance run passes

- **Decision:** Add collection schema `0.8.0` on the main development line without changing the
  released package/Skill version `1.0.0`. Do not create a new release tag until one explicitly
  approved public account passes credential, billing, field-mapping, data-count, validation, and
  secret-leak checks in the real environment.
- **Reason:** Offline provider contracts prove deterministic behavior but cannot prove a live
  subscription, current provider payload, or account-specific availability. Version promotion
  should follow that final operational evidence rather than precede it.

## ID-056 — Make public comment collection opt-in and cost-bounded

- **Decision:** Keep homepage comment collection disabled by default. When explicitly requested,
  sample at most 20 top-level comments from each of at most 10 already-collected videos, prioritizing
  public comment count. Include every added comment page in dry-run call totals, preserve the raw
  Provider page, hash author identifiers in canonical rows, and run the existing redacted comment
  analysis before distillation.
- **Reason:** Comment text materially improves pain-point, objection, and content-opportunity
  analysis, but multiplies Provider calls and expands the personal-data footprint. A one-page,
  high-signal, explicitly enabled sample creates predictable cost and privacy limits while reusing
  the tested Phase 4 pipeline.

## ID-057 — Default live acceptance to the free-credit-compatible Web posts endpoint

- **Decision:** Use TikHub's Douyin Web homepage-post endpoint by default because the API
  marketplace currently marks it as eligible for welcome credit. Keep the documented APP V3
  endpoint available through `TIKHUB_DOUYIN_POSTS_MODE=app-v3`, but never fall back to it
  automatically.
- **Reason:** The approved first live test has only welcome credit, while TikHub currently marks
  the APP V3 homepage-post endpoint as paid-credit-only. The Web endpoint has the same bounded
  pagination contract but is documented as potentially less stable. An explicit opt-in preserves
  the more stable paid path without risking an unexpected charge or changing normalized schemas.

## ID-058 — Pin MediaCrawler as an explicitly third-party research component

- **Decision:** Add `NanmiCoder/MediaCrawler` as a Git submodule pinned to commit
  `0625e01a6bc717a3fc9c96d3dac7fb8957043838`. Preserve its upstream license and add
  `THIRD_PARTY_NOTICES.md`. Limit the bundled path to the user's declared personal,
  non-commercial learning and research scope; require a new licensing review before commercial
  use, hosted service, paid delivery, or redistribution beyond the upstream terms.
- **Reason:** A pinned source tree and lockfile make the research runtime reproducible and
  auditable, while a clear third-party boundary prevents the root MIT license from being
  misinterpreted as relicensing MediaCrawler. The notice preserves learning/reference attribution
  without making an unsupported commercial-rights claim.

## ID-059 — Use a controlled MediaCrawler sidecar instead of its full crawler workflow

- **Decision:** Invoke only MediaCrawler's Douyin client, parsing, and signing code from a separate
  locked `uv` process. Launch visible Chrome with a dedicated persistent profile and require manual
  user authentication. Disable proxies and do not invoke upstream stealth injection,
  automatic-login, slider/CAPTCHA, or risk-control-evasion paths.
- **Reason:** The project needs the useful data-collection capability but must keep authentication
  and platform controls under direct user control. A strict JSON sidecar preserves process and
  dependency isolation, stable errors, offline contract testing, and the existing provider-neutral
  analysis kernel.

## ID-060 — Make MediaCrawler the default complete homepage-to-distillation workflow

- **Decision:** Default the CLI and request model to `mediacrawler`, sample up to 10 top-level
  comments from each of at most three high-comment collected videos, and keep TikHub as an explicit
  optional paid Provider. A single `account analyze` command must still preserve raw pages and
  hashes, import and validate canonical rows, rebuild Parquet/DuckDB, calculate robust metrics, and
  generate comment analysis, account health, and distillation artifacts.
- **Reason:** The requested operating model is a usable end-to-end workflow from one homepage URL,
  not a disconnected collector or manual export bridge. Reusing `AccountCollectionService` keeps
  all existing evidence, privacy, and validation contracts intact while removing a mandatory
  third-party API charge from the default personal-research path.

## ID-061 — Keep manual authentication navigation-safe and browser-specific

- **Decision:** Treat page-navigation errors during the bounded login wait as transient, support
  `chrome` and `msedge` through separate dedicated profiles, and allow an environment-only
  30～900-second login timeout. Continue to reject every other browser channel and never automate
  credentials, CAPTCHA, verification, proxy, stealth, or risk-control behavior.
- **Reason:** The first Windows acceptance attempt showed that a normal user-initiated login
  navigation could destroy Playwright's evaluation context, while the default three-minute window
  could close before a slower manual login completed. These changes make the allowed manual path
  reliable without broadening the security boundary.

## ID-062 — Treat contradictory zero public views as unavailable

- **Decision:** When a public post reports `play_count = 0` together with any positive interaction,
  normalize views to `null`, retain every interaction count, and emit the existing missing-view
  collection warning. If every otherwise-known performance score is tied, assign neutral band
  `B` rather than incorrectly labeling every row `S`.
- **Reason:** The first live MediaCrawler payload exposed positive likes, comments, shares, and
  saves while withholding play counts as zero. Treating that sentinel as a measured zero removed
  all rate denominators and caused a percentile tie to appear as universal top performance.
  Missing and neutral output is more honest than a fabricated ranking.

## ID-063 — Pin claude-video as an MIT workflow reference

- **Decision:** Add `bradautomates/claude-video` as a Git submodule pinned to
  `83da59fa78c3eee9e20f515fe75c438bb5166efd` (`0.2.0`) and preserve its MIT license and
  attribution in `THIRD_PARTY_NOTICES.md`.
- **Reason:** The upstream project provides a compact, auditable reference for URL/local-video
  acquisition, scene-aware frames, captions, and Whisper fallback. Pinning it makes the borrowed
  workflow boundary reproducible without making an unversioned GitHub dependency part of the
  analysis kernel.

## ID-064 — Adapt the workflow instead of executing upstream watch.py

- **Decision:** Do not execute upstream `/watch` in the account pipeline. Implement a project-native
  `AccountMediaEnrichmentService` that reuses the existing FFmpeg media service, transcript
  importer, normalizer, single-video analyzer, and account distiller.
- **Reason:** Upstream output is Markdown-oriented, defaults captions to English, falls back only
  to cloud Whisper APIs, and has an open source/output-directory deletion risk. The native adapter
  preserves strict Pydantic JSON, raw hashes, stable errors, Windows UTF-8 behavior, offline tests,
  and the project's evidence chain.

## ID-065 — Resolve video bytes only from retained approved Provider evidence

- **Decision:** Media enrichment may read candidates only from an immutable MediaCrawler
  `aweme/detail` page for the selected normalized video. Accept only HTTPS `douyin.com` or
  `douyinvod.com` hosts, validate the final redirect host, limit each file to 512 MiB, never emit
  signed URLs, and remove only service-owned temporary files after the media is hash-preserved.
- **Reason:** This removes manual per-video import while keeping the account, sample, provenance,
  and network boundary explicit. It also prevents the feature from becoming an arbitrary URL
  fetcher or a second authentication/cookie workflow.

## ID-066 — Keep transcription local and mockable

- **Decision:** Use a local OpenAI Whisper CLI through an argument-array subprocess with no shell,
  default model `base`, explicit executable override, one-hour timeout, strict JSON conversion,
  and stable unavailable/failed error codes. Tests inject a local fixture transcriber and disable
  all sockets.
- **Reason:** Current public Douyin details do not provide speech captions. Local transcription
  closes the semantic-analysis gap without uploading guest, room, screen, or booking content to a
  third-party model service.

## ID-067 — Surface measured production style and bounded local hotel semantics

- **Decision:** Let the degraded text fallback classify only explicit Chinese hotel-operation,
  service, housekeeping, career, and accommodation keywords, cap confidence at `0.45`, and retain
  a human/model-review warning. Account positioning may summarize measured orientation, median
  shot duration, silence ratio, and schema-backed visual annotations from `media_features`.
- **Reason:** Always returning `primary_pillar=unknown` made a real 10-video report structurally
  correct but operationally empty. Explicit evidence-linked local labels and measured production
  signals improve the report without fabricating objects, people, OCR, music meaning, causality,
  or performance patterns.
