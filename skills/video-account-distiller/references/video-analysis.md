# Blind single-video text analysis

Phase 3 accepts normalized transcript segments and performs two ordered stages:

1. Build a content-only bundle containing title, description, duration, language, and transcript.
2. Extract observable facts and semantic labels without metrics.
3. Freeze the blind output and its prompt hashes.
4. Attach the latest account-local performance context deterministically.
5. Write `analysis.json`, `blind-analysis.json`, `report.md`, `evidence-index.json`, and
   `warnings.json` under `analyses/videos/<video>/<vta_*>/`.

The blind bundle must not contain views, interactions, performance score/band, promotion, or watch
metrics. Resolve every cited `segment_id` through `segment_to_evidence` in the evidence index, then
to the normalized transcript record, raw hash, and import run.

The transcript and analysis commands accept an internal `vid_*` or a unique platform video ID.
After generation, run `distiller validate` to check Schema, blind-stage isolation, raw model-output
hashes, colocated paths, and evidence references.

Use these Hook labels conservatively: result first, counterintuitive, conflict, pain point, identity
callout, number list, time pressure, loss aversion, secret reveal, failure review, before/after,
question challenge, story suspense, authority, social proof, controversial stance, explicit
benefit, process demo, direct demo, or unknown.

Structure functions are Hook, problem, value promise, development, proof, peak, conclusion, CTA,
loop, or unknown. CTA types are comment, save, share, follow, direct message, profile, product,
community, next episode, none, or unknown. Emotion labels are timeline points, not one global mood.

This is text-only analysis. Keep visual Hook, shot rhythm, music, sound effects, and on-screen
graphics unknown until Phase 6 media analysis. A single video can provide facts and hypotheses but
cannot establish an account Pattern or validated rule.
