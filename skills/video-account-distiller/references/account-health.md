# Account-health reports

Phase 2 reports are deterministic and account-local. They include:

- data scope, missingness, promotion, outlier, and small-sample warnings;
- follower snapshot, publication cadence, duration, views, engagement, and completion summaries;
- S/A/B/C/D distribution, high-performance rate, and longest C/D streak;
- `content_type` distribution as an explicitly labeled pillar proxy;
- high (S/A), middle (B), and low (C/D) cohort medians;
- the stratified sample manifest;
- JSON, Markdown, `evidence-index.json`, and `warnings.json`.

Every statistic and finding must carry an `evi_*` reference. Resolve it in the evidence index to
normalized record IDs, source record IDs, raw hashes, and source run IDs. Report generation reads
normalized Parquet only and never mutates raw exports.

Pass `--sample-size <n>` to `distiller report` when the user specified a sampling target. This keeps
the report tied to the same deterministic sample request even if the project default later changes.

Classify direct values as facts and cohort differences as statistical associations. Do not claim
causality, content strategy, audience intent, semantic pillars, stable patterns, or guaranteed
performance from an account-health report alone. Phase 3/4 artifacts may add text labels, comment
needs, and candidate Patterns, but they remain separately scoped evidence rather than retroactive
proof for Phase 2 findings.
