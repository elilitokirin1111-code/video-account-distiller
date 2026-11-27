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

This command is text-only analysis. Use the separate Phase 6 `analyze media` workflow for observed
shot rhythm, keyframes, signal-level audio, and schema-cited OCR/visual evidence. Do not backfill
these fields from transcript guesses. A single video can provide facts and hypotheses but
cannot establish an account Pattern or validated rule.

## Deep single-video distillation

`distiller analyze video --deep` merges the blind text analysis with any existing local media
analysis into one `svd_*` reference card: 选材 topic (angle/audience/information increment/memory
point/topic formula), 表现形式 expression (opening form/subtitle style/packaging/audio/editing),
拍摄手法 craft (shot scale/camera/composition/lighting/opening/pacing plus deterministic
per-shot counts), and a 可复制清单 copy checklist with what to avoid. It works on one video from
an account the user does not follow; it never needs account-level performance bands.

The deep stage is optional: pass `--deep-provider ollama|llamacpp|cloud` with `--deep-model`,
`--deep-base-url`, `--deep-api-key`, or offline `--deep-output` JSON. Model citations are filtered
to real `segment_id`/`shot_id` evidence. Without a provider the service degrades visibly
(`status: degraded`) to deterministic aggregation of blind labels and measured media features;
`--strict-deep` fails instead. `distiller validate` checks the `svd_*` artifacts and their
evidence links.

To push the reference card into WeKnora, run
`distiller knowledge weknora sync-video --project <dir> --video <video-id> --kb-id <id>
--base-url http://127.0.0.1:8080 --api-key $env:WEKNORA_API_KEY` (or the equivalent
`POST /api/projects/{project}/knowledge/weknora/videos/{video_id}/sync`). The HTTP analyze route
(`POST /api/projects/{project}/analyze/video/{video_id}` with `deep: true`) supports
`deep_provider cloud` with credentials resolved from the workspace credential store, never from the
request body.
