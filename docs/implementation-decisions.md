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
