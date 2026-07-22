# Pattern and counterexample evidence

A Phase 4 Pattern must include a readable feature condition, target metric, support video IDs,
counterexample video IDs, counts, account/platform scope, confounders, confidence, maturity,
replicability, risks, version, timestamps, and evidence IDs.

Build content features before comparing performance. Use account-local S/A versus C/D bands.
Exclude promoted and Robust-outlier videos from support/counterexample counts but retain them as
visible confounders. Keep support and counterexample sets disjoint and never create a Pattern with
zero support.

Phase 4 may emit only:

- Level 0 observation when evidence or counterexamples are limited.
- Level 1 association when repeated account-local support and counterexamples exist.

Do not emit Level 2 causal explanations as facts, Level 3 experiment rules, or Level 4 validated
rules. Missing counterexamples lower confidence and create an explicit active-validation risk.
Opaque cluster IDs are not business conclusions; every cluster needs a semantic or proxy label.
