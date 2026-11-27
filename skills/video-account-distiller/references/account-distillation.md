# Account distillation and benchmark transfer

Distill only after normalization and account-local metrics. Prefer completed comment analysis and
multiple blind single-video analyses; otherwise expose coverage warnings and proxy labels.

The report must include data scope, observable positioning, content clusters, audience-need
clusters, persona unknowns/signals, Patterns, support, counterexamples, strengths, failure modes,
copyable/noncopyable factors, actions, experiments, evidence, and warnings. Write versioned Pattern
JSON to `knowledge-base/patterns/` and a latest account profile pointer under
`knowledge-base/accounts/`.

When local media analysis exists, the report also includes a 拍摄手法与表现形式 craft profile:
per-tag coverage for shot scale, camera motion, camera angle, composition, lighting, text styles,
motion graphics, branding, opening technique, and editing rhythm, plus a signature style line.
Each craft tag reaching `min_pattern_support` may become a `craft` Pattern with account-local S/A
support versus C/D counterexamples. Craft tags are model-label observations, not measurements or
causal rules; camera-motion tags are best-effort from still frames. Benchmark profiles carry this
profile as `craft_identity` so comparisons can show each account's signature craft side by side.

For benchmark transfer, distill every account separately. Never compare raw cross-account or
cross-platform views. Evaluate feature overlap and platform alignment; keep audience, account
stage, resources, and business alignment as unknown unless the user supplied them. Use these
verdicts: directly test, adapt then test, understand only, or do not migrate. Every transfer item is
a planning hypothesis and must lead to a bounded target-account experiment, not copying.

After distillation, run `distiller account benchmark-profile`. Preserve every content-addressed
`abp_*` profile. It summarizes the latest retained public snapshot using per-video medians and
totals for likes, comments, shares, and saves/favorites, interaction mix, optional interactions per
1,000 followers, comment semantics, content pillars, and visual identity. `distiller compare`
embeds the exact profiles and ranks target-platform accounts on available public-interaction
dimensions. Report per-account data coverage; exclude cross-platform accounts and unavailable
views from ranking while still allowing a conservative Pattern transfer review.
