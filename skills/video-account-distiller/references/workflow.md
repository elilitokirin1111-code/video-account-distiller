# Phase 0/1/2/3/4/5/6 workflow

## Sequence

1. Confirm the task uses offline user-provided exports.
2. From the repository root, initialize a project with `uv run distiller init`.
3. Import accounts before videos, videos before metrics/comments where practical.
4. Inspect each import receipt and paired quality reports.
5. Run `uv run distiller validate` to verify raw hashes and staging schemas.
6. Run `uv run distiller normalize` to rebuild Parquet.
7. Run `uv run distiller status` and capture internal account IDs.
8. Run `uv run distiller metrics` separately for each account.
9. Run `uv run distiller sample` for a traceable stratified sample.
10. Run `uv run distiller report` for account-health JSON, Markdown, evidence, and warnings.
11. Import SRT/VTT/TXT/JSON transcripts using an internal or unique platform video ID, then
    normalize again.
12. Run `uv run distiller analyze video` for blind text labels and post-label performance context.
13. Run `uv run distiller validate` again to verify analysis isolation and its evidence chain.
14. Run `uv run distiller analyze comments` for redacted comment signals and need clusters.
15. Run `uv run distiller distill` for content clusters, Patterns, counterexamples, and actions.
16. Build a content-addressed `account benchmark-profile` after each distillation.
17. Distill and profile every account separately before `uv run distiller compare`.
18. Run `uv run distiller validate` again to verify Phase 4 evidence and knowledge artifacts.
19. Run `uv run distiller score` to check a new script against the current Rubric.
20. Run `uv run distiller predict` to save an immutable account-local interval.
21. Import/normalize the published video, then run `uv run distiller publish`.
22. Import later metric snapshots, recalculate metrics, and run `uv run distiller retro`.
23. Run `uv run distiller validate` to verify the complete closed-loop evidence chain.
24. Run `uv run distiller analyze media` for local scene/keyframe/audio and optional OCR evidence.
25. Run `uv run distiller validate` to verify raw media, frames, timeline, and evidence hashes.
26. For an approved retained account batch, preview and run `distiller account enrich-media` to
    add local media, transcript, single-video semantics, and a rebuilt account distillation.
27. Run `uv run distiller validate` to verify the account media-enrichment bridge.
28. Query with DuckDB only after normalization.

## Idempotence

The same entity/platform/input hash returns the existing receipt and changes nothing. A dry run
must not change state, raw data, staging, Parquet, or manifests. Repeated normalization rebuilds the
same record population; repeated metrics replace that account's derived rows instead of appending
duplicates. Samples and reports use content-addressed IDs and reuse unchanged artifacts.
Transcript imports are keyed by video plus raw hash. Video analyses use content-addressed `vta_*`
IDs and never overwrite an existing analysis.
Comment analyses, account distillations, Patterns, and comparisons use content-addressed `cma_*`,
`dst_*`, `pat_*`, and `cmp_*` IDs. Knowledge Pattern files are immutable; the account profile and
knowledge index are rebuildable latest pointers.
Account benchmark profiles use `abp_*`; new public metric/comment/distillation inputs create a new
profile while every earlier profile remains available for historical comparison.
Scores and predictions use content-addressed `score_*` and `pred_*` IDs. Predictions and
publications are immutable. Retros use `retro_*`; repeating the same publication/snapshot/version
reuses the existing review. Retro writes pending proposals without modifying Rule or Rubric files.
Media analyses use content-addressed `mda_*` IDs, immutable `raw/media/<sha256>.<ext>` copies, and
stable `shot_*`/`key_*` evidence. Repeating identical media/config/provider inputs reuses the result.

## Project evidence

- `.distiller-state.json`: imports and latest successful stages.
- `raw/imports/`: exact source bytes named by SHA-256.
- `staging/`: validated canonical JSONL.
- `normalized/`: Parquet source of analytical truth.
- `runs/<run-id>/manifest.json`: command, hashes, counts, warnings, outputs.
- `runs/<run-id>/quality-report.{json,md}`: data-quality evidence.
- `analyses/accounts/<account-id>/samples/<sample-id>/sample-manifest.json`: selection reasons and
  coverage.
- `reports/accounts/<account-id>/<report-id>/`: JSON, Markdown, evidence index, and warnings.
- `analyses/videos/<video-id>/<analysis-id>/`: blind analysis, combined analysis, Markdown report,
  evidence index, and warnings.
- `analyses/comments/<account-id>/<analysis-id>/`: redacted signals, need clusters, evidence, and
  warnings.
- `reports/accounts/<account-id>/<distillation-id>/`: account distillation JSON/Markdown/evidence.
- `reports/comparisons/<comparison-id>/`: benchmark transfer matrix and evidence.
- `analyses/accounts/<account>/benchmark-profiles/<abp_*>/`: reusable interaction, comment,
  content, and visual account snapshots for later ranking.
- `knowledge-base/patterns/`: versioned Pattern JSON with support and counterexamples.
- `knowledge-base/rules/` and `knowledge-base/rubrics/`: versioned scoring inputs.
- `candidates/` and `reports/scoring/`: script candidate and explainable score artifacts.
- `predictions/` and `publications/`: immutable prediction and publication linkage.
- `reports/retros/` and `knowledge-base/reviews/`: prediction errors and pending proposals.
- `analyses/media/<video-id>/<analysis-id>/`: media analysis, timeline, frames, evidence, warnings.
- `analyses/accounts/<account>/media-enrichments/<ame_*>/`: retained batch, media, transcript,
  text-analysis, and rebuilt-distillation links.

## Failure handling

Use the stable code in JSON output. Do not retry malformed data blindly. For mapping failures, show
missing and available fields and request a mapping file. For partial invalid files, preserve valid
rows and direct the user to the quality report. For raw hash mismatch, stop before normalization.
