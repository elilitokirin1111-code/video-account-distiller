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

## ID-060 — Make MediaCrawler the default complete homepage-to-distillation workflow (superseded)

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

## ID-068 — Keep the bundled live visual Provider loopback-only

- **Decision:** Add Ollama/Qwen3-VL as the only bundled live visual path. Accept only
  `http://127.0.0.1:11434` or `localhost` on port 11434 and reject TLS, remote hosts, credentials,
  alternate ports, paths, queries, and fragments before reading image bytes.
- **Reason:** The project needs real visual/OCR analysis without sending guest, room, screen, or
  booking imagery to a cloud service. A hard loopback boundary is testable and preserves the
  existing local-first privacy model.

## ID-069 — Install Ollama program and model storage on D

- **Decision:** On the accepted Windows workstation, install Ollama under `D:\AI\Ollama\App`, set
  the user `OLLAMA_MODELS` value to `D:\AI\Ollama\Models`, and pull `qwen3-vl:8b` there. Keep this
  path operator-configurable in documentation rather than hard-coding it into project data.
- **Reason:** The user explicitly requested D-drive installation and the workstation has ample D
  capacity. Environment-based model storage avoids filling the system drive while keeping normal
  Ollama behavior.

## ID-070 — Persist reusable public-interaction and comment-content profiles

- **Decision:** Build content-addressed `abp_*` profiles from the latest normalized per-video
  metrics, exact comment-analysis artifact, exact account distillation, and any visual identity.
  Retain every profile and automatically rebuild after homepage analysis or media enrichment.
- **Reason:** Later account comparisons must not require the user to re-enter older data. Immutable
  raw batches plus versioned derived profiles preserve history and make the exact comparison input
  auditable.

## ID-071 — Rank only visible same-platform interaction dimensions

- **Decision:** Rank target-platform accounts using percentiles for median likes, comments, shares,
  saves/favorites, and interactions per 1,000 followers when available. Average only each account's
  available dimensions, report coverage, exclude cross-platform accounts, and never use homepage
  views.
- **Reason:** Douyin public pages may withhold views and follower denominators. Treating them as
  zero or comparing them across platforms would create false precision. Comment semantics explain
  audience needs but do not inflate the interaction score.

## ID-072 — Validate Qwen structured output from either Ollama message field

- **Decision:** Prefer non-empty `message.content`; when it is empty, accept `message.thinking` and
  validate it against the same strict JSON Schema. Do not regex-repair or invent missing evidence.
- **Reason:** Real `qwen3-vl:8b` acceptance returned the requested structured JSON in the local
  thinking field even with thinking disabled. Supporting the actual Ollama response shape closes
  compatibility without weakening Schema or evidence checks.

## ID-073 — Make homepage exhaustion the default video scope (superseded)

- **Decision:** Interpret `AccountCollectionRequest.count = null` as all Provider-exposed homepage
  videos and make that the CLI default. Continue pagination until `has_more` is false. Retain
  `--count <1-20000>` only as an explicit user limit, detect repeated cursors, and stop with a
  visible warning at the 1,000-page or 20,000-video emergency guard.
- **Reason:** A fixed 10-video default made account distillation and later cross-account ranking
  sensitive to a small recent slice. Full accessible history provides the requested account-level
  evidence, while Provider termination, cursor detection, explicit paid-provider confirmation,
  and emergency guards prevent accidental infinite or uncontrolled collection.

## ID-074 — Make bounded TikHub collection the standard product entry point

- **Decision:** Supersede ID-073 at the CLI/API/Web entry points: default to TikHub, 20 recent
  videos, and zero comments. Preserve `AccountCollectionRequest.count = null` as the internal
  full-homepage contract, but expose it only through explicit `--all`. Keep MediaCrawler available
  only through `--provider mediacrawler`.
- **Reason:** The standard product must behave the same from a source checkout and an installed
  wheel. TikHub has a documented, browser-free boundary, while MediaCrawler has a separate
  non-commercial license, source checkout, Node/browser runtime, and manual login. A bounded default
  also makes time, cost, and evidence scope reviewable before users opt into comments or full history.

## ID-075 — Centralize and isolate API task execution

- **Decision:** Route blocking API services through one typed in-process executor with a stable task
  envelope, normalized `DistillerError` payloads, terminal progress, and one task store per FastAPI
  application instance.
- **Reason:** Four copied task runners had already diverged in error serialization and progress
  behavior, and the module-global task dictionary leaked state across application instances. One
  executor gives the Web console and API clients a single contract and creates a clean seam for a
  future persistent queue.

## ID-076 — Integrate OpenKB as an optional one-way sidecar

- **Decision:** Keep OpenKB out of the core dependency set. Export only bounded, privacy-aware
  account analysis documents to `knowledge-outbox/openkb/`, synchronize them through the OpenKB
  REST API with canonical payload hashes, and mark all query results non-authoritative. Require
  explicit model-processing confirmation before real sync/query operations.
- **Reason:** OpenKB adds cross-report compiled knowledge and long-term query value, but it does not
  collect platform data, understand video files, replace Parquet/DuckDB, or preserve Distiller's
  row-level evidence contract. A separate process isolates its Alpha dependency graph and lets an
  OpenKB outage fail only the optional knowledge surface.

## ID-077 — Queue the self-service workflow with SQLite claims and bounded leases

- **Decision:** Persist the serializable self-service account-distillation job before execution and
  let any API process sharing the same SQLite database atomically claim it. Enforce a bounded global
  concurrency limit, a stricter workflow resource limit, and a pending-task ceiling. Renew active
  claims with leases; when a lease expires, fail the task as explicitly retryable instead of
  automatically replaying it. Keep existing one-step API jobs in-process until each has a validated
  serializable job contract.
- **Reason:** Durable pending work must survive an API restart and multiple workbench processes must
  not duplicate expensive collection or media work. Automatic replay after an uncertain process
  failure could duplicate Provider charges or partially repeat immutable writes, so checkpoint-based
  user retry remains the safer boundary. Migrating the primary workbench workflow first closes the
  main M2 path without coupling every legacy service call to one oversized dispatcher change.

## ID-078 — Keep GPT credentials environment-only and freeze the pricing basis per run

- **Decision:** Accept only secret-free GPT analysis requests. Read `OPENAI_API_KEY` inside the API
  process, require a local preflight that exposes the bounded data scope, request fingerprints,
  selected model, rate-card snapshot, and conservative cost ceiling, and persist actual token usage
  with that immutable pricing basis. Save a separate fixed-question evaluation artifact; never
  write GPT output into Rule or Rubric records.
- **Reason:** Request-body credentials contradict the repository's environment-only secret
  contract and expand the browser/API leakage surface. A versioned price snapshot makes historical
  estimates reproducible even after public prices change, while the preflight and non-retryable
  task boundary prevent silent paid calls. Separate evaluation keeps model conclusions derived,
  reviewable, and comparable without weakening deterministic governance.

## ID-079 — Keep private-data provenance in immutable import receipts

- **Decision:** Classify imported data as `public`, `authorized_private`, `model_inferred`, or
  `unknown` in immutable import receipts, and retain the authorization grant ID for private imports.
  Normalize creator audience data through a versioned flat segment contract. Generate a fixed
  machine-readable account data-gap table that separates intended source tier, observed provenance,
  availability counts, and row-level evidence backlinks.
- **Reason:** Adding source labels directly to historical normalized rows would silently rewrite old
  provenance and make unchanged raw hashes appear newly trusted. Receipt-level provenance preserves
  the original authorization boundary, while `unknown` remains honest for legacy imports. A flat
  audience segment table is strict enough to validate shares and counts but portable across changing
  creator-center export shapes.

## ID-080 — Keep the productized Web redesign inside the Streamlit boundary

- **Decision:** Retain the existing Streamlit multipage runtime and FastAPI contracts, but centralize
  the visual shell, theme tokens, browser-persisted light/dark state, Chinese navigation, reusable
  cards, workflow steppers, form states, tables, badges, and responsive rules in one shared Web
  module. Keep page-specific business requests in their existing page modules.
- **Reason:** Replacing the frontend framework would add a second deployment and API-client surface
  while the current product workflows are still evolving. A shared Streamlit design layer removes
  the default prototype appearance and provides consistent SaaS behavior without duplicating or
  destabilizing collection, import, analysis, report, permission, and task-recovery logic.

## ID-081 — Select account-analysis providers explicitly without moving credentials into requests

- **Decision:** Keep one provider-neutral account-analysis contract and add Alibaba Cloud Model
  Studio beside OpenAI as an explicit Web/API choice. Validate a password-masked credential online,
  persist it only in the current operating-system user's secure keyring until the user updates or
  deletes it, allow only Alibaba Cloud HTTPS `compatible-mode/v1` endpoints, and retain
  provider-specific immutable USD/CNY pricing snapshots. Apply the same local schema, evidence
  allowlist, privacy gates, audit artifacts, and non-retryable paid-task boundary to both providers.
- **Reason:** A selectable provider lets operators choose the service appropriate for their region
  and account without forking the distillation pipeline. Operating-system credential storage avoids
  repeated local environment edits while keeping secrets outside projects and task records. Endpoint
  trust and shared validation prevent a compatibility API from weakening the evidence contract.

## ID-082 — Separate evidence readiness from knowledge distillation

- **Decision:** Always rebuild deterministic account patterns after media analysis, but report the
  workflow as only `evidence_ready` until an explicitly authorized account-level synthesis runs.
  Make DeepSeek V4 Flash with thinking enabled and high reasoning effort the default synthesis
  configuration. Keep the paid call optional, privacy-gated, mockable, and secret-free in durable
  task payloads; resolve credentials from the operating-system keyring or environment in the worker.
- **Reason:** A template-rendered report is not evidence that the system has formed reusable
  knowledge. Distinguishing the two states prevents the product from claiming “distillation
  complete” when it has only normalized and summarized evidence, while preserving an offline path.

## ID-083 — Persist model learning as candidate knowledge cards, never validated rules

- **Decision:** Require account synthesis to emit falsifiable knowledge cards containing a claim,
  mechanism, competing explanations, scope, boundary conditions, decision, trade-off, target metric,
  success condition, and stop condition. Persist them under `knowledge-base/claims/` as candidate or
  experimental records with evidence backlinks and mandatory human review. A single model run may
  assign maturity Level 0–3 only and cannot write or promote a Level-4 Rule or alter a Rubric.
- **Reason:** The durable asset is a testable operating proposition, not a metric inventory or a
  fluent report. Candidate isolation supports learning and later experiment-driven promotion without
  allowing one model response to bypass the existing evidence and governance lifecycle.

## ID-084 — Retire OpenKB and keep knowledge artifacts local

- **Decision:** Remove OpenKB from the Web, API, CLI, durable job registry, environment template,
  and automatic workflow language. Write new curated knowledge packages to
  `knowledge-outbox/local/` for local archival and Obsidian use. Preserve existing historical
  `knowledge-outbox/openkb/` files without migrating or deleting them.
- **Reason:** The durable product asset is the evidence-linked knowledge card and local knowledge
  package, not a dependency on a separate knowledge sidecar. Retiring the integration removes an
  unnecessary synchronization, credential, and model-processing surface while preserving history.

## ID-085 — Expand acquisition separately from selective media reparsing

- **Decision:** Increase the standard public-video acquisition window from 20 to 50 and the
  operator-selected media-enrichment ceiling from 20 to 100. Add a durable account-level reparse
  task that can target only failed/degraded videos, explicit retained video IDs, or the current
  retained batch. Preserve successful transcripts by default, optionally refresh media analysis,
  keep prior immutable artifacts, and rebuild account distillation after a successful retry.
- **Reason:** Metadata collection and multimodal parsing have different cost and failure profiles.
  A larger evidence window improves representativeness, while bounded selective retries prevent one
  transient download, transcription, or vision failure from forcing another account collection or
  overwriting prior evidence.

## ID-086 — Replace avoidable unknowns with bounded proxies, not invented facts

- **Decision:** During account distillation, prefer validated performance bands when available. If
  a public provider omits views but at least five videos retain public likes/comments/shares/saves,
  derive an explicitly labelled account-local public-interaction percentile solely for pattern and
  counterexample mining. Treat absence of an explicit CTA as an analyzable strategy category, infer
  a public-scale account stage from observed followers and published-video count, and render true
  evidence gaps as specific Chinese explanations instead of generic `unknown`/`none` tokens.
- **Reason:** Generic missing labels conceal whether the system lacks data, lacks taxonomy coverage,
  or observed a meaningful absence. A transparent proxy recovers useful comparisons without
  pretending that views, completion, conversion, causality, or business lifecycle are known.

## ID-087 — Carry the declared collection scope through downstream analysis

- **Decision:** Default comment coverage and media understanding to the operator's finite collection
  scope instead of independently resetting them to 20. Allow collection, media enrichment, and
  selective reparsing to share the 20,000-video safety ceiling. Aggregate every completed video
  analysis in deterministic distillation, then provide cloud/local knowledge synthesis with up to
  1,000 compact per-video evidence rows alongside the full-corpus clusters and patterns. Preserve
  immutable full analysis artifacts on disk and disclose whether the model context contains full
  detail or full-corpus aggregation plus a compact detail sample.
- **Reason:** Increasing acquisition alone creates false coverage when later stages silently truncate
  the corpus. Compact evidence rows remove the historical 25/50-item context bottleneck without
  duplicating long transcripts or exceeding the existing upload-size guard, while full-corpus
  deterministic aggregation retains information from accounts larger than the model detail cap.

## ID-088 — Treat a valid empty speech result as evidence, not a runtime failure

- **Decision:** When Whisper completes successfully and returns a valid segment list containing no
  usable speech, record transcription as complete with zero segments and the stable warning
  `no_speech_detected`. Continue media, visual, text, and account analysis even in strict workflows.
  Preserve hard failures for process errors, timeouts, malformed output, and unavailable runtimes.
- **Reason:** Music-only, ambient, and montage videos are valid account evidence. Retrying the same
  semantic result on CPU wastes time, while aborting a whole account batch confuses “no speech” with
  an infrastructure failure and discards usable visual and metadata evidence.

## ID-089 — Recover media sources from every retained provider response shape

- **Decision:** Build each video's allowlisted download candidates by merging immutable evidence from
  single-video detail payloads, wrapped detail payloads, and `aweme_list` account-list payloads.
  Deduplicate URLs without refreshing or inventing signed sources. If all retained shapes genuinely
  lack a source, record that video as failed with `retained_source_unavailable` and continue the
  account batch even when strict media processing is enabled; actual download and decode failures
  retain strict failure behavior.
- **Reason:** Public detail calls may degrade while the already-retained account listing still
  contains valid play addresses. Ignoring that evidence creates a false download failure. A truly
  unavailable, deleted, or restricted video is a per-item evidence gap and should not discard the
  rest of an otherwise valid account analysis.

## ID-090 — Bound local vision JSON before increasing its generation budget

- **Decision:** Keep llama.cpp vision output under the strict Pydantic-derived JSON Schema, while
  adding explicit maximum lengths for summaries, labels, OCR text, arrays, and bounding boxes.
  Increase the single-frame completion budget from 2,048 to 4,096 tokens. When llama.cpp reports a
  length-truncated completion, retry from the original image with a compact instruction instead of
  feeding the incomplete assistant JSON back into the conversation. Continue to reject any final
  response that does not validate; never persist truncated or repaired-by-guesswork model JSON.
- **Reason:** A visually dense frame can make Qwen enumerate unconstrained arrays until the token
  ceiling, leaving syntactically incomplete JSON. Raising the ceiling alone only delays that failure,
  while replaying a truncated response encourages continuation of an invalid object. Schema bounds
  make generation finite and the clean retry preserves both evidence grounding and strict validation.

## ID-091 — Do not treat image-post background audio as a video source

- **Decision:** Detect retained Douyin image posts from their non-empty `images` collection and
  zero-duration video envelope before extracting media candidates. Do not download the associated
  `video.play_addr`, because it is the slideshow background audio rather than a video stream. Record
  the item as `retained_non_video_post`, continue strict account enrichment, preserve its metadata and
  comments for downstream account analysis, and do not recommend reparsing against the same retained
  batch.
- **Reason:** Douyin type-68 carousel posts use the same response envelope as videos and may expose
  `audio/mp4` or MP3 URLs under `video.play_addr`. Passing those URLs to the video decoder produces a
  false media-download or no-video-stream failure and can abort an otherwise valid account batch.
  Explicit classification preserves the evidence boundary without pretending that background audio
  is visual footage.

## ID-092 — Distill shooting techniques and expression forms as labeled craft patterns

- **Decision:** Extend the vision contract (prompt 1.4.0) with explicit `shot_scale` and
  `camera_movement` fields while keeping the legacy `camera` field for viewpoint/angle; mirror the
  angle into `ShotVisualAnnotation.camera_angle`. Aggregate per-shot labels into per-video
  `MediaFeatureRecord` craft tags (`shot_scale_tags`, `camera_movement_tags`, `camera_angle_tags`,
  `composition_tags`, `lighting_tags`) plus deterministic `opening_technique_tags` (from the first
  shot) and `pacing_tags` (from measured shot duration). At account level, build one `CraftProfile`
  whose per-tag coverage denominators are explicit (vision-annotated media for visual categories,
  shot-bearing media for pacing), promote a `signature_style`, mine each tag as a `craft` Pattern
  against account-local S/A versus C/D bands, and carry `craft_identity` into benchmark profiles.
  All new model fields default to empty so pre-existing artifacts and replays stay readable.
- **Reason:** The account previously summarized vision labels only as merged, coverage-free text
  lines, so recurring shooting techniques and expression forms could not be compared, mined against
  performance, or transferred between accounts. Craft tags stay deterministic aggregations of model
  labels: camera motion is best-effort from still frames and must not be presented as measured fact,
  so unknowns and low-coverage warnings remain explicit, and craft Patterns are Level 0/1
  observations exactly like text Patterns.

