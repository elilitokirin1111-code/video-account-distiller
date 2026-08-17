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

## Shooting techniques and expression forms (craft distillation)

When local media analysis is available (`analyzed_media_count > 0`), distillation additionally
builds a `craft_profile` that aggregates per-video shooting-technique and expression-form tags into
one traceable account-level image:

- 景别 shot scale (`shot_scale`): 特写/近景/中景/全景/远景 tags from vision annotations.
- 运镜手法 camera movement (`camera_movement`): 固定机位/手持/推拉摇移跟 best-effort tags.
- 机位角度 camera angle (`camera_angle`): 平视/俯视/仰视/斜角 tags.
- 构图 composition, 光线 lighting, 字幕与艺术字 text overlay, 动效与贴纸 motion graphics,
  品牌露出 branding.
- 开场手法 opening technique: deterministic tags derived from the first shot's labels, such as
  特写开场 / 固定机位开场 / 开场大字标题 / 开场即出字幕.
- 剪辑节奏 editing rhythm: measured median shot duration and a 快/中/慢 pacing label.

Every tag carries `video_count`, the covering `video_ids`, and a coverage ratio against its own
denominator (vision-annotated media for visual categories, all shot-bearing media for pacing).
`signature_style` promotes the account's recurring combination (e.g.
`近景 + 手持 + 自然光 + 大字标题`) and per-category top tags above 30% coverage. The profile is
content-addressed into the distillation ID, exported as evidence
(`account.craft_profile`), and listed in the report's
「拍摄手法与表现形式画像」section.

Craft tags participate in Pattern mining exactly like text features: each tag reaching
`min_pattern_support` becomes a `craft` Pattern with S/A support versus C/D counterexamples
(replicability `high`, scope pillars empty). These associations remain observations — a camera
technique that correlates with high interaction in the current sample is not a proven cause.

Coverage warnings (`craft_profile_vision_annotations_low`,
`craft_profile_no_aggregatable_craft_tags`) appear when the visual evidence is too thin to
distill, and the positioning `unknowns` explain what is missing.

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
pillars, and visual identity. Since profile version 1.1.0 it also stores `craft_identity`, the
distillation's shooting-technique/expression-form profile, so the comparison report can show each
account's signature craft side by side. Profiles are content-addressed: a later collection or
labeling version creates another profile without replacing history.

The comparison ranks only target-platform accounts on available public interaction dimensions,
reports data coverage, and embeds the exact profiles used. Public-homepage views are not used and
missing metrics are never zero-filled. The transfer matrix
checks content-feature overlap, Pattern maturity, platform alignment, replicability, and risks.
Audience, account stage, resources, and business alignment remain unknown unless supplied by the
user. Verdicts are `directly_test`, `adapt_then_test`, `understand_only`, or `do_not_migrate`.

Cross-platform raw views are never compared. Cross-platform items default to understanding rather
than direct migration, are excluded from interaction ranking, and every transferable item becomes
a target-account experiment rather than a copying instruction.
