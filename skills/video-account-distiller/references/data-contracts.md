# Data contracts

Core normalized schema version is `0.1.0`; Phase 2 analysis artifacts use `0.2.0`; transcript and
text-analysis contracts use `0.3.0`; comment, Pattern, distillation, and comparison artifacts use
`0.4.0`; Rubric, Rule, candidate, score, prediction, publication, experiment, and Retro artifacts
use `0.5.0`; local media analysis contracts use `0.6.0`; authorization, collaboration Sync, Batch,
Snapshot, and Team contracts use `0.7.0`. Executable Pydantic models reject unknown fields.

Normalized tables are `accounts`, `account_snapshots`, `videos`, `metric_snapshots`, `comments`,
`transcripts`, `derived_metrics`, and `media_features`. Every core row includes source platform/type/URI/record ID, collected and
ingested timestamps, run ID, raw hash, schema version, and quality flags.

Treat these cases differently:

- Unknown: `null`.
- Known zero: `0` or `0.0`.
- Invalid negative count/duration/spend: rejected row.
- Zero or unknown denominator: derived rate is `null`.

Stable internal IDs derive from platform plus platform record IDs. Keep current account followers
separate from `follower_count_at_publish`. Do not substitute the current count silently.

Transcript timing may be `null`; never invent timestamps for TXT. Phase 3 semantic output must cite
existing transcript segment IDs. `blind-analysis.json` must contain no performance fields.

Phase 4 IDs use `cma_*` comment analyses, `cms_*` comment signals, `cnc_*` need clusters, `dst_*`
account distillations, `clu_*` content clusters, `pat_*` Patterns, and `cmp_*` comparisons. Every
Pattern requires support, a counterexample field, disjoint sample sets, scope, maturity, version,
risks, and evidence IDs. Core records are not rewritten.

Phase 5 IDs use `rule_*`, `rub_*`, `cand_*`, `score_*`, `pred_*`, `pub_*`, `retro_*`, and `exp_*`.
Rubric weights must total 100. Prediction quantiles must satisfy P25 ≤ P50 ≤ P75 and include
`immutable: true`. Rule versions are stored separately; Retro proposals are `pending` and do not
replace their source Rule/Rubric.

Phase 6 IDs use `mda_*`, `mdf_*`, `shot_*`, and `key_*`. Shot intervals are non-negative,
non-overlapping, and exactly match duration. Keyframes carry a local path and SHA-256. OCR must cite
an existing shot/keyframe and timestamp evidence. Unknown decoder, audio, OCR, and visual values stay
`null` or absent; they are never inferred as zero/false.

Retained account media enrichment uses `ame_*` and strict `AccountMediaEnrichment`,
`VideoMediaEnrichment`, and `TranscriptionSummary` models under the Phase 6 schema. The artifact
links one retained Provider batch hash to media/transcript/text-analysis IDs and a rebuilt
distillation. `VideoMediaEnrichment.status` covers the media/transcription chain and
`text_analysis_status` separately marks a bounded heuristic result as degraded. Signed source URLs
are forbidden in this contract.

Phase 7 authorization grants bind one connector, resource, operation, and expiry. Connector files
contain environment-variable names, never credential values. Sync receipts record requested,
completed, and failed row counts; a partial remote write remains `partial`. Pulled provider pages are
content-addressed under `raw/collaboration/` before rows enter the existing import pipeline. Batch,
scheduled Snapshot, and Team files are schema-validated, auditable artifacts rather than hidden
background state.

For full field definitions, read the repository `docs/data-contracts.md` and
`docs/planning/04_DATA_SCHEMA.md`.
