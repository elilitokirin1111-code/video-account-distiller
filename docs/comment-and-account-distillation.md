# Comment analysis, Patterns, and account distillation

## Comment privacy and labeling

Phase 4 reads normalized comments from user-provided exports. Raw bytes remain immutable and author
identifiers remain hashed. Before prompting or reporting, the pipeline creates an analysis copy and
redacts common phone numbers, email addresses, URLs, social handles, and contact IDs.

Each comment receives a strict `CommentSignalAnnotation` covering sentiment, intent, pain points,
questions, objections, purchase intent, identity signals, content opportunities, spam probability,
confidence, and unknowns. Offline structured candidates are retried; unavailable or exhausted
providers degrade visibly to deterministic keyword labels.

Need clusters use a stable intent priority rather than opaque embedding cluster numbers. Every
cluster records frequency, intensity, covered videos, representative comment IDs, content
opportunities, and evidence. Reports always warn that exported commenters are not all viewers and
that ranking, pinning, deletion, controversy, and export limits bias the sample.

## Content clusters and Pattern evidence

Content clustering prefers existing blind semantic pillars. Unanalyzed videos fall back to the
normalized `content_type` proxy and are labeled accordingly. Cluster summaries use account-local
performance bands and scores.

A Pattern is created only when the feature group reaches `analysis.min_pattern_support` and has at
least one support video. Support and counterexamples are selected from account-local S/A and C/D
bands. Promoted or Robust-outlier videos are excluded from those counts but retained as confounders.

Every Pattern contains:

- readable feature conditions and target metrics;
- support and counterexample video IDs with consistent counts;
- platform/pillar scope, effect summary, confounders, risks, and replicability;
- confidence, maturity, version, validation time, and evidence IDs.

Phase 4 emits only Level 0 observations and Level 1 associations. It never emits a Level 4
validated rule. Missing counterexamples lower confidence and trigger active-validation warnings.

## Account outputs

`distiller distill` produces `distillation.json`, `report.md`, `evidence-index.json`, and
`warnings.json` under `reports/accounts/<account>/<dst_*>/`. The report includes observable
positioning, content and comment clusters, persona signals/unknowns, strengths, failure modes,
copyable and noncopyable factors, actions, and bounded experiments.

Versioned Pattern JSON is written to `knowledge-base/patterns/`; the latest stable account profile
pointer is written to `knowledge-base/accounts/`, with a rebuildable `knowledge-base/index.json`.

## Benchmark transfer

Distill target and benchmark accounts separately, then persist each reusable snapshot:

```bash
distiller account benchmark-profile --project <dir> --account <account-id> --json
distiller compare --project <dir> --target <account-id> \
  --benchmarks <account-id-1>,<account-id-2> --json
```

Each `abp_*` profile stores the latest public per-video likes/comments/shares/saves medians and
totals, interaction mix, optional per-1,000-follower interaction, comment-like coverage, sentiment,
intent, questions, pain points, objections, purchase intent, spam, content opportunities, content
pillars, and visual identity. Profiles are content-addressed: a later collection or labeling
version creates another profile without replacing history.

The comparison ranks only target-platform accounts on available public interaction dimensions,
reports data coverage, and embeds the exact profiles used. Public-homepage views are not used and
missing metrics are never zero-filled. The transfer matrix
checks content-feature overlap, Pattern maturity, platform alignment, replicability, and risks.
Audience, account stage, resources, and business alignment remain unknown unless supplied by the
user. Verdicts are `directly_test`, `adapt_then_test`, `understand_only`, or `do_not_migrate`.

Cross-platform raw views are never compared. Cross-platform items default to understanding rather
than direct migration, are excluded from interaction ranking, and every transferable item becomes
a target-account experiment rather than a copying instruction.
