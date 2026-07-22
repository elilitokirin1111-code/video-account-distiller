# Stratified sampling and account-health reports

## Scope

Phase 2 operates entirely on normalized Parquet and `DerivedMetrics`. It does not inspect raw CSV,
call a model, access a platform, infer semantic content pillars, or produce causal content rules.

## Sampling policy

`distiller sample` uses a deterministic, account-local strategy. It prioritizes:

1. promotion/ad and Robust Z-score outliers;
2. all available S/A/B/C/D performance bands;
3. major `content_type` values as a content-pillar proxy;
4. short (<30s), medium (30–59s), long (>=60s), and unknown duration buckets;
5. recent videos;
6. balanced round-robin fill across performance bands.

Default sample targets follow the planning guidance:

| Population | Default target |
|---:|---:|
| `<30` | all videos |
| `30–100` | configured value clamped to `20–40` |
| `101–500` | configured value clamped to `40–80` |
| `>500` | configured value clamped to `60–120` |

`--size` overrides the configured value but is capped at the population. The manifest preserves
requested, target, and selected sizes separately. A content-addressed ID includes the policy
version, input hashes, target size, and selected IDs.

## Account statistics

The account-health report calculates:

- observed period and current follower snapshot;
- publication frequency and gap distribution;
- duration, views, performance score, engagement, and completion five-number summaries;
- S/A/B/C/D distribution and high-performance hit rate;
- longest chronological C/D streak;
- content-type proxy and data-quality-flag distributions;
- promotion/ad and outlier counts;
- high (S/A), middle (B), and low (C/D) cohort medians.

Missing values remain `null`; every summary reports known and missing counts. Promotion and
outliers remain in the population but are explicitly warned and sampled.

## Evidence contract

Every report statistic contains an `evidence_id`; findings contain `evidence_ids`. The separate
`EvidenceIndex` resolves those IDs to:

- normalized table and record ID;
- source record ID;
- raw hash;
- source run ID;
- calculation description and value.

The report bundle always contains:

```text
reports/accounts/<account-id>/<report-id>/
├── report.json
├── report.md
├── evidence-index.json
└── warnings.json
```

Reports are content-addressed and reused when inputs, sample, and report version are unchanged.
`--dry-run` calculates the complete machine result without creating artifacts or run state.

## Interpretation boundary

High/middle/low comparisons are statistical associations within one account and platform. They do
not establish causality, audience intent, content strategy, transferable patterns, or guaranteed
performance. Small samples remain descriptive and carry explicit warnings.
